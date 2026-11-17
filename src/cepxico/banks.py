"""Bank identification: CLABE validation and matching receipt names to Banxico's catalog."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import NamedTuple


class Bank(NamedTuple):
    """A SPEI participant as listed by Banxico (e.g. Bank("40012", "BBVA MEXICO"))."""

    code: str
    name: str


# Names that appear on receipts -> name in Banxico's catalog.
# Keys are matched as whole words after normalize_name().
BANK_ALIASES: dict[str, str] = {
    "BBVA": "BBVA MEXICO",
    "BANCOMER": "BBVA MEXICO",
    "BANCO MERCANTIL DEL NORTE": "BANORTE",
    "IXE": "BANORTE",
    "CITIBANAMEX": "BANAMEX",
    "BANCO NACIONAL DE MEXICO": "BANAMEX",
    "NU MEXICO": "NUBANK",
    "NU BANK": "NUBANK",
    "MERCADO PAGO": "Mercado Pago W",
    "BANCO DEL BAJIO": "BAJIO",
    "BANCO AZTECA": "AZTECA",
    "BANCO COPPEL": "BANCOPPEL",
    "SCOTIABANK INVERLAT": "SCOTIABANK",
    "BANCO INBURSA": "INBURSA",
    "BANCO REGIONAL": "BANREGIO",
    "HEY BANCO": "HEY BANCO",
    "SISTEMA DE TRANSFERENCIAS Y PAGOS": "STP",
    "INTERCAM": "INTERCAM BANCO",
    "MULTIVA": "MULTIVA BANCO",
    "SPIN": "SPIN BY OXXO",
    "CITI": "CITI MEXICO",
    "CITIBANK": "CITI MEXICO",
}

_CLABE_WEIGHTS = (3, 7, 1)


def normalize_name(text: str | None) -> str:
    """Uppercase, strip accents and punctuation, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^A-Za-z0-9]+", " ", without_accents).upper().split())


def clabe_is_valid(clabe: str | None) -> bool:
    """True if `clabe` is 18 digits with a correct control digit."""
    if not clabe or not re.fullmatch(r"\d{18}", clabe):
        return False
    total = sum((int(d) * _CLABE_WEIGHTS[i % 3]) % 10 for i, d in enumerate(clabe[:17]))
    return (10 - total % 10) % 10 == int(clabe[17])


def _contains_words(haystack: str, needle: str) -> bool:
    return re.search(rf"(?<![A-Z0-9]){re.escape(needle)}(?![A-Z0-9])", haystack) is not None


class BankCatalog:
    """Banxico's list of SPEI participants for a given date."""

    def __init__(self, banks: Iterable[Bank]):
        self.banks: list[Bank] = list(banks)
        self._by_norm: dict[str, Bank] = {normalize_name(b.name): b for b in self.banks}

    @classmethod
    def from_rows(cls, rows: Iterable[Iterable[str]]) -> BankCatalog:
        """Builds a catalog from instituciones.do rows: [[code, name], ...]."""
        return cls(Bank(str(code), str(name)) for code, name in rows)

    def __len__(self) -> int:
        return len(self.banks)

    def by_name(self, catalog_name: str) -> Bank | None:
        return self._by_norm.get(normalize_name(catalog_name))

    def by_clabe(self, clabe: str) -> Bank | None:
        """The first 3 CLABE digits identify the bank; Banxico codes end in those digits."""
        if not clabe_is_valid(clabe):
            return None
        matches = [b for b in self.banks if b.code[-3:] == clabe[:3]]
        return matches[0] if len(matches) == 1 else None

    def resolve(self, extracted_name: str | None) -> Bank | None:
        """Maps a bank name taken from a receipt to a catalog entry, or None."""
        text = normalize_name(extracted_name)
        if not text:
            return None
        if text in self._by_norm:
            return self._by_norm[text]

        for alias in sorted(BANK_ALIASES, key=len, reverse=True):
            if _contains_words(text, normalize_name(alias)):
                bank = self.by_name(BANK_ALIASES[alias])
                if bank:
                    return bank

        # A catalog name appearing as whole words inside the text; the longest wins.
        hits = [(norm, bank) for norm, bank in self._by_norm.items() if _contains_words(text, norm)]
        if hits:
            return max(hits, key=lambda hit: len(hit[0]))[1]

        # The text is the start of exactly one catalog name (e.g. "INTERCAM").
        prefix_hits = [bank for norm, bank in self._by_norm.items() if norm.startswith(text + " ")]
        if len(prefix_hits) == 1:
            return prefix_hits[0]
        return None
