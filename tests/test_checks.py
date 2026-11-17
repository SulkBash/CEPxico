"""The checks beyond "does Banxico have a CEP": own accounts, CEP vs receipt, payments
without CEP, Banxico's hours and lookup limit, pago a banco, settings."""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from cepxico import pipeline
from cepxico.banks import Bank
from cepxico.banxico import CEPFiles, CEPResult, CEPStatus, parse_cep_xml
from cepxico.cli import main
from cepxico.extraction import correct_payment
from cepxico.identify import BankSource, identify_receiver, identify_sender
from cepxico.models import PaymentData
from cepxico.pipeline import (
    BLOCKED_MESSAGE,
    CLOSED_MESSAGE,
    MEXICO_CITY,
    Outcome,
    process_file,
    process_files,
)
from cepxico.pipeline import banxico_open as real_banxico_open  # before conftest patches it
from cepxico.settings import Settings, load_settings, parse_accounts, save_settings, settings_path
from tests.conftest import with_check_digit
from tests.test_banxico_responses import cep_xml
from tests.test_pipeline import COMPLETE, FakeClient

BANORTE_CLABE = with_check_digit("07218000123456789")
BBVA_CLABE = COMPLETE.beneficiary_account
FOUND = CEPResult(CEPStatus.FOUND, "ok", pdf_path=Path("CEP_x.pdf"))


@pytest.fixture
def receipt(tmp_path) -> Path:
    path = tmp_path / "r.pdf"
    path.write_bytes(b"%PDF placeholder")
    return path


def found_with(**xml) -> CEPResult:
    defaults = dict(clave=COMPLETE.tracking_key, amount=COMPLETE.amount, account=BBVA_CLABE)
    return replace(FOUND, record=parse_cep_xml(cep_xml(**{**defaults, **xml})))


# --- The CEP's own data against the receipt ----------------------------------------


def test_matching_cep_is_success(receipt):
    result = process_file(receipt, FakeClient(found_with()), payment=COMPLETE)
    assert result.outcome is Outcome.SUCCESS


@pytest.mark.parametrize(
    ("xml", "shown"),
    [
        ({"amount": "99.00"}, "monto 99.00"),
        ({"clave": "OTRA01002611050012345678"}, "clave de rastreo OTRA01002611050012345678"),
        ({"account": with_check_digit("01218000999999999")}, "cuenta beneficiaria …"),
    ],
)
def test_cep_for_another_transfer_needs_review(receipt, xml, shown):
    result = process_file(receipt, FakeClient(found_with(**xml)), payment=COMPLETE)
    assert result.outcome is Outcome.REVIEW
    assert result.message.startswith("CEP doesn't match the receipt") and shown in result.message


def test_card_payment_cep_showing_a_clabe_is_not_a_mismatch(receipt):
    card = replace(COMPLETE, beneficiary_account="4152313456789012", receiver_bank="BBVA MEXICO")
    result = process_file(receipt, FakeClient(found_with(account=BBVA_CLABE)), payment=card)
    assert result.outcome is Outcome.SUCCESS


def test_payment_without_cep_needs_review(receipt):
    cep = CEPResult(CEPStatus.NO_CEP, "Payment was returned ...", payment_status="Retornado")
    result = process_file(receipt, FakeClient(cep), payment=COMPLETE)
    assert result.outcome is Outcome.REVIEW and result.message == "Payment was returned ..."


# --- Own accounts --------------------------------------------------------------------

MINE = Settings(check_own_accounts=True, own_accounts=(BBVA_CLABE,))


def test_payment_to_another_account_is_flagged_without_asking_banxico(receipt):
    client = FakeClient(FOUND)
    elsewhere = replace(MINE, own_accounts=(BANORTE_CLABE,))
    result = process_file(receipt, client, payment=COMPLETE, settings=elsewhere)
    assert result.outcome is Outcome.REVIEW
    assert f"…{BBVA_CLABE[-4:]}" in result.message and "isn't one of your accounts" in result.message
    assert client.calls == []


def test_payment_to_own_account_is_checked(receipt):
    client = FakeClient(FOUND)
    assert process_file(receipt, client, payment=COMPLETE, settings=MINE).outcome is Outcome.SUCCESS
    assert len(client.calls) == 1


def test_own_account_check_is_off_by_default(receipt):
    off = Settings(own_accounts=(BANORTE_CLABE,))  # listed but not enabled
    assert off.accepted_accounts is None
    assert process_file(receipt, FakeClient(FOUND), payment=COMPLETE, settings=off).outcome is Outcome.SUCCESS


def test_files_setting_reaches_banxico_client(receipt):
    client = FakeClient(FOUND)
    process_file(receipt, client, payment=COMPLETE, settings=Settings(cep_files=CEPFiles.ZIP))
    assert client.calls[0]["cep_files"] is CEPFiles.ZIP


# --- Pago a banco --------------------------------------------------------------------

PAGO_A_BANCO = replace(
    COMPLETE, pago_a_banco=True, beneficiary_account=BANORTE_CLABE, receiver_bank="BBVA", sender_bank=None
)


def test_pago_a_banco_banks(directory):
    # The account is the sender's: its CLABE names the sending bank; the receiving bank
    # comes from the receipt.
    receiver = identify_receiver(PAGO_A_BANCO, directory)
    assert receiver.bank == Bank("40012", "BBVA MEXICO") and receiver.source is BankSource.LABEL
    sender = identify_sender(PAGO_A_BANCO, directory, receiver=receiver.bank)
    assert sender.bank == Bank("40072", "BANORTE") and sender.source is BankSource.CLABE


def test_pago_a_banco_needs_the_receiving_bank():
    p = replace(PAGO_A_BANCO, receiver_bank=None)
    assert p.missing_fields() == ["receiver_bank"]
    assert p.label("beneficiary_account") == "cuenta ordenante"


def test_pago_a_banco_lookup(receipt):
    client = FakeClient(found_with(pago_a_banco=True, account=BANORTE_CLABE))
    result = process_file(receipt, client, payment=PAGO_A_BANCO)
    assert result.outcome is Outcome.SUCCESS
    assert client.calls[0]["pago_a_banco"] is True and client.calls[0]["account"] == BANORTE_CLABE


def test_pago_a_banco_is_never_one_of_your_accounts(receipt):
    client = FakeClient(FOUND)
    result = process_file(receipt, client, payment=PAGO_A_BANCO, settings=MINE)
    assert result.outcome is Outcome.REVIEW and "pago a banco" in result.message
    assert client.calls == []


def test_pago_a_banco_can_be_typed_in():
    corrected, errors = correct_payment(COMPLETE, {"pago_a_banco": "1"})
    assert errors == {} and corrected.pago_a_banco and corrected.edited_fields == ("pago_a_banco",)
    back, _ = correct_payment(corrected, {"pago_a_banco": "0"})
    assert not back.pago_a_banco


# --- Banxico's hours and lookup limit --------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "minute", "open_"),
    [(9, 29, False), (9, 30, True), (15, 0, True), (22, 59, True), (23, 0, False), (3, 0, False)],
)
def test_banxico_hours(hour, minute, open_):
    assert real_banxico_open(datetime(2026, 11, 17, hour, minute, tzinfo=MEXICO_CITY)) is open_


def test_banxico_hours_use_mexico_city_time():
    from datetime import UTC

    # 04:00 UTC is 22:00 the previous day in Mexico City: open.
    assert real_banxico_open(datetime(2026, 11, 18, 4, 0, tzinfo=UTC))


def test_not_found_outside_banxico_hours_is_not_called_fake(receipt, monkeypatch):
    monkeypatch.setattr(pipeline, "banxico_open", lambda now=None: False)
    result = process_file(receipt, FakeClient(CEPResult(CEPStatus.NOT_FOUND, "x")), payment=COMPLETE)
    assert result.outcome is Outcome.FAILED and result.message == CLOSED_MESSAGE


def test_batch_stops_asking_once_banxico_refuses(tmp_path):
    paths = []
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        (tmp_path / name).write_bytes(b"%PDF")
        paths.append(tmp_path / name)

    class Client(FakeClient):
        def close(self):
            pass

    client = Client(CEPResult(CEPStatus.RATE_LIMITED, "limit"))

    results = process_files(
        paths, tmp_path, jobs=1, client_factory=lambda _c: client, payments=dict.fromkeys(paths, COMPLETE)
    )

    assert len(client.calls) == 1
    assert [r.message for r in results[1:]] == [BLOCKED_MESSAGE, BLOCKED_MESSAGE]


# --- Settings --------------------------------------------------------------------------


def test_settings_live_in_appdata(tmp_path):
    assert settings_path() == tmp_path / "appdata" / "CEPxico" / "settings.json"


def test_settings_round_trip(tmp_path):
    settings = Settings(
        cep_files=CEPFiles.ZIP, check_own_accounts=True, own_accounts=(BBVA_CLABE, "5512345678")
    )
    save_settings(settings)
    assert load_settings() == settings


def test_missing_or_damaged_settings_mean_defaults(tmp_path):
    assert load_settings() == Settings()
    path = settings_path()
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert load_settings() == Settings()
    path.write_text(
        json.dumps({"cep_files": "rar", "own_accounts": [BBVA_CLABE, "123"], "unknown": 1}), encoding="utf-8"
    )
    assert load_settings() == Settings(own_accounts=(BBVA_CLABE,))  # bad values dropped


def test_parse_accounts():
    accounts, problems = parse_accounts(
        f"{BBVA_CLABE[:4]} {BBVA_CLABE[4:]}\n55-1234-5678, {BBVA_CLABE}\n\n123"
    )
    assert accounts == (BBVA_CLABE, "5512345678")
    assert len(problems) == 1 and problems[0].startswith("123:")


def test_cli_uses_saved_settings_and_save_option(tmp_path, monkeypatch):
    save_settings(Settings(check_own_accounts=True, own_accounts=(BBVA_CLABE,)))
    seen = []
    monkeypatch.setattr(
        "cepxico.cli.process_files", lambda paths, out, *, jobs, settings: seen.append(settings) or []
    )
    receipt_path = tmp_path / "r.pdf"
    receipt_path.write_bytes(b"%PDF")

    main([str(receipt_path), "--save", "zip"])

    assert seen == [Settings(cep_files=CEPFiles.ZIP, check_own_accounts=True, own_accounts=(BBVA_CLABE,))]


def test_payment_data_default_is_ordinary_transfer():
    assert PaymentData("r.pdf").pago_a_banco is False
