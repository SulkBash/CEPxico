import json
from pathlib import Path

import pytest

from cepxico.banks import BankCatalog

DATA_DIR = Path(__file__).parent / "data"


def with_check_digit(first17: str) -> str:
    """Builds a valid CLABE from its first 17 digits."""
    weights = (3, 7, 1)
    total = sum((int(d) * weights[i % 3]) % 10 for i, d in enumerate(first17))
    return first17 + str((10 - total % 10) % 10)


@pytest.fixture(scope="session")
def catalog_json() -> dict:
    """Snapshot of Banxico's instituciones.do response (public data)."""
    return json.loads((DATA_DIR / "instituciones_2026-11-10.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def catalog(catalog_json) -> BankCatalog:
    return BankCatalog.from_rows(catalog_json["instituciones"])


@pytest.fixture
def bbva_clabe() -> str:
    return with_check_digit("01218000123456789")
