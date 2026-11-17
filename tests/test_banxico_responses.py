"""How BanxicoCEPClient reads each kind of answer from Banxico.

The pages below are trimmed versions of real valida.do / descarga.do responses (as
recorded by the cepmex project's test suite), with made-up transfer data.
"""

import zipfile

import pytest

from cepxico.banxico import BanxicoCEPClient, CEPFiles, CEPStatus, parse_cep_xml
from tests.test_banxico import BANORTE, BBVA, PDF, FakeResponse, FakeSession

CLAVE = "MBAN01002611100012345678"

FOUND_PAGE = """<div class="bg-banxico title-bar"> Descargar CEP </div>
<h2>Gracias por utilizar el servicio de descarga de CEP</h2>
Haga clic sobre el &iacute;cono para descargar el CEP.
<a href="descarga.do?formato=PDF">PDF</a> <a href="descarga.do?formato=XML">XML</a>
<a href="descarga.do?formato=ZIP">ZIP</a>"""

NOT_FOUND_PAGE = """<div class="bg-banxico title-bar"> Error </div>
<div id="#error_div"><div class="info"><p> [BE] No se encontró ningún pago con la información
proporcionada. Verifique e intente nuevamente. </p></div></div>
<input type="hidden" name="varHideCaptcha" value="true"/>"""

OPERATION_NOT_FOUND_PAGE = """<head><title>CEP</title></head>
<div class="bg-banxico title-bar">Informaci&oacute;n del estado del pago</div>
<p>Lo sentimos, por el momento no es posible generar el CEP. Operación no encontrada. El SPEI no
ha recibido una orden de pago que cumpla con el criterio de búsqueda especificado.</p>"""


def no_cep_page(status: str) -> str:
    # The legend at the end also describes "No encontrado", like the real page.
    return f"""<div class="bg-banxico title-bar">Informaci&oacute;n del estado del pago</div>
<div class="info"><strong>Lo sentimos, por el momento no es posible generar el CEP. Con la
información proporcionada se identificó el siguiente pago:</strong></div>
<table><tbody>
<tr><td>Clave de Rastreo</td><td>{CLAVE}</td></tr>
<tr><td>Instituci&oacute;n emisora del pago</td><td>BANORTE</td></tr>
<tr><td>Estado del pago en Banxico</td><td>{status}</td></tr>
<tr><td>Monto</td><td>1234.50</td></tr>
</tbody></table>
<p>No encontrado El SPEI® no ha recibido una orden de pago que cumpla con el criterio de
búsqueda especificado.</p>"""


CAPTCHA_PAGE = """<div class="bg-banxico title-bar"> Error </div>
<p> La imagen de seguridad no fue ingresada correctamente. Favor de validar. </p>
<input type="hidden" name="varHideCaptcha" value="false"/>"""

RATE_LIMIT_PAGE = """<!DOCTYPE html><html><body>COMPROBANTE ELECTR&Oacute;NICO DE PAGO (CEP)
Lo sentimos, pero ha excedido el n&uacute;mero m&aacute;ximo de consultas en este portal.
Favor de intentar nuevamente m&aacute;s tarde.</body></html>"""


def cep_xml(*, amount="1234.50", clave=CLAVE, account="012180001234567893", pago_a_banco=False) -> bytes:
    beneficiary = (
        'Nombre="NA" TipoCuenta="-1" Cuenta="NA" RFC="NA"'
        if pago_a_banco
        else f'Nombre="Comercio Ejemplo SA" TipoCuenta="40" Cuenta="{account}" RFC="CEJ010101AB1"'
    )
    sender_account = account if pago_a_banco else "072180001234567891"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<SPEI_Tercero FechaOperacion="2026-11-10" Hora="10:53:36" ClaveSPEI="40012" sello="c2VsbG8="
 numeroCertificado="00000100000100014853" cadenaCDA="||1|10112026|10112026|105336|40012|..."
 claveRastreo="{clave}">
 <Beneficiario BancoReceptor="BBVA MEXICO" {beneficiary} Concepto="Pedido 418" IVA="0.00"
  MontoPago="{amount}"/>
 <Ordenante BancoEmisor="BANORTE" Nombre="Juan Pérez" TipoCuenta="40" Cuenta="{sender_account}"
  RFC="PEJJ800101AAA"/>
</SPEI_Tercero>""".encode()


@pytest.fixture
def check(tmp_path, catalog_json, bbva_clabe):
    """Runs one lookup against canned Banxico responses; returns (result, session)."""

    def run(valida_page, *, xml=None, pdf=PDF, **overrides):
        client = BanxicoCEPClient(tmp_path)
        session = FakeSession(catalog_json, FakeResponse(text=valida_page), pdf, xml=xml)
        client.session = session
        query = dict(
            fecha="10-11-2026",
            clave_rastreo=CLAVE,
            sender=BANORTE,
            receiver=BBVA,
            account=bbva_clabe,
            amount="1234.50",
        )
        query.update(overrides)
        return client.download_cep(**query), session

    return run


def downloads(session) -> list[str]:
    return [c for c in session.calls if "descarga.do" in c]


def test_parse_cep_xml():
    record = parse_cep_xml(cep_xml())
    assert record.operation_date == "10-11-2026" and record.time == "10:53:36"
    assert record.tracking_key == CLAVE and record.amount == "1234.50"
    assert record.beneficiary.name == "Comercio Ejemplo SA"
    assert record.beneficiary.account == "012180001234567893"
    assert record.sender.name == "Juan Pérez" and record.sender.bank == "BANORTE"
    assert record.concept == "Pedido 418"


def test_parse_pago_a_banco_xml_has_no_beneficiary_account():
    record = parse_cep_xml(cep_xml(pago_a_banco=True, account="072180001234567891"))
    assert record.beneficiary.account == "" and record.beneficiary.name == ""
    assert record.sender.account == "072180001234567891"


@pytest.mark.parametrize("data", [b"<html>error</html>", b"not xml", b"<SPEI_Tercero/>"])
def test_parse_rejects_what_isnt_a_cep(data):
    with pytest.raises(ValueError):
        parse_cep_xml(data)


STEM = f"CEP_10-11-2026_{CLAVE}"


def saved(tmp_path) -> list[str]:
    return sorted(p.name for p in tmp_path.iterdir())


def test_pdf_only_still_reads_the_xml(check, tmp_path):
    result, session = check(FOUND_PAGE, xml=FakeResponse(content=cep_xml()))
    assert result.status is CEPStatus.FOUND
    assert result.record.beneficiary.name == "Comercio Ejemplo SA"
    assert result.saved_path == result.pdf_path == tmp_path / f"{STEM}.pdf"
    assert saved(tmp_path) == [f"{STEM}.pdf"]
    assert downloads(session) == [
        "https://www.banxico.org.mx/cep/descarga.do?formato=XML",
        "https://www.banxico.org.mx/cep/descarga.do?formato=PDF",
    ]


def test_xml_only_skips_the_pdf_download(check, tmp_path):
    result, session = check(FOUND_PAGE, xml=FakeResponse(content=cep_xml()), cep_files=CEPFiles.XML)
    assert result.status is CEPStatus.FOUND and result.record is not None
    assert result.saved_path == result.xml_path == tmp_path / f"{STEM}.xml"
    assert result.xml_path.read_bytes() == cep_xml()
    assert saved(tmp_path) == [f"{STEM}.xml"]
    assert downloads(session) == ["https://www.banxico.org.mx/cep/descarga.do?formato=XML"]


def test_zip_holds_pdf_and_xml_and_nothing_else_is_saved(check, tmp_path):
    result, session = check(FOUND_PAGE, xml=FakeResponse(content=cep_xml()), cep_files=CEPFiles.ZIP)

    assert result.zip_path == tmp_path / f"{STEM}.zip" and result.saved_path == result.zip_path
    assert result.pdf_path is None and result.xml_path is None
    assert saved(tmp_path) == [f"{STEM}.zip"]
    with zipfile.ZipFile(result.zip_path) as archive:
        assert sorted(archive.namelist()) == [f"{STEM}.pdf", f"{STEM}.xml"]
        assert archive.read(f"{STEM}.pdf") == PDF.content
        assert archive.read(f"{STEM}.xml") == cep_xml()
    # Built from the two downloads; Banxico's own ZIP isn't requested.
    assert not any("ZIP" in c for c in downloads(session))


def test_xml_wanted_but_unreadable_saves_the_pdf(check, tmp_path):
    result, _ = check(FOUND_PAGE, xml=FakeResponse(content=b"<html>error</html>"), cep_files=CEPFiles.XML)
    assert result.status is CEPStatus.FOUND and result.record is None
    assert result.saved_path == result.pdf_path and saved(tmp_path) == [f"{STEM}.pdf"]


def test_zip_without_readable_xml_holds_only_the_pdf(check):
    result, _ = check(FOUND_PAGE, xml=FakeResponse(content=b"<html>error</html>"), cep_files=CEPFiles.ZIP)
    with zipfile.ZipFile(result.zip_path) as archive:
        assert archive.namelist() == [f"{STEM}.pdf"]


@pytest.mark.parametrize(
    ("status", "message_start"),
    [
        ("Liquidado", "Payment is real and settled (Liquidado)"),
        ("En proceso", "Banxico received the payment but hasn't settled it yet"),
        ("Cancelado", "Payment was cancelled"),
        ("Retornado", "Payment was returned"),
        ("Rechazado", "Banxico found the payment (status: Rechazado)"),
    ],
)
def test_payment_without_cep_is_not_reported_as_missing(check, status, message_start):
    result, session = check(no_cep_page(status))
    assert result.status is CEPStatus.NO_CEP
    assert result.payment_status == status
    assert result.message.startswith(message_start)
    assert downloads(session) == []


@pytest.mark.parametrize("page", [NOT_FOUND_PAGE, OPERATION_NOT_FOUND_PAGE])
def test_not_found_pages(check, page):
    result, session = check(page)
    assert result.status is CEPStatus.NOT_FOUND
    assert "No se encontró ningún pago" in result.message or "Operación no encontrada" in result.message
    assert "&" not in result.message  # entities decoded
    assert downloads(session) == []  # nothing to download


def test_captcha_means_too_many_lookups(check):
    result, _ = check(CAPTCHA_PAGE)
    assert result.status is CEPStatus.CAPTCHA
    assert "too many lookups" in result.message


def test_rate_limit_page_on_download(check):
    result, _ = check(FOUND_PAGE, xml=FakeResponse(text=RATE_LIMIT_PAGE, content=RATE_LIMIT_PAGE.encode()))
    assert result.status is CEPStatus.RATE_LIMITED


def test_pago_a_banco_is_sent(check):
    _, session = check(FOUND_PAGE, xml=FakeResponse(content=cep_xml()), pago_a_banco=True)
    assert session.posted["receptorParticipante"] == "1"
    _, session = check(FOUND_PAGE, xml=FakeResponse(content=cep_xml()))
    assert session.posted["receptorParticipante"] == "0"


@pytest.mark.parametrize("amount", ["0", "-5", "abc", "NaN"])
def test_invalid_amounts_are_rejected_before_posting(check, amount):
    result, session = check(FOUND_PAGE, amount=amount)
    assert result.status is CEPStatus.INPUT_ERROR and session.posted is None
