from pathlib import Path

import pytest

from cepxico import pipeline
from cepxico.banks import Bank, BankCatalog
from cepxico.banxico import BanxicoError, CEPResult, CEPStatus
from cepxico.cli import main
from cepxico.identify import BankSource
from cepxico.models import PaymentData
from cepxico.pipeline import Outcome, process_file
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
        (CEPResult(CEPStatus.NOT_FOUND, "No existe"), Outcome.NOT_FOUND, "No CEP at Banxico: No existe"),
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
    assert steps == ["Extracting", "Identifying banks", "Checking at Banxico"]
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


def test_cli_exit_code_and_summary(tmp_path, capsys):
    exit_code = main([str(tmp_path / "missing.pdf"), "--out", str(tmp_path)])
    assert exit_code == 1
    assert "missing.pdf: File not found" in capsys.readouterr().out
