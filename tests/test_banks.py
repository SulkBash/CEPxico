import pytest

from cepxico.banks import (
    Bank,
    BankDirectory,
    BankInfo,
    clabe_is_valid,
    load_bank_info,
    normalize_name,
    parse_bank_info,
)
from tests.conftest import load_catalog, with_check_digit


def test_normalize_name_strips_accents_and_punctuation():
    assert normalize_name("  Banco del Bajío, S.A.  ") == "BANCO DEL BAJIO S A"
    assert normalize_name(None) == ""


def test_code3_is_the_clabe_prefix():
    assert Bank("40012", "BBVA MEXICO").code3 == "012"
    assert Bank("2001", "BANXICO").code3 == "001"


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
            ("638", Bank("40638", "NUBANK")),
        ],
    )
    def test_bank_from_prefix(self, catalog, prefix, expected):
        assert catalog.by_clabe(with_check_digit(prefix + "18000123456789")) == expected

    def test_invalid_clabe_gives_no_bank(self, catalog, bbva_clabe):
        wrong = bbva_clabe[:-1] + str((int(bbva_clabe[-1]) + 1) % 10)
        assert catalog.by_clabe(wrong) is None


class TestResolve:
    """Short labelled fields, e.g. the value of "Banco destino:"."""

    @pytest.mark.parametrize(
        ("field", "catalog_name"),
        [
            # catalog short names
            ("BBVA MEXICO", "BBVA MEXICO"),
            ("Santander", "SANTANDER"),
            ("STP", "STP"),
            ("INTERCAM", "INTERCAM BANCO"),  # unique prefix of a catalog name
            # aliases from banks.toml
            ("BBVA", "BBVA MEXICO"),
            ("BBVA Bancomer", "BBVA MEXICO"),
            ("Citibanamex", "BANAMEX"),
            ("Nu México", "NUBANK"),
            ("Mercado Pago", "Mercado Pago W"),
            ("PayPal", "PPBALANCEMX"),
            ("Revolut", "REVOLUT BANK"),
            # legal names from Banxico's participant list
            ("Banco Mercantil del Norte, S.A., Institución de Banca Múltiple", "BANORTE"),
            ("BANCO SANTANDER (MEXICO) S.A.", "SANTANDER"),
            ("Banco del Bajío", "BAJIO"),
            ("Scotiabank Inverlat", "SCOTIABANK"),
            ("Cartera Digital Wal-Mart", "CASHI CUENTA"),
            ("Inteligencia en Finanzas SAPI de CV", "albo"),
            ("Compropago", "SPIN BY OXXO"),
            ("Banco del Bienestar", "BaBien"),
            # ambiguous names are fine in a labelled field
            ("DONDE", "DONDE"),
        ],
    )
    def test_known(self, directory, field, catalog_name):
        bank = directory.resolve(field)
        assert bank is not None and bank.name == catalog_name

    @pytest.mark.parametrize("field", ["Envio", "", None, "Banco Inexistente"])
    def test_unknown(self, directory, field):
        assert directory.resolve(field) is None  # "Envio" used to match NVIO as a substring

    def test_names_follow_the_payment_date(self):
        """Same 3-digit code, different catalog name and full code over time."""
        old, new = BankDirectory(load_catalog("2024-07-01")), BankDirectory(load_catalog("2026-11-10"))
        assert old.resolve("Nu México") == Bank("90638", "NU MEXICO")
        assert new.resolve("Nu México") == Bank("40638", "NUBANK")
        bancomer = BankDirectory(load_catalog("2019-07-01")).resolve("BBVA")
        assert bancomer == Bank("40012", "BBVA BANCOMER")


class TestBanksInText:
    """Scanning a whole receipt for bank names."""

    def test_order_of_appearance(self, directory):
        text = "BANORTE\nTransferencia a Banco Destino: BBVA MEXICO"
        assert [b.name for b in directory.banks_in_text(text)] == ["BANORTE", "BBVA MEXICO"]

    def test_shorter_name_inside_longer_one_is_ignored(self, directory):
        # "BBVA" (alias) is part of "BBVA MEXICO"; only one bank must be reported.
        assert [b.name for b in directory.banks_in_text("BBVA MEXICO")] == ["BBVA MEXICO"]

    def test_ambiguous_names_are_skipped(self, directory):
        text = (
            "Consulta tu CEP en www.banxico.org.mx. Banco de México no es responsable.\n"
            "Concepto: renta del local donde está la libertad\n"
            "Comprobante emitido por Banco Azteca"
        )
        assert [b.name for b in directory.banks_in_text(text)] == ["AZTECA"]


class TestReferenceData:
    def test_bundled_file_loads(self):
        assert len(load_bank_info()) > 90

    def test_every_code_exists_in_banxicos_catalog(self, catalog):
        unknown = set(load_bank_info()) - {b.code3 for b in catalog}
        assert not unknown, f"codes in banks.toml not in Banxico's current catalog: {sorted(unknown)}"

    def test_every_current_bank_has_a_legal_name(self, catalog):
        info = load_bank_info()
        without = {b.name for b in catalog if not info.get(b.code3, BankInfo(b.code3)).legal_name}
        assert without == {"CLS", "CoDi Valida"}  # not SPEI participants: no razón social published

    def test_no_name_points_to_two_banks(self, catalog):
        info = load_bank_info()
        owners: dict[str, set[str]] = {}
        for bank in catalog:
            for name in (bank.name, *info.get(bank.code3, BankInfo(bank.code3)).extra_names):
                owners.setdefault(normalize_name(name), set()).add(bank.code3)
        clashes = {name: codes for name, codes in owners.items() if len(codes) > 1}
        assert not clashes

    def test_ambiguous_names_are_names_of_that_bank(self, catalog):
        info = load_bank_info()
        for bank in catalog:
            entry = info.get(bank.code3)
            if entry:
                known = {normalize_name(n) for n in (bank.name, *entry.extra_names)}
                assert {normalize_name(n) for n in entry.ambiguous_names} <= known, bank

    def test_legal_core(self):
        assert BankInfo("072", legal_name="Banco Mercantil del Norte, S.A., IBM").legal_core == (
            "Banco Mercantil del Norte"
        )
        assert BankInfo("729", legal_name="Depósitos y Pagos Digitales S.A.P.I. de C.V.").legal_core == (
            "Depósitos y Pagos Digitales"
        )

    @pytest.mark.parametrize(
        "document",
        [
            {"12": {}},  # not 3 digits
            {"012": {"nickname": "x"}},  # unknown field
            {"012": {"aliases": "BBVA"}},  # not a list
            {"012": {"aliases": [""]}},  # empty string
        ],
    )
    def test_invalid_reference_data_is_rejected(self, document):
        with pytest.raises(ValueError):
            parse_bank_info(document)
