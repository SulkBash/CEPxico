"""Field parsing from receipt text. Texts are synthetic, modelled on real receipt wording."""

import pytest

from cepxico.extraction.parser import (
    clean_field,
    correct_payment,
    find_amount,
    find_beneficiary_account,
    find_payment_date,
    find_receiver_bank,
    find_sender_bank,
    find_tracking_key,
    parse_payment,
)
from cepxico.models import PaymentData
from tests.conftest import with_check_digit

SANTANDER_RECEIPT = """\
Comprobante de Operación
Fecha de aplicación: 05/11/2026
Clave de Rastreo: 2026110540014TRAN00001234567
Banco receptor: BBVA MEXICO
Cuenta CLABE Beneficiario: 012180001234567893
Importe: $1,234.50 MXN
"""

BANORTE_RECEIPT = """\
BANCO MERCANTIL DEL NORTE, S.A.
Fecha Aplicación: 5/11/2026
Clave de Rastreo: 8846APR1202611050012345678
Banco Destino: STP
Cuenta de abono: 646180123456789012
Importe a Transferir: $500.00
"""

BBVA_RECEIPT = """\
BBVA
Fecha y Hora Operación: 2026-11-05 10:22:01
Referencia BNET01002611050012345678
Descripción: pago proveedor Importe: $2,000.00
Saldo disponible 9,999.99
"""


class TestFullReceipts:
    def test_santander(self):
        p = parse_payment(SANTANDER_RECEIPT, "santander.pdf")
        assert p.sender_bank is None  # no sender label; identified later (test_identify.py)
        assert p.payment_date == "05-11-2026"
        assert p.tracking_key == "2026110540014TRAN00001234567"
        assert p.receiver_bank == "BBVA MEXICO"
        assert p.beneficiary_account == "012180001234567893"
        assert p.amount == "1234.50"
        assert p.error_reason == ""
        assert p.text == SANTANDER_RECEIPT

    def test_banorte(self):
        p = parse_payment(BANORTE_RECEIPT)
        assert p.sender_bank is None
        assert p.payment_date == "05-11-2026"
        assert p.tracking_key == "8846APR1202611050012345678"
        assert p.receiver_bank == "STP"
        assert p.beneficiary_account == "646180123456789012"
        assert p.amount == "500.00"

    def test_bbva_uses_description_amount_not_balance(self):
        p = parse_payment(BBVA_RECEIPT)
        assert p.sender_bank is None
        assert p.payment_date == "05-11-2026"
        assert p.tracking_key == "BNET01002611050012345678"
        assert p.amount == "2000.00"

    def test_empty_text_reports_missing_tracking_key_first(self):
        p = parse_payment("nothing useful here")
        assert p.error_reason == "Missing clave de rastreo"


def test_tracking_key_drops_glued_label():
    text = "Clave de Rastreo: MBAN01002611050012345678FECHAYHORADECAPTURA 05/11/2026"
    assert find_tracking_key(text) == "MBAN01002611050012345678"


def test_tracking_key_too_short_is_rejected():
    assert find_tracking_key("Clave de rastreo: ABC123") is None


AFIRME_SPLIT_KEY = "Clave de rastreo:\nAFIR0100261105\n0012345678\nFolio Interbancario 123"


def test_afirme_key_split_across_lines():
    assert find_tracking_key("Banca Afirme\n" + AFIRME_SPLIT_KEY) == "AFIR01002611050012345678"


def test_split_key_is_only_joined_on_afirme_receipts():
    assert find_tracking_key(AFIRME_SPLIT_KEY) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Fecha Aplicación: 05/11/2026", "05-11-2026"),
        ("Fecha: 5/11/26", "05-11-2026"),
        ("Fecha y Hora Operación: 2026-11-05", "05-11-2026"),
        ("sin fecha", None),
    ],
)
def test_payment_date(text, expected):
    assert find_payment_date(text) == expected


@pytest.mark.parametrize(
    "text",
    ["BANCO DESTINO: BANORTE", "Banco Receptor: BANORTE", "banco beneficiario: BANORTE"],
)
def test_receiver_bank_label_any_case(text):
    assert find_receiver_bank(text) == "BANORTE"


def test_receiver_bank_participante_is_last_resort():
    text = "Banco participante: SANTANDER\nBanco destino: BANORTE"
    assert find_receiver_bank(text) == "BANORTE"
    assert find_receiver_bank("Banco participante: SANTANDER") == "SANTANDER"


def test_receiver_bank_strips_quotes():
    assert find_receiver_bank('Banco destino: "BANORTE"') == "BANORTE"


def test_receiver_bank_quoted_value():
    assert find_receiver_bank('Banco receptor: "BANORTE"') == "BANORTE"
    assert find_receiver_bank('Banco receptor: BANORTE", "Cuenta": "123"') == "BANORTE"


def test_receiver_bank_ignores_empty_capture():
    assert find_receiver_bank('Banco receptor: ""') is None


def test_account_prefers_clabe_over_short_number():
    clabe = with_check_digit("07218000123456789")
    assert find_beneficiary_account(f"Cuenta/CLABE/Celular: {clabe}") == clabe
    assert find_beneficiary_account("Cuenta/CLABE/Celular: 5512345678") == "5512345678"
    assert find_beneficiary_account("Cuenta de abono: 12345") is None


def test_amount_prefers_labelled_mxn():
    assert find_amount("Comisión $5.00\nImporte: $1,500.00 MXN") == "1500.00"


def test_missing_receiver_is_fine_with_valid_clabe():
    clabe = with_check_digit("01218000123456789")
    text = (
        "Comprobante de Operación\n"
        "Fecha de aplicación: 05/11/2026\n"
        "Clave de Rastreo: MBAN01002611050012345678\n"
        f"Cuenta Beneficiaria: {clabe}\n"
        "Importe: $10.00 MXN\n"
    )
    p = parse_payment(text)
    assert p.receiver_bank is None
    assert p.missing_fields() == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Banco emisor: BANORTE", "BANORTE"),
        ("Institución ordenante: BBVA MEXICO", "BBVA MEXICO"),
        ("BANCO DE ORIGEN: Santander", "Santander"),
        ("Banco que envía: Nu México", "Nu México"),
        ("Banco destino: BBVA MEXICO", None),
    ],
)
def test_sender_bank_label(text, expected):
    assert find_sender_bank(text) == expected


# --- Wording and layouts that used to be misread --------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # OCR spaces the currency sign; the balance must not be taken instead.
        ("Monto: $ 1,234.50\nComisión: $ 0.00\nSaldo: 9,999.99", "1234.50"),
        ("Monto transferido\n$ 1,234.50\nSaldo disponible 8,765.43", "1234.50"),
        ("Monto: $1,500 MXN\nFolio 123", "1500.00"),  # whole pesos after a label
        ("Importe: -$ 1,234.50 MXN", "1234.50"),
        ("Importe: 1,234.50, gracias", "1234.50"),
        # BBVA Net Cash scan: the IVA comes later and was taken as the last amount.
        (
            "BBVA Net Cash - Pagos Interbancarios\n"
            "Descripción: ASESORIA Importe de la operación: 1,160.00 MXP\n"
            "RFC del tercero: XAXX010101000 IVA del pago: 160.00\n",
            "1160.00",
        ),
    ],
)
def test_amount_layouts(text, expected):
    assert find_amount(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # A labelled date beats an earlier print date, whatever the label's case.
        ("Impreso 01/12/2026\nFECHA DE APLICACIÓN: 05/11/2026", "05-11-2026"),
        ("Fecha de aplicacion: 05/11/2026", "05-11-2026"),  # OCR dropped the accent
        ("Fecha de operación: jueves, 5 de noviembre de 2026", "05-11-2026"),
        ("Fecha: 05/Nov/2026", "05-11-2026"),
        ("05 nov. 2026 14:03 h", "05-11-2026"),
        ("Fecha de operación: 05-11-2026", "05-11-2026"),
        ("2026-11-05 10:00", "05-11-2026"),  # not read as 26-11-05
        ("Ref 31/31/2026 Fecha 01/02/2026", "01-02-2026"),  # impossible date skipped
    ],
)
def test_payment_date_layouts(text, expected):
    assert find_payment_date(text) == expected


CLABE = with_check_digit("01218000123456789")
GROUPED_CLABE = f"{CLABE[:4]} {CLABE[4:8]} {CLABE[8:12]} {CLABE[12:16]} {CLABE[16:]}"


@pytest.mark.parametrize(
    "text",
    [
        f"Cuenta CLABE Beneficiario: {GROUPED_CLABE}",
        f"Cuenta destino: {CLABE}",
        f"Cuenta de deposito: {CLABE}",  # OCR dropped the accent
        f"CUENTA DE ABONO {CLABE} Monto $10.00",
        f"Para: Juan Pérez\n{GROUPED_CLABE}\nFolio 1234567890",  # unlabelled, only valid CLABE
    ],
)
def test_account_layouts(text):
    assert find_beneficiary_account(text) == CLABE


def test_unlabelled_clabe_must_be_the_only_one():
    other = with_check_digit("07218000123456789")
    assert find_beneficiary_account(f"Origen {other}\nDestino {CLABE}") is None


def test_grouped_card_is_not_merged_with_next_number():
    text = "Cuenta de abono: 4152 3134 5678 9012 1,500.00"
    assert find_beneficiary_account(text) == "4152313456789012"


def test_tracking_key_longer_than_banxico_allows_is_rejected():
    assert find_tracking_key("Clave de rastreo: MBAN01002611050000123456ABCDEFGHI") is None


# --- Fields typed in by the user -----------------------------------------------

VALID_CLABE = with_check_digit("01218000123456789")


@pytest.mark.parametrize(
    ("name", "raw", "expected"),
    [
        ("payment_date", "5/11/2026", "05-11-2026"),
        ("payment_date", "05-11-26", "05-11-2026"),
        ("payment_date", "5 de noviembre de 2026", "05-11-2026"),
        ("payment_date", "   ", None),  # empty = unknown
        ("tracking_key", " 058-29/10/2026/29-245akjnw23 ", "0582910202629245AKJNW23"),
        ("beneficiary_account", "0121 8000 1234 5678 9" + VALID_CLABE[-1], VALID_CLABE),
        ("beneficiary_account", "4152-3134-5678-9012", "4152313456789012"),
        ("beneficiary_account", "55 1234 5678", "5512345678"),
        ("amount", "$1,500", "1500.00"),
        ("amount", "318,940.25 MXP", "318940.25"),
        ("sender_bank", "  banorte   ixe ", "banorte ixe"),
    ],
)
def test_clean_field(name, raw, expected):
    assert clean_field(name, raw) == expected


@pytest.mark.parametrize(
    ("name", "raw", "problem"),
    [
        ("payment_date", "31/02/2026", "isn't a date"),
        ("payment_date", "ayer", "isn't a date"),
        ("tracking_key", "A" * 31, "1 to 30"),
        ("beneficiary_account", "***************756", "digits only"),
        ("beneficiary_account", "12345", "has 5 digits"),
        ("beneficiary_account", VALID_CLABE[:-1] + str((int(VALID_CLABE[-1]) + 1) % 10), "typo"),
        ("amount", "0.00", "valid amount"),
        ("amount", "-$50.00", "valid amount"),
        ("amount", "mil pesos", "valid amount"),
    ],
)
def test_clean_field_rejects(name, raw, problem):
    with pytest.raises(ValueError, match=problem):
        clean_field(name, raw)


def test_correct_payment_marks_changed_fields():
    read = PaymentData("r.pdf", payment_date="12-11-2026", amount="48750.00", error_reason="Missing cuenta")

    corrected, errors = correct_payment(
        read, {"beneficiary_account": VALID_CLABE, "amount": "48,750.00", "receiver_bank": "KUSPIT"}
    )

    assert errors == {}
    assert corrected.beneficiary_account == VALID_CLABE
    assert corrected.edited_fields == ("receiver_bank", "beneficiary_account")  # amount didn't change
    assert corrected.error_reason == ""
    assert corrected.payment_date == "12-11-2026"
    # A later correction keeps the earlier ones marked.
    again, _ = correct_payment(corrected, {"payment_date": "13/11/2026"})
    assert again.edited_fields == ("payment_date", "receiver_bank", "beneficiary_account")


def test_correct_payment_reports_every_problem_and_changes_nothing():
    read = PaymentData("r.pdf")

    corrected, errors = correct_payment(
        read, {"beneficiary_account": "123", "amount": "x", "tracking_key": "OK1"}
    )

    assert corrected is read
    assert set(errors) == {"beneficiary_account", "amount"}


# --- SPID (dollar transfers) ---------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Transferencia SPID\nImporte: 1,500.00",
        "Importe: 1,500.00 USD",
        "Monto: US$ 1,500.00",
        "Importe en Dólares: 1,500.00",
        "Importe: 1,500.00 DLS",
        "Comprobante Electrónico de Pagos SPEI / SPID\nImporte: 1,500.00 USD",  # banner + currency
    ],
)
def test_dollar_transfers_are_recognised(text):
    assert parse_payment(text).spid is True


@pytest.mark.parametrize(
    "text",
    [
        "Transferencia SPEI\nImporte: $1,500.00 MXN",
        "Clave de rastreo: MBAN01002611SPIDER0001",  # inside a word, not the system's name
        # One banner some banks print on every receipt, peso or dollar.
        "Comprobante Electrónico de Pagos SPEI / SPID\nImporte: $12,980.00",
        "Concepto: pago de lusd",
    ],
)
def test_peso_transfers_are_not_taken_for_dollars(text):
    assert parse_payment(text).spid is False


def test_spid_flag_can_be_corrected():
    from cepxico.extraction import correct_payment

    corrected, errors = correct_payment(PaymentData("r.pdf", spid=True), {"spid": "0"})
    assert errors == {} and corrected.spid is False and corrected.edited_fields == ("spid",)
