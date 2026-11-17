"""BanxicoCEPClient against a fake HTTP session (no network)."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pytest
import requests

from cepxico.banks import Bank, BankCatalog
from cepxico.banxico import BanxicoCEPClient, BanxicoError, CatalogCache, CEPStatus

BANORTE = Bank("40072", "BANORTE")
BBVA = Bank("40012", "BBVA MEXICO")


@dataclass
class FakeResponse:
    status_code: int = 200
    text: str = ""
    content: bytes = b""
    json_data: dict | None = None

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


@dataclass
class FakeSession:
    catalog_json: dict
    valida: FakeResponse
    pdf: FakeResponse
    posted: dict | None = None
    headers: dict = field(default_factory=dict)
    cookies: requests.cookies.RequestsCookieJar = field(default_factory=requests.cookies.RequestsCookieJar)
    calls: list[str] = field(default_factory=list)

    def get(self, url, params=None, **_kwargs):
        self.calls.append(url)
        if url.endswith("instituciones.do"):
            return FakeResponse(json_data=self.catalog_json)
        if url.endswith("descarga.do"):
            return self.pdf
        return FakeResponse(text="<html>cep</html>")

    def post(self, url, data=None, **_kwargs):
        self.posted = data
        return self.valida

    def close(self):
        pass


PDF = FakeResponse(content=b"%PDF-1.4 fake cep")
NO_PDF = FakeResponse(text="<html>error</html>", content=b"<html>error</html>")


@pytest.fixture
def lookup(tmp_path, catalog_json, bbva_clabe):
    def run(valida: FakeResponse, pdf: FakeResponse = PDF, **overrides):
        client = BanxicoCEPClient(tmp_path)
        client.session = FakeSession(catalog_json, valida, pdf)
        query = {
            "fecha": "10-11-2026",
            "clave_rastreo": "MBAN01002611100012345678",
            "sender": BANORTE,
            "receiver": BBVA,
            "account": bbva_clabe,
            "amount": "1,234.5",
        }
        query.update(overrides)
        return client.download_cep(**query), client.session.posted

    return run


def test_found_saves_pdf(lookup, tmp_path):
    result, posted = lookup(FakeResponse(text="<a href='descarga.do?formato=PDF'>PDF</a>"))

    assert result.status is CEPStatus.FOUND and result.ok
    assert result.pdf_path == tmp_path / "CEP_10-11-2026_MBAN01002611100012345678.pdf"
    assert result.pdf_path.read_bytes().startswith(b"%PDF")
    assert posted["emisor"] == "40072"
    assert posted["receptor"] == "40012"
    assert posted["monto"] == "1234.50"
    assert posted["tipoConsulta"] == "1"
    assert posted["captcha"] == "c"


def test_not_found_reports_banxico_message(lookup):
    result, _ = lookup(FakeResponse(text="<div>No se encontró información</div>"), pdf=NO_PDF)
    assert result.status is CEPStatus.NOT_FOUND
    assert result.message == "No se encontró información"


@pytest.mark.parametrize(
    ("valida", "status"),
    [
        (FakeResponse(text="<p>meta:stats=ERR</p>"), CEPStatus.INPUT_ERROR),
        (FakeResponse(text="<input type='hidden' name='varHideCaptcha' value='false'/>"), CEPStatus.CAPTCHA),
        (FakeResponse(status_code=503, text="Service Unavailable"), CEPStatus.ERROR),
    ],
)
def test_banxico_responses(lookup, valida, status):
    result, _ = lookup(valida)
    assert result.status is status


@pytest.mark.parametrize(
    "overrides",
    [
        {"sender": BBVA},  # same bank on both sides
        {"fecha": "2026-11-10"},
        {"amount": "abc"},
        {"clave_rastreo": ""},
    ],
)
def test_invalid_input_is_rejected_before_posting(lookup, overrides):
    result, posted = lookup(FakeResponse(text="unused"), **overrides)
    assert result.status is CEPStatus.INPUT_ERROR
    assert posted is None


def test_catalog_is_fetched_once_per_date(tmp_path, catalog_json):
    client = BanxicoCEPClient(tmp_path)
    session = FakeSession(catalog_json, PDF, PDF)
    calls = []
    original_get = session.get
    session.get = lambda url, **kw: calls.append(url) or original_get(url, **kw)
    client.session = session

    first, second = client.get_catalog("10-11-2026"), client.get_catalog("10-11-2026")

    assert first is second and len(first) == 97
    assert sum(url.endswith("instituciones.do") for url in calls) == 1


def test_catalog_failure_raises_banxico_error(tmp_path, catalog_json):
    client = BanxicoCEPClient(tmp_path)
    client.session = FakeSession({"instituciones": []}, PDF, PDF)
    with pytest.raises(BanxicoError):
        client.get_catalog("10-11-2026")


def test_catalog_cache_loads_each_date_once_across_threads():
    cache = CatalogCache()
    loads = []

    def load():
        loads.append(1)
        time.sleep(0.02)  # wide window for a second thread to race in
        return BankCatalog([Bank("40012", "BBVA MEXICO")])

    with ThreadPoolExecutor(8) as pool:
        catalogs = list(pool.map(lambda _: cache.get("05-11-2026", load), range(8)))

    assert len(loads) == 1
    assert all(c is catalogs[0] for c in catalogs)


def test_failed_catalog_load_is_retried():
    cache = CatalogCache()

    def fail():
        raise BanxicoError("down")

    with pytest.raises(BanxicoError):
        cache.get("05-11-2026", fail)
    assert len(cache.get("05-11-2026", lambda: BankCatalog([]))) == 0


def test_each_lookup_starts_a_new_session(tmp_path, catalog_json, bbva_clabe):
    """descarga.do serves the session's last CEP: a cookie from an earlier lookup must
    never reach the next one, or a rejected lookup could download the previous CEP."""
    client = BanxicoCEPClient(tmp_path)
    client.session = session = FakeSession(catalog_json, FakeResponse(text="ok"), PDF)
    session.cookies.set("JSESSIONID", "previous-receipt")
    client._started = True

    client.download_cep(
        fecha="10-11-2026",
        clave_rastreo="MBAN01002611100012345678",
        sender=BANORTE,
        receiver=BBVA,
        account=bbva_clabe,
        amount="10",
    )

    assert "JSESSIONID" not in session.cookies
    assert session.calls[0] == client.base_url  # new session before valida.do


def test_catalog_cache_loads_different_dates_in_parallel():
    cache = CatalogCache()
    barrier = threading.Barrier(2, timeout=2)

    def load():
        barrier.wait()  # deadlocks (BrokenBarrierError) if loads are serialized
        return BankCatalog([])

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda fecha: cache.get(fecha, load), ["05-11-2026", "06-11-2026"]))
