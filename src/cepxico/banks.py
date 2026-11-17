"""
Banks: Banxico's catalog, our reference data (data/banks.toml), and name matching.

Banks are identified by their 3-digit CLABE bank code (`code3`), which stays the same
through renames and re-licensing. Names always come from Banxico's catalog for the
payment date, plus the extra names in banks.toml.
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import NamedTuple

_CLABE_WEIGHTS = (3, 7, 1)


class Bank(NamedTuple):
    """A SPEI participant as listed by Banxico, e.g. Bank("40012", "BBVA MEXICO")."""

    code: str
    name: str

    @property
    def code3(self) -> str:
        """3-digit CLABE bank code (last 3 digits of Banxico's code)."""
        return self.code[-3:].zfill(3)


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


def _word_spans(haystack: str, needle: str) -> Iterable[tuple[int, int]]:
    """(start, end) of each whole-word occurrence of `needle` in `haystack` (both normalized)."""
    for m in re.finditer(rf"(?<![A-Z0-9]){re.escape(needle)}(?![A-Z0-9])", haystack):
        yield m.start(), m.end()


# ------------------------------------------------------------------------------
# Banxico's catalog (one per date)
# ------------------------------------------------------------------------------


class BankCatalog:
    """Banxico's list of SPEI participants valid on a given date."""

    def __init__(self, banks: Iterable[Bank]):
        self.banks: list[Bank] = list(banks)
        self._by_code3: dict[str, Bank] = {b.code3: b for b in self.banks}

    @classmethod
    def from_rows(cls, rows: Iterable[Iterable[str]]) -> BankCatalog:
        """From instituciones.do rows: [[code, name], ...]."""
        return cls(Bank(str(code), str(name)) for code, name in rows)

    def __len__(self) -> int:
        return len(self.banks)

    def __iter__(self):
        return iter(self.banks)

    def by_code3(self, code3: str) -> Bank | None:
        return self._by_code3.get(code3)

    def by_clabe(self, clabe: str | None) -> Bank | None:
        """The bank a valid CLABE belongs to (its first 3 digits)."""
        return self.by_code3(clabe[:3]) if clabe and clabe_is_valid(clabe) else None


# ------------------------------------------------------------------------------
# Reference data (data/banks.toml)
# ------------------------------------------------------------------------------


@dataclass(frozen=True)
class BankInfo:
    """What we know about a bank beyond Banxico's catalog. See data/banks.toml."""

    code3: str
    legal_name: str = ""
    aliases: tuple[str, ...] = ()
    ambiguous_names: tuple[str, ...] = ()
    tracking_key_prefixes: tuple[str, ...] = ()
    receipt_signatures: tuple[str, ...] = ()

    @property
    def legal_core(self) -> str:
        """Legal name without the corporate suffix: "Banco Mercantil del Norte, S.A., ..." ->
        "Banco Mercantil del Norte"."""
        return re.split(r",|\s+S\.A\.", self.legal_name, maxsplit=1)[0].strip()

    @property
    def extra_names(self) -> tuple[str, ...]:
        return tuple(n for n in (self.legal_core, *self.aliases) if n)


_LIST_FIELDS = ("aliases", "ambiguous_names", "tracking_key_prefixes", "receipt_signatures")


def parse_bank_info(data: Mapping[str, Mapping[str, object]]) -> dict[str, BankInfo]:
    """Validates and converts the parsed TOML document."""
    banks: dict[str, BankInfo] = {}
    for code3, entry in data.items():
        if not re.fullmatch(r"\d{3}", code3):
            raise ValueError(f"banks.toml: key {code3!r} is not a 3-digit bank code")
        unknown = set(entry) - {"legal_name", *_LIST_FIELDS}
        if unknown:
            raise ValueError(f"banks.toml [{code3}]: unknown field(s) {sorted(unknown)}")
        lists = {}
        for name in _LIST_FIELDS:
            value = entry.get(name, [])
            if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
                raise ValueError(f"banks.toml [{code3}].{name} must be a list of non-empty strings")
            lists[name] = tuple(value)
        legal_name = entry.get("legal_name", "")
        if not isinstance(legal_name, str):
            raise ValueError(f"banks.toml [{code3}].legal_name must be a string")
        banks[code3] = BankInfo(code3=code3, legal_name=legal_name, **lists)
    return banks


@lru_cache(maxsize=1)
def load_bank_info() -> dict[str, BankInfo]:
    """Reference data bundled with the package."""
    text = resources.files("cepxico").joinpath("data/banks.toml").read_text(encoding="utf-8")
    return parse_bank_info(tomllib.loads(text))


# ------------------------------------------------------------------------------
# Name matching: catalog + reference data
# ------------------------------------------------------------------------------


class _Name(NamedTuple):
    normalized: str
    bank: Bank
    scannable: bool  # usable when scanning a whole receipt (not an ordinary word)


class BankDirectory:
    """Every way to name each bank in a date's catalog, for matching receipt text."""

    def __init__(self, catalog: BankCatalog, info: Mapping[str, BankInfo] | None = None):
        self.catalog = catalog
        self.info = load_bank_info() if info is None else info
        names: dict[str, _Name] = {}
        for bank in catalog:
            bank_info = self.info.get(bank.code3, BankInfo(bank.code3))
            ambiguous = {normalize_name(n) for n in bank_info.ambiguous_names}
            for raw in (bank.name, *bank_info.extra_names):
                norm = normalize_name(raw)
                if norm and norm not in names:  # first bank to claim a name keeps it
                    names[norm] = _Name(norm, bank, norm not in ambiguous)
        # Longest first, so "BANCO MERCANTIL DEL NORTE" is tried before "NORTE"-like names.
        self._names = sorted(names.values(), key=lambda n: len(n.normalized), reverse=True)
        self._by_norm = names

    def resolve(self, text: str | None) -> Bank | None:
        """The bank named in a short field like "Banco destino: BBVA MEXICO", or None."""
        norm = normalize_name(text)
        if not norm:
            return None
        if norm in self._by_norm:
            return self._by_norm[norm].bank
        for name in self._names:  # longest name contained in the field wins
            if next(_word_spans(norm, name.normalized), None):
                return name.bank
        # The field is the start of exactly one name (e.g. "INTERCAM" -> "INTERCAM BANCO").
        prefixed = {n.bank for n in self._names if n.normalized.startswith(norm + " ")}
        return prefixed.pop() if len(prefixed) == 1 else None

    def banks_in_text(self, text: str) -> list[Bank]:
        """Banks named anywhere in a whole receipt, in order of first appearance.
        Ignores ambiguous names, and names inside a longer name ("BBVA" in "BBVA MEXICO")."""
        norm = normalize_name(text)
        taken: list[tuple[int, int]] = []
        first_seen: dict[Bank, int] = {}
        for name in self._names:
            for start, end in _word_spans(norm, name.normalized):
                if any(s <= start and end <= e for s, e in taken):
                    continue  # part of a longer name already matched
                taken.append((start, end))  # ambiguous names still shadow shorter ones inside them
                if name.scannable:
                    first_seen[name.bank] = min(start, first_seen.get(name.bank, start))
        return sorted(first_seen, key=first_seen.__getitem__)

    def by_tracking_key(self, tracking_key: str | None) -> Bank | None:
        key = (tracking_key or "").upper()
        for bank in self.catalog:
            prefixes = self.info.get(bank.code3, BankInfo(bank.code3)).tracking_key_prefixes
            if key and any(key.startswith(p.upper()) for p in prefixes):
                return bank
        return None

    def by_signature(self, text: str) -> list[Bank]:
        """Banks whose receipt-only wording appears in the text."""
        norm = normalize_name(text)
        found = []
        for bank in self.catalog:
            signatures = self.info.get(bank.code3, BankInfo(bank.code3)).receipt_signatures
            if any(next(_word_spans(norm, normalize_name(s)), None) for s in signatures):
                found.append(bank)
        return found
