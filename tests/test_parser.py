"""Field parsing from receipt text. Texts are synthetic, modelled on real receipt wording."""

import pytest

from cepxico.extraction.parser import (
    find_amount,
    find_beneficiary_account,
    find_payment_date,
    find_receiver_bank,
    find_sender_bank,
    find_tracking_key,
    parse_payment,
)
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
