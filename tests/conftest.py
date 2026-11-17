import json
from pathlib import Path

import pytest

from cepxico.banks import BankCatalog, BankDirectory

DATA_DIR = Path(__file__).parent / "data"


def with_check_digit(first17: str) -> str:
    """Builds a valid CLABE from its first 17 digits."""
    weights = (3, 7, 1)
    total = sum((int(d) * weights[i % 3]) % 10 for i, d in enumerate(first17))
    return first17 + str((10 - total % 10) % 10)


def load_catalog_json(date: str) -> dict:
    """Snapshot of Banxico's instituciones.do response for `date` (yyyy-mm-dd). Public data."""
    return json.loads((DATA_DIR / f"instituciones_{date}.json").read_text(encoding="utf-8"))


def load_catalog(date: str) -> BankCatalog:
    return BankCatalog.from_rows(load_catalog_json(date)["instituciones"])


@pytest.fixture(scope="session")
def catalog_json() -> dict:
    return load_catalog_json("2026-11-10")


@pytest.fixture(scope="session")
def catalog() -> BankCatalog:
    return load_catalog("2026-11-10")


@pytest.fixture(scope="session")
def directory(catalog) -> BankDirectory:
    return BankDirectory(catalog)


@pytest.fixture
def bbva_clabe() -> str:
    return with_check_digit("01218000123456789")


@pytest.fixture(autouse=True)
def banxico_is_open(monkeypatch):
    """Banxico only answers 09:30-23:00; tests must not depend on when they run.
    Tests about the hours set pipeline.banxico_open themselves."""
    from cepxico import pipeline

    monkeypatch.setattr(pipeline, "banxico_open", lambda now=None: True)


@pytest.fixture(scope="session")
def window(tmp_path_factory):
    """The desktop app's window, shared by every test that needs Tk: creating and
    destroying many Tk roots in one process makes Tcl fail to initialise now and then
    on Windows. Created before per-test fixtures run, so it gets its own data folder."""
    from cepxico.gui import app as gui
    from cepxico.history import History

    home = tmp_path_factory.mktemp("window_home")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CEPXICO_HOME", str(home))
        try:
            window = gui.CEPApp(tmp_path_factory.mktemp("ceps"), history=History(home / "history.sqlite3"))
        except Exception as e:  # no display, or tkdnd missing
            pytest.skip(f"Tk unavailable: {e}")
    window.withdraw()
    yield window
    window.destroy()


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Never read or write the real user's settings or history."""
    monkeypatch.setenv("CEPXICO_HOME", str(tmp_path / "appdata"))


@pytest.fixture(autouse=True)
def english():
    """Messages in English whatever the machine's language; tests about Spanish switch."""
    from cepxico import i18n

    i18n.set_language("en")
    yield
    i18n.set_language("en")
