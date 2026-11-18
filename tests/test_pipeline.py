import threading
import time
from pathlib import Path

import pytest

from cepxico import pipeline
from cepxico.banks import Bank, BankCatalog
from cepxico.banxico import BanxicoError, CEPResult, CEPStatus
from cepxico.cli import main
from cepxico.identify import BankSource
from cepxico.models import PaymentData
from cepxico.pipeline import Outcome, process_file, process_files
from tests.conftest import load_catalog, with_check_digit

COMPLETE = PaymentData(
    source_file="r.pdf",
    payment_date="05-11-2026",
    tracking_key="MBAN01002611050012345678",
    sender_bank="Banorte",
    receiver_bank=None,  # comes from the CLABE
    beneficiary_account=with_check_digit("01218000123456789"),
    amount="10.00",
)


class FakeClient:
    def __init__(self, result: CEPResult, catalog: BankCatalog | Exception | None = None):
        self.result = result
        self.catalog = catalog if catalog is not None else load_catalog("2026-11-10")
        self.calls: list[dict] = []

    def get_catalog(self, _fecha):
        if isinstance(self.catalog, Exception):
            raise self.catalog
        return self.catalog

    def download_cep(self, **query):
        self.calls.append(query)
        return self.result


@pytest.fixture
def receipt(tmp_path) -> Path:
    path = tmp_path / "r.pdf"
    path.write_bytes(b"%PDF placeholder")
    return path


@pytest.fixture
def extracted(monkeypatch):
    def use(payment: PaymentData):
        monkeypatch.setattr(pipeline, "extract_payment", lambda _path: payment)

    return use


@pytest.mark.parametrize(
    ("cep", "outcome", "message_start"),
    [
        (
            CEPResult(CEPStatus.FOUND, "ok", pdf_path=Path("CEP_x.pdf")),
            Outcome.SUCCESS,
            "CEP saved: CEP_x.pdf",
        ),
        (CEPResult(CEPStatus.NOT_FOUND, "No existe"), Outcome.NOT_FOUND, "Banxico: No existe"),
        (CEPResult(CEPStatus.CAPTCHA, "captcha"), Outcome.FAILED, "captcha"),
        (CEPResult(CEPStatus.ERROR, "timeout"), Outcome.FAILED, "timeout"),
    ],
)
def test_outcomes(receipt, extracted, cep, outcome, message_start):
    extracted(COMPLETE)
    client = FakeClient(cep)
    steps: list[str] = []

    result = process_file(receipt, client, on_step=steps.append)

    assert result.outcome is outcome
    assert result.message.startswith(message_start)
    assert steps == ["Reading", "Identifying banks", "Checking at Banxico"]
    assert client.calls[0]["sender"] == Bank("40072", "BANORTE")
    assert client.calls[0]["receiver"] == Bank("40012", "BBVA MEXICO")
    assert result.sender.source is BankSource.LABEL
    assert result.receiver.source is BankSource.CLABE


def test_unidentified_sender_skips_banxico(receipt, extracted):
    extracted(PaymentData(**{**COMPLETE.__dict__, "sender_bank": None, "text": "nothing"}))
    client = FakeClient(CEPResult(CEPStatus.FOUND, "unused"))

    result = process_file(receipt, client)

    assert result.outcome is Outcome.FAILED
    assert result.message == "Couldn't identify the sending bank"
    assert client.calls == []


def test_same_bank_on_both_sides_skips_banxico(receipt, extracted):
    # Receipt says the money left BBVA, and the CLABE is a BBVA account.
    extracted(PaymentData(**{**COMPLETE.__dict__, "sender_bank": "BBVA"}))
    client = FakeClient(CEPResult(CEPStatus.FOUND, "unused"))

    result = process_file(receipt, client)

    assert result.outcome is Outcome.FAILED
    assert result.message.startswith("Both banks read as BBVA MEXICO")
    assert result.sender.bank == result.receiver.bank == Bank("40012", "BBVA MEXICO")
    assert client.calls == []


def test_catalog_unavailable(receipt, extracted):
    extracted(COMPLETE)
    client = FakeClient(CEPResult(CEPStatus.FOUND, "unused"), catalog=BanxicoError("Banxico down"))

    result = process_file(receipt, client)

    assert result.outcome is Outcome.FAILED and result.message == "Banxico down"


def test_missing_data_skips_banxico(receipt, extracted):
    extracted(PaymentData(source_file="r.pdf", error_reason="Missing clave de rastreo"))
    client = FakeClient(CEPResult(CEPStatus.FOUND, "unused"))

    result = process_file(receipt, client)

    assert result.outcome is Outcome.FAILED
    assert result.message == "Missing clave de rastreo"
    assert client.calls == []


def test_missing_file(tmp_path):
    result = process_file(tmp_path / "nope.pdf", FakeClient(CEPResult(CEPStatus.FOUND, "unused")))
    assert result.outcome is Outcome.FAILED and result.message == "File not found"


def test_unexpected_error_becomes_failure(receipt, monkeypatch):
    def boom(_path):
        raise RuntimeError("kaput")

    monkeypatch.setattr(pipeline, "extract_payment", boom)
    result = process_file(receipt, FakeClient(CEPResult(CEPStatus.FOUND, "unused")))
    assert result.outcome is Outcome.FAILED and "kaput" in result.message


def no_extraction(monkeypatch):
    def fail(_path):
        raise AssertionError("the file shouldn't be read again")

    monkeypatch.setattr(pipeline, "extract_payment", fail)


def test_corrected_payment_is_used_without_reading_the_file(receipt, monkeypatch):
    no_extraction(monkeypatch)
    corrected = PaymentData(**{**COMPLETE.__dict__, "amount": "318940.25", "edited_fields": ("amount",)})
    client = FakeClient(CEPResult(CEPStatus.FOUND, "ok", pdf_path=receipt))

    result = process_file(receipt, client, payment=corrected)

    assert result.outcome is Outcome.SUCCESS
    assert result.payment is corrected
    assert client.calls[0]["amount"] == "318940.25"


def test_typed_sender_must_be_in_banxicos_list(receipt, monkeypatch):
    # The receipt names Banorte, but the user typed a bank that doesn't exist: report it
    # rather than fall back to the bank named on the receipt.
    no_extraction(monkeypatch)
    typed = PaymentData(
        **{
            **COMPLETE.__dict__,
            "sender_bank": "Banco Inexistente",
            "text": "Banorte",
            "edited_fields": ("sender_bank",),
        }
    )
    client = FakeClient(CEPResult(CEPStatus.FOUND, "unused"))

    result = process_file(receipt, client, payment=typed)

    assert result.outcome is Outcome.FAILED
    assert result.message == "Sending bank 'Banco Inexistente' not in Banxico's list"
    assert client.calls == []


def test_typed_sender_is_used(receipt, monkeypatch):
    no_extraction(monkeypatch)
    typed = PaymentData(**{**COMPLETE.__dict__, "sender_bank": "banorte", "edited_fields": ("sender_bank",)})
    client = FakeClient(CEPResult(CEPStatus.FOUND, "ok", pdf_path=receipt))

    result = process_file(receipt, client, payment=typed)

    assert result.outcome is Outcome.SUCCESS
    assert result.sender.bank.code3 == "072"
    assert result.sender.source is BankSource.LABEL


def test_cli_exit_code_and_summary(tmp_path, capsys):
    exit_code = main([str(tmp_path / "missing.pdf"), "--out", str(tmp_path)])
    assert exit_code == 1
    assert "missing.pdf: File not found" in capsys.readouterr().out


class TestProcessFiles:
    """Batches: order, one Banxico session per thread, cancelling."""

    def run(self, paths, extracted, jobs=4, **kwargs):
        extracted(COMPLETE)
        clients: list[FakeClient] = []
        users: dict[int, set[int]] = {}  # client id -> threads that used it
        lock = threading.Lock()

        class TrackingClient(FakeClient):
            def download_cep(self, **query):
                with lock:
                    users.setdefault(id(self), set()).add(threading.get_ident())
                time.sleep(0.02)  # let the workers overlap
                return super().download_cep(**query)

            def close(self):
                self.closed = True

        def factory(_catalogs):
            client = TrackingClient(CEPResult(CEPStatus.FOUND, "ok", pdf_path=Path("CEP.pdf")))
            with lock:
                clients.append(client)
            return client

        results = process_files(paths, "unused", jobs=jobs, client_factory=factory, **kwargs)
        return results, clients, users

    def test_results_in_input_order(self, tmp_path, extracted):
        paths = [tmp_path / f"r{i}.pdf" for i in range(10)]
        for p in paths:
            p.write_bytes(b"%PDF")
        results, _, _ = self.run(paths, extracted)
        assert [r.path for r in results] == paths
        assert all(r.outcome is Outcome.SUCCESS for r in results)

    def test_each_thread_has_its_own_session(self, tmp_path, extracted):
        paths = [tmp_path / f"r{i}.pdf" for i in range(12)]
        for p in paths:
            p.write_bytes(b"%PDF")
        _, clients, users = self.run(paths, extracted, jobs=4)
        assert 1 < len(clients) <= 4
        assert all(len(threads) == 1 for threads in users.values())
        assert all(c.closed for c in clients)

    def test_callbacks_get_paths_as_given(self, tmp_path, extracted):
        path = str(tmp_path / "r.pdf")
        Path(path).write_bytes(b"%PDF")
        steps, done = [], []
        self.run(
            [path], extracted, on_step=lambda p, s: steps.append((p, s)), on_done=lambda p, r: done.append(p)
        )
        assert done == [path]
        assert steps[0] == (path, "Reading")

    def test_cancel_skips_files_not_started(self, tmp_path, extracted):
        paths = [tmp_path / f"r{i}.pdf" for i in range(6)]
        for p in paths:
            p.write_bytes(b"%PDF")
        cancel = threading.Event()
        results, _, _ = self.run(paths, extracted, jobs=1, cancel=cancel, on_done=lambda p, r: cancel.set())
        assert results[0].outcome is Outcome.SUCCESS
        assert results[1:] == [None] * 5

    def test_empty_batch(self, extracted):
        results, clients, _ = self.run([], extracted)
        assert results == [] and clients == []

    def test_corrected_payments_by_path(self, tmp_path, extracted):
        typed, read = str(tmp_path / "typed.pdf"), str(tmp_path / "read.pdf")
        for p in (typed, read):
            Path(p).write_bytes(b"%PDF")
        corrected = PaymentData(**{**COMPLETE.__dict__, "amount": "99.00", "edited_fields": ("amount",)})

        results, _, _ = self.run([typed, read], extracted, payments={typed: corrected})

        assert results[0].payment is corrected
        assert results[1].payment is COMPLETE


@pytest.mark.parametrize("value", ["0", "9", "two"])
def test_cli_rejects_bad_jobs(value, capsys):
    with pytest.raises(SystemExit):
        main(["r.pdf", "--jobs", value])
    assert "--jobs" in capsys.readouterr().err


def test_cli_expands_wildcards_and_folders(tmp_path):
    from cepxico.cli import expand_paths

    for name in ("b.pdf", "a.PNG", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    a, b = tmp_path / "a.PNG", tmp_path / "b.pdf"

    assert expand_paths([tmp_path / "*.pdf"]) == [b]  # Windows shells don't expand it
    assert expand_paths([tmp_path]) == [a, b]  # receipts in the folder, not notes.txt
    assert expand_paths([b, tmp_path / "*.pdf"]) == [b]  # no repeats
    assert expand_paths([tmp_path / "*.jpg"]) == [tmp_path / "*.jpg"]  # reported as missing


def test_dollar_transfer_isnt_reported_as_fake(receipt, extracted):
    """Banxico's SPEI service doesn't know SPID transfers; asking it would say "not found"."""
    extracted(PaymentData(source_file="r.pdf", spid=True, amount="1500.00"))
    client = FakeClient(CEPResult(CEPStatus.NOT_FOUND, "No existe"))

    result = process_file(receipt, client)

    assert result.outcome is Outcome.FAILED
    assert "SPID" in result.message and pipeline.SPID_URL in result.message
    assert client.calls == []
