"""Dollar transfers (SPID): Banxico's CEP-SPID client, the security code a person types,
and how the pipeline, the desktop app and the command line ask for it. No network."""

import io
import json
from pathlib import Path

import pytest

from cepxico import pipeline
from cepxico.banks import Bank, BankCatalog
from cepxico.banxico import BanxicoError, CEPResult, CEPStatus, SPIDClient
from cepxico.models import PaymentData
from cepxico.pipeline import (
    MAX_CODE_ATTEMPTS,
    CodeRequest,
    Outcome,
    SPIDLookup,
    process_file,
    process_files,
)
from tests.conftest import DATA_DIR, with_check_digit
from tests.test_banxico import PDF, FakeResponse, FakeSession
from tests.test_pipeline import FakeClient

BANORTE = Bank("40072", "BANORTE")
BBVA = Bank("40012", "BBVA MEXICO")
IMAGE = b"\x89PNG fake security image"


def spid_catalog_json() -> dict:
    """Snapshot of CEP-SPID's instituciones.do for 2026-11-10. Public data."""
    return json.loads((DATA_DIR / "instituciones_spid_2026-11-10.json").read_text(encoding="utf-8"))


class SPIDSession(FakeSession):
    """FakeSession that also serves the security image and records query parameters."""

    def __init__(self, valida: FakeResponse, **kwargs):
        super().__init__(spid_catalog_json(), valida, PDF, **kwargs)
        self.params: list[dict | None] = []
        self.cleared = 0

    def get(self, url, params=None, **kwargs):
        self.params.append(params)
        if url.endswith("stickyImg"):
            self.calls.append(url)
            return FakeResponse(content=IMAGE)
        return super().get(url, params=params, **kwargs)


CEP_LINKS = FakeResponse(text="<a href='descarga.do'>PDF</a>")


@pytest.fixture
def spid_client(tmp_path):
    def make(valida: FakeResponse = CEP_LINKS):
        client = SPIDClient(tmp_path)
        client.session = SPIDSession(valida)
        return client

    return make


QUERY = {
    "fecha": "10-11-2026",
    "clave_rastreo": "SPID2611100012345",
    "sender": BANORTE,
    "receiver": BBVA,
    "account": with_check_digit("01218000123456789"),
    "amount": "1,500.00",
}


# --- The CEP-SPID client ------------------------------------------------------------


def test_spid_bank_list_is_read_from_its_own_format(spid_client):
    client = spid_client()
    catalog = client.get_catalog("10-11-2026")

    assert client.session.params[-1] == {"fecha": "20261110"}  # the SPID page's date format
    assert catalog.by_code3("012") == BBVA  # names come padded with spaces
    assert catalog.by_code3("072") == BANORTE


def test_lookup_sends_the_typed_code_on_the_session_that_showed_the_image(spid_client):
    client = spid_client()

    assert client.security_image() == IMAGE
    result = client.download_cep(**QUERY, captcha="X7K2Q")

    assert result.status is CEPStatus.FOUND
    assert result.saved_path.name == "CEP_SPID_10-11-2026_SPID2611100012345.pdf"
    calls = [c.rsplit("/", 1)[-1] for c in client.session.calls]
    # The image's session is kept for the lookup: no new session between them.
    assert calls == ["", "stickyImg", "descarga.do?formato=XML", "descarga.do?formato=PDF"]
    assert client.session.posted == {
        "tipoCriterio": "R",  # clave de rastreo on this page ("T" on SPEI's)
        "fecha": "20261110",
        "criterio": "SPID2611100012345",
        "emisor": "40072",
        "receptor": "40012",
        "cuenta": QUERY["account"],
        "monto": "1500.00",
        "pagoABanco": "false",
        "captcha": "X7K2Q",
        "tipoConsulta": "1",
    }


def test_pago_a_banco_is_sent_as_the_spid_page_does(spid_client):
    client = spid_client()
    client.security_image()
    client.download_cep(**QUERY, pago_a_banco=True, captcha="X")
    assert client.session.posted["pagoABanco"] == "true"


def test_one_image_serves_one_lookup(spid_client):
    client = spid_client()
    assert client.download_cep(**QUERY, captcha="X").status is CEPStatus.ERROR  # no image shown

    client.security_image()
    client.download_cep(**QUERY, captcha="X")
    assert client.download_cep(**QUERY, captcha="X").status is CEPStatus.ERROR  # image used up


def test_a_wrong_code_is_told_apart(spid_client):
    client = spid_client(FakeResponse(text="<!-- meta:stats=ERR -->"))
    client.security_image()
    result = client.download_cep(**QUERY, captcha="WRONG")
    assert result.status is CEPStatus.WRONG_CODE


def test_spid_page_always_shows_its_image_so_it_isnt_taken_for_a_lookup_limit(spid_client):
    page = "<input name='varHideCaptcha' value='false'/> No se encontró ningún pago"
    client = spid_client(FakeResponse(text=page))
    client.security_image()
    assert client.download_cep(**QUERY, captcha="X").status is CEPStatus.NOT_FOUND


def test_another_image_keeps_the_session(spid_client):
    client = spid_client()
    client.security_image()
    assert client.new_image() == IMAGE
    assert [c.rsplit("/", 1)[-1] for c in client.session.calls] == ["", "stickyImg", "stickyImg"]


# --- The pipeline ---------------------------------------------------------------------

DOLLARS = PaymentData(
    source_file="usd.pdf",
    payment_date="10-11-2026",
    tracking_key="SPID2611100012345",
    sender_bank="Banorte",
    beneficiary_account=with_check_digit("01218000123456789"),
    amount="1500.00",
    spid=True,
)
FOUND = CEPResult(CEPStatus.FOUND, "ok", pdf_path=Path("CEP_SPID_x.pdf"))
WRONG = CEPResult(CEPStatus.WRONG_CODE, "wrong")


class FakeSPIDClient(FakeClient):
    def __init__(self, *results: CEPResult):
        super().__init__(results[0], BankCatalog.from_rows([("40072", "BANORTE"), ("40012", "BBVA MEXICO")]))
        self.results = list(results)
        self.images = 0
        self.codes: list[str] = []

    def security_image(self):
        self.images += 1
        return IMAGE

    def new_image(self):
        return IMAGE

    def download_cep(self, *, captcha, **query):
        self.codes.append(captcha)
        self.calls.append(query)
        return self.results.pop(0)

    def close(self):
        pass


@pytest.fixture
def receipt(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "usd.pdf"
    path.write_bytes(b"%PDF placeholder")
    monkeypatch.setattr(pipeline, "extract_payment", lambda _path: DOLLARS)
    return path


def asker(*answers):
    requests: list[CodeRequest] = []
    remaining = list(answers)

    def ask(request: CodeRequest):
        requests.append(request)
        return remaining.pop(0)

    return ask, requests


def test_dollar_receipt_is_checked_with_the_code_typed(receipt):
    spei = FakeClient(FOUND)
    spid = FakeSPIDClient(FOUND)
    ask, requests = asker(" x7k2q ")

    result = process_file(receipt, spei, spid=SPIDLookup(spid, ask))

    assert result.outcome is Outcome.SUCCESS
    assert spid.codes == ["x7k2q"]
    assert spei.calls == []  # never sent to the SPEI service
    (request,) = requests
    assert (request.file_name, request.amount, request.attempt, request.retry) == (
        "usd.pdf",
        "1500.00",
        1,
        False,
    )
    assert request.image == IMAGE


def test_a_wrong_code_shows_a_new_image(receipt):
    spid = FakeSPIDClient(WRONG, FOUND)
    ask, requests = asker("AAAA", "BBBB")

    result = process_file(receipt, FakeClient(FOUND), spid=SPIDLookup(spid, ask))

    assert result.outcome is Outcome.SUCCESS
    assert spid.images == 2 and spid.codes == ["AAAA", "BBBB"]
    assert [r.retry for r in requests] == [False, True]


def test_skipping_the_code_leaves_the_receipt_unchecked(receipt):
    spid = FakeSPIDClient(FOUND)
    result = process_file(receipt, FakeClient(FOUND), spid=SPIDLookup(spid, asker(None)[0]))
    assert result.outcome is Outcome.FAILED
    assert result.message == "Not checked: no code typed"
    assert spid.codes == []


def test_gives_up_after_too_many_wrong_codes(receipt):
    spid = FakeSPIDClient(*[WRONG] * MAX_CODE_ATTEMPTS)
    ask, _ = asker(*["X"] * MAX_CODE_ATTEMPTS)
    result = process_file(receipt, FakeClient(FOUND), spid=SPIDLookup(spid, ask))
    assert result.outcome is Outcome.FAILED
    assert result.message.startswith(f"Code rejected {MAX_CODE_ATTEMPTS} times")


def test_banks_come_from_the_spid_list(receipt):
    spid = FakeSPIDClient(FOUND)
    result = process_file(receipt, FakeClient(FOUND), spid=SPIDLookup(spid, asker("X")[0]))
    assert result.sender.bank == BANORTE and result.receiver.bank == BBVA


def test_batch_sends_pesos_to_spei_and_dollars_to_spid(tmp_path, monkeypatch):
    pesos = tmp_path / "mxn.pdf"
    dollars = tmp_path / "usd.pdf"
    for path in (pesos, dollars):
        path.write_bytes(b"%PDF")
    from dataclasses import replace

    monkeypatch.setattr(
        pipeline,
        "extract_payment",
        lambda path: DOLLARS if Path(path).name == "usd.pdf" else replace(DOLLARS, spid=False),
    )
    spei_clients, spid_clients = [], []

    def spei_factory(_cache):
        client = FakeSPIDClient(FOUND, FOUND)  # same fake; used without a code here
        client.download_cep = lambda **query: spei_clients.append(query) or FOUND
        return client

    def spid_factory(_cache):
        client = FakeSPIDClient(FOUND)
        spid_clients.append(client)
        return client

    results = process_files(
        [pesos, dollars],
        tmp_path,
        jobs=1,
        client_factory=spei_factory,
        spid_client_factory=spid_factory,
        ask_code=lambda request: "CODE",
    )

    assert [r.outcome for r in results] == [Outcome.SUCCESS, Outcome.SUCCESS]
    assert len(spei_clients) == 1
    assert [c.codes for c in spid_clients] == [["CODE"]]


# --- Desktop app ----------------------------------------------------------------------


def png(size=(60, 20)) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, "PNG")
    return out.getvalue()


def request(**overrides) -> CodeRequest:
    values = {
        "image": png(),
        "file_name": "usd.pdf",
        "amount": "1500.00",
        "tracking_key": "SPID2611100012345",
        "attempt": 1,
        "new_image": lambda: png((80, 30)),
    }
    return CodeRequest(**(values | overrides))


def test_code_dialog_returns_the_code_typed(window):
    from cepxico.gui.code_dialog import CodeDialog

    answers = []
    dialog = CodeDialog(window, request=request(), on_answer=answers.append)
    assert dialog.picture is not None and dialog.picture.width() == 120  # shown at twice the size
    dialog.submit()  # nothing typed yet: stays open
    assert answers == [] and dialog.isVisible()

    dialog.code.setText(" ab12 ")
    dialog.submit()
    assert answers == ["ab12"] and not dialog.isVisible()


def test_code_dialog_skip_and_another_image(window):
    from cepxico.gui.code_dialog import CodeDialog

    answers = []
    dialog = CodeDialog(window, request=request(attempt=2), on_answer=answers.append)
    dialog.another_image()
    assert dialog.picture.width() == 160
    dialog.reject()  # Escape, or the window's close button
    assert answers == [None] and not dialog.isVisible()


def test_code_dialog_reports_an_image_it_cant_get(window):
    from cepxico.gui.code_dialog import CodeDialog

    def fail():
        raise BanxicoError("Banxico is down")

    dialog = CodeDialog(window, request=request(image=b"junk", new_image=fail), on_answer=lambda _c: None)
    assert "Ask for another" in dialog.image_label.text()
    dialog.another_image()
    assert dialog.image_label.text() == "Banxico is down"
    dialog.skip()


# --- Command line ---------------------------------------------------------------------


def test_command_line_asks_only_when_someone_is_at_the_terminal():
    from cepxico import cli

    assert cli.interactive_ask_code() is None  # pytest's stdin isn't a terminal


def test_terminal_prompt_can_show_another_image(monkeypatch, capsys):
    from cepxico import cli

    opened, answers = [], iter(["?", " Q9W "])
    monkeypatch.setattr(cli, "open_path", opened.append)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    new_images = []

    code = cli.terminal_ask_code(request(new_image=lambda: new_images.append(1) or png()))

    assert code == "Q9W"
    assert len(opened) == 2 and new_images == [1]
    assert not any(Path(p).exists() for p in opened)  # temporary images cleaned up
    assert "dollar transfer (SPID) of 1500.00" in capsys.readouterr().out


def test_terminal_prompt_enter_skips(monkeypatch):
    from cepxico import cli

    monkeypatch.setattr(cli, "open_path", lambda _p: None)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    assert cli.terminal_ask_code(request()) is None
