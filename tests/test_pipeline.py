from pathlib import Path

import pytest

from cepxico import pipeline
from cepxico.banxico import CEPResult, CEPStatus
from cepxico.cli import main
from cepxico.models import PaymentData
from cepxico.pipeline import Outcome, process_file

COMPLETE = PaymentData(
    source_file="r.pdf",
    payment_date="05-11-2026",
    tracking_key="MBAN01002611050012345678",
    sender_bank="Banorte",
    receiver_bank="BBVA MEXICO",
    beneficiary_account="012180001234567893",
    amount="10.00",
)


class FakeClient:
    def __init__(self, result: CEPResult):
        self.result = result
        self.calls: list[dict] = []

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
    assert steps == ["Extracting", "Checking at Banxico"]
    assert client.calls[0]["sender_name"] == "Banorte"


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
