"""The check history: reused receipts, the record of every check, and CSV export."""

import csv
import threading
import time
from pathlib import Path

import pytest

from cepxico import pipeline
from cepxico.banxico import CEPResult, CEPStatus
from cepxico.cli import main
from cepxico.history import Check, History, write_csv
from cepxico.pipeline import Outcome, process_file, process_files
from tests.test_pipeline import COMPLETE
from tests.test_pipeline import FakeClient as PipelineFakeClient


class FakeClient(PipelineFakeClient):
    def close(self):
        pass


FOUND = CEPResult(CEPStatus.FOUND, "ok", pdf_path=Path("CEP_x.pdf"))


@pytest.fixture
def history(tmp_path) -> History:
    return History(tmp_path / "history.sqlite3")


@pytest.fixture(autouse=True)
def extracted(monkeypatch):
    """Every receipt reads as the same transfer."""
    monkeypatch.setattr(pipeline, "extract_payment", lambda _path: COMPLETE)


def receipt(tmp_path, name: str, content: bytes = b"%PDF one") -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def test_same_transfer_on_another_receipt_is_flagged_without_asking_banxico(tmp_path, history):
    first = process_file(receipt(tmp_path, "juan.pdf"), FakeClient(FOUND), history=history)
    client = FakeClient(FOUND)
    second = process_file(receipt(tmp_path, "pedro.pdf", b"%PDF two"), client, history=history)

    assert first.outcome is Outcome.SUCCESS
    assert second.outcome is Outcome.REVIEW
    assert second.message.startswith("Receipt already used: Banxico confirmed this transfer on ")
    assert "for juan.pdf; not checked again" in second.message
    assert client.calls == []  # saved a Banxico lookup


def test_forwarded_copy_of_the_same_file_is_flagged(tmp_path, history):
    """Forwarding a screenshot keeps its bytes; only the file name or folder changes."""
    process_file(receipt(tmp_path, "IMG-001.pdf"), FakeClient(FOUND), history=history)
    (tmp_path / "forwarded").mkdir()
    copy = receipt(tmp_path / "forwarded", "IMG-001.pdf")
    assert process_file(copy, FakeClient(FOUND), history=history).outcome is Outcome.REVIEW


def test_checking_the_same_file_again_is_fine(tmp_path, history):
    path = receipt(tmp_path, "juan.pdf")
    assert process_file(path, FakeClient(FOUND), history=history).outcome is Outcome.SUCCESS
    assert process_file(path, FakeClient(FOUND), history=history).outcome is Outcome.SUCCESS


def test_a_different_file_saved_over_the_old_one_is_another_receipt(tmp_path, history):
    path = receipt(tmp_path, "comprobante.pdf")
    process_file(path, FakeClient(FOUND), history=history)
    path.write_bytes(b"%PDF someone else's")
    assert process_file(path, FakeClient(FOUND), history=history).outcome is Outcome.REVIEW


def test_only_confirmed_transfers_count_as_used(tmp_path, history):
    not_found = CEPResult(CEPStatus.NOT_FOUND, "No existe")
    assert process_file(receipt(tmp_path, "a.pdf"), FakeClient(not_found), history=history).outcome is (
        Outcome.NOT_FOUND
    )
    later = process_file(receipt(tmp_path, "b.pdf", b"%PDF b"), FakeClient(FOUND), history=history)
    assert later.outcome is Outcome.SUCCESS


def test_a_flagged_receipt_doesnt_take_the_transfer_from_the_first(tmp_path, history):
    first = receipt(tmp_path, "juan.pdf")
    process_file(first, FakeClient(FOUND), history=history)
    process_file(receipt(tmp_path, "pedro.pdf", b"%PDF two"), FakeClient(FOUND), history=history)
    assert process_file(first, FakeClient(FOUND), history=history).outcome is Outcome.SUCCESS


def test_two_receipts_of_one_transfer_in_the_same_batch_cant_both_pass(tmp_path, history):
    class SlowClient(FakeClient):
        def download_cep(self, **query):
            time.sleep(0.2)  # both lookups are in flight before either is recorded
            return super().download_cep(**query)

    paths = [receipt(tmp_path, "a.pdf", b"%PDF a"), receipt(tmp_path, "b.pdf", b"%PDF b")]
    started = threading.Barrier(2)

    def factory(_catalogs):
        started.wait(timeout=5)
        return SlowClient(FOUND)

    results = process_files(paths, tmp_path, jobs=2, client_factory=factory, history=history)

    assert sorted(r.outcome.value for r in results) == ["review", "success"]
    review = next(r for r in results if r.outcome is Outcome.REVIEW)
    assert review.message.startswith("Receipt already used") and "not checked again" not in review.message


def test_every_check_is_recorded(tmp_path, history):
    result = process_file(receipt(tmp_path, "juan.pdf"), FakeClient(FOUND), history=history)
    process_file(tmp_path / "missing.pdf", FakeClient(FOUND), history=history)

    newest, oldest = history.checks()
    assert (newest.file_name, newest.outcome, newest.message) == ("missing.pdf", "failed", "File not found")
    assert oldest.outcome == "success" and oldest.message == result.message
    assert oldest.tracking_key == COMPLETE.tracking_key
    assert oldest.account == COMPLETE.beneficiary_account
    assert oldest.amount == "10.00"
    assert oldest.sender_bank == "BANORTE" and oldest.receiver_bank == "BBVA MEXICO"
    assert oldest.cep_file == "CEP_x.pdf"
    assert len(oldest.file_hash) == 64


def test_a_broken_history_doesnt_lose_the_result(tmp_path):
    (tmp_path / "taken").mkdir()
    broken = History(tmp_path / "taken")  # a folder, so the database can't be opened
    result = process_file(receipt(tmp_path, "juan.pdf"), FakeClient(FOUND), history=broken)
    assert result.outcome is Outcome.SUCCESS


def test_csv_opens_cleanly_in_excel(tmp_path):
    check = Check(
        checked_at="2026-11-17T10:05:00-06:00",
        file_name="año.pdf",
        file_path="C:/r/año.pdf",
        file_hash="",
        outcome="success",
        message="CEP saved",
        tracking_key="085901234567890123",
        account="012180001234567893",
        amount="1234.50",
        beneficiary_name="JOSÉ PÉREZ",
        edited=True,
    )
    out = tmp_path / "out.csv"
    write_csv(out, [check])

    assert out.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM: Excel reads it as UTF-8
    header, row = list(csv.reader(out.open(encoding="utf-8-sig")))
    values = dict(zip(header, row, strict=True))
    assert values["Checked"] == "17/11/2026 10:05"
    assert values["File"] == "año.pdf"
    assert values["Result"] == "Success"
    assert values["Account"] == '="012180001234567893"'  # text, not 1.2E+17
    assert values["Clave de rastreo"] == '="085901234567890123"'
    assert values["Beneficiary"] == "JOSÉ PÉREZ"
    assert values["Typed by user"] == "yes"


def test_cli_records_history_and_exports_it(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "BanxicoCEPClient", lambda out, catalogs: FakeClient(FOUND))
    path = receipt(tmp_path, "juan.pdf")
    run_csv = tmp_path / "run.csv"

    assert main([str(path), "--csv", str(run_csv)]) == 0
    assert main([str(receipt(tmp_path, "pedro.pdf", b"%PDF two"))]) == 1  # reused: review
    main([str(receipt(tmp_path, "otro.pdf", b"%PDF 3")), "--no-history"])  # not recorded

    all_csv = tmp_path / "all.csv"
    assert main(["--export-history", str(all_csv)]) == 0
    rows = list(csv.DictReader(all_csv.open(encoding="utf-8-sig")))
    assert [(r["File"], r["Result"]) for r in rows] == [("pedro.pdf", "Review"), ("juan.pdf", "Success")]
    assert [r["File"] for r in csv.DictReader(run_csv.open(encoding="utf-8-sig"))] == ["juan.pdf"]


def test_forgetting_a_check_frees_its_transfer(tmp_path, history):
    process_file(receipt(tmp_path, "juan.pdf"), FakeClient(FOUND), history=history)
    flagged = process_file(receipt(tmp_path, "pedro.pdf", b"%PDF two"), FakeClient(FOUND), history=history)
    assert flagged.outcome is Outcome.REVIEW

    juan = next(c for c in history.checks() if c.file_name == "juan.pdf")
    assert juan.id > 0
    history.forget(juan)

    assert [c.file_name for c in history.checks()] == ["pedro.pdf"]
    again = process_file(receipt(tmp_path, "pedro.pdf", b"%PDF two"), FakeClient(FOUND), history=history)
    assert again.outcome is Outcome.SUCCESS
