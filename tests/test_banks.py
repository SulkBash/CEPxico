import pytest

from cepxico.banks import Bank, clabe_is_valid, normalize_name
from tests.conftest import with_check_digit


def test_normalize_name_strips_accents_and_punctuation():
    assert normalize_name("  Banco del Bajío, S.A.  ") == "BANCO DEL BAJIO S A"
    assert normalize_name(None) == ""


class TestClabe:
    def test_valid(self, bbva_clabe):
        assert clabe_is_valid(bbva_clabe)

    def test_wrong_check_digit(self, bbva_clabe):
        wrong = bbva_clabe[:-1] + str((int(bbva_clabe[-1]) + 1) % 10)
        assert not clabe_is_valid(wrong)

    @pytest.mark.parametrize("value", ["4152313412345678", "5512345678", "", None, "01218000123456789X"])
    def test_not_a_clabe(self, value):
        assert not clabe_is_valid(value)

    @pytest.mark.parametrize(
        ("prefix", "expected"),
        [
            ("012", Bank("40012", "BBVA MEXICO")),
            ("072", Bank("40072", "BANORTE")),
            ("646", Bank("90646", "STP")),
        ],
    )
    def test_bank_from_prefix(self, catalog, prefix, expected):
        assert catalog.by_clabe(with_check_digit(prefix + "18000123456789")) == expected

    def test_invalid_clabe_gives_no_bank(self, catalog, bbva_clabe):
        wrong = bbva_clabe[:-1] + str((int(bbva_clabe[-1]) + 1) % 10)
        assert catalog.by_clabe(wrong) is None


@pytest.mark.parametrize(
    ("receipt_text", "catalog_name"),
    [
        ("BBVA", "BBVA MEXICO"),
        ("BBVA Bancomer", "BBVA MEXICO"),
        ("Santander", "SANTANDER"),
        ("BANCO SANTANDER MEXICO S.A.", "SANTANDER"),
        ("Banorte", "BANORTE"),
        ("Banco Mercantil del Norte", "BANORTE"),
        ("Citibanamex", "BANAMEX"),
        ("Banco del Bajío", "BAJIO"),
        ("INTERCAM", "INTERCAM BANCO"),
        ("Nu México", "NUBANK"),
        ("Mercado Pago", "Mercado Pago W"),
        ("STP", "STP"),
        ("Afirme", "AFIRME"),
        ("BANCO AZTECA", "AZTECA"),
        ("Hey Banco", "HEY BANCO"),
        ("Scotiabank Inverlat", "SCOTIABANK"),
        ("KUSPIT Disponibilidad de pago: Mismo día", "KUSPIT"),
    ],
)
def test_resolve_known_names(catalog, receipt_text, catalog_name):
    bank = catalog.resolve(receipt_text)
    assert bank is not None and bank.name == catalog_name


@pytest.mark.parametrize("receipt_text", ["Envio", "", None, "Banco Inexistente"])
def test_resolve_unknown_names(catalog, receipt_text):
    # "Envio" used to match the bank NVIO as a substring.
    assert catalog.resolve(receipt_text) is None
