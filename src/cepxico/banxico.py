"""
Direct HTTP client for Banxico's CEP service (https://www.banxico.org.mx/cep/).

Makes the same requests as the official page's JavaScript (js/cep-min.js):

  1. GET  /cep/                          -> session cookie
  2. GET  /cep/instituciones.do?fecha=   -> JSON bank catalog [[code, name], ...]
  3. POST /cep/valida.do                 -> validates the operation (HTML fragment)
  4. GET  /cep/descarga.do?formato=XML   -> the CEP's data, digitally signed by Banxico
  5. GET  /cep/descarga.do?formato=PDF   -> the CEP itself, same session

valida.do answers with one of these (wording from recorded responses, see tests):
  - links to descarga.do                        the CEP exists
  - "...se identificó el siguiente pago"        the payment exists but has no CEP; a
                                                table gives its status (Liquidado,
                                                En proceso, Cancelado, Retornado...)
  - "No se encontró ningún pago..." /           no such payment
    "Operación no encontrada..."
  - the security image again                    usually after too many lookups;
                                                descarga.do then says "ha excedido el
                                                número máximo de consultas"

"Pago a Banco" (receptorParticipante=1) is for payments to the receiving bank itself
rather than to one of its customers. The account sent is then the *ordering* account,
and the CEP's beneficiary has no account (Cuenta="NA").

Banxico currently disables the security image ("overrideCaptcha": true); the page
then sends the fixed value "c", and so do we. If Banxico turns the captcha back on,
we report it instead of trying to get around it.
"""

from __future__ import annotations

import html
import logging
import re
import threading
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from types import TracebackType

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from cepxico.banks import Bank, BankCatalog

logger = logging.getLogger(__name__)

BASE_URL = "https://www.banxico.org.mx/cep/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) cep-client/2.0"
REQUEST_TIMEOUT = 90  # valida.do can take >25 s when searching historical data
MAX_CLAVE_LEN = 30
# Connection failures and gateway errors are retried with backoff (1.5 s, 3 s). Every
# request is a read-only query, so retrying the POST is safe too. Read timeouts aren't
# retried: after 90 s, waiting another 90 s rarely helps.
RETRY = Retry(
    total=2,
    read=0,
    backoff_factor=1.5,
    status_forcelist=(502, 503, 504),
    allowed_methods=None,
    raise_on_status=False,
)
_XHR = {"X-Requested-With": "XMLHttpRequest"}


class CEPStatus(StrEnum):
    FOUND = "found"  # CEP exists and the PDF was saved
    NOT_FOUND = "not_found"  # Banxico has no such payment (possible fake receipt)
    NO_CEP = "no_cep"  # the payment exists but has no CEP; see CEPResult.payment_status
    INPUT_ERROR = "input_error"  # data invalid
    CAPTCHA = "captcha"  # Banxico is asking for the security image (usually: too many lookups)
    RATE_LIMITED = "rate_limited"  # Banxico says too many lookups; try again later
    ERROR = "error"  # network/server problem; says nothing about the receipt


# Once Banxico answers like this it refuses further lookups for a while.
BLOCKED_STATUSES = frozenset({CEPStatus.CAPTCHA, CEPStatus.RATE_LIMITED})

_NO_CEP_MARK = re.compile(r"identific\w*\s+el\s+siguiente\s+pago", re.IGNORECASE)
_NOT_FOUND_MARK = re.compile(
    r"No\s+se\s+encontr\w*\s+ning\w*\s+pago|Operaci\w*\s+no\s+encontrada", re.IGNORECASE
)
_RATE_LIMIT_MARK = re.compile(r"excedido\s+el\s+n\w*\s+m\w*\s+de\s+consultas", re.IGNORECASE)
_PAYMENT_STATUS = re.compile(
    r"Estado\s+del\s+pago\s+en\s+Banxico\s*</td>\s*<td[^>]*>\s*([^<]+?)\s*<", re.IGNORECASE
)
RATE_LIMIT_MESSAGE = "Banxico's limit of lookups was reached; try again later"

# What each status of a payment without CEP means for whoever was paid.
NO_CEP_MESSAGES = {
    "LIQUIDADO": "Payment is real and settled (Liquidado), but the receiving bank hasn't "
    "issued its CEP yet; check again later",
    "EN PROCESO": "Banxico received the payment but hasn't settled it yet (En proceso); check again later",
    "CANCELADO": "Payment was cancelled before it settled (Cancelado); the money didn't arrive",
    "RETORNADO": "Payment was returned by the beneficiary's bank (Retornado); the money "
    "didn't stay in the account",
    "DEVUELTO": "Payment was returned by the beneficiary's bank (Devuelto); the money "
    "didn't stay in the account",
}


@dataclass(frozen=True)
class Party:
    """One side of a transfer as its CEP records it."""

    bank: str
    name: str
    account: str  # "" when the CEP has none (the beneficiary of a pago a banco)
    rfc: str


@dataclass(frozen=True)
class CEPRecord:
    """The data in a CEP XML, which Banxico signs (`sello`, `numeroCertificado`)."""

    operation_date: str  # dd-mm-yyyy
    time: str  # hh:mm:ss
    tracking_key: str
    amount: str  # "1234.50"
    concept: str
    sender: Party
    beneficiary: Party
    certificate: str


def _party(element: ET.Element | None, bank_attr: str) -> Party:
    if element is None:
        raise ValueError("not a CEP XML: missing Ordenante or Beneficiario")

    def value(name: str) -> str:
        v = element.attrib.get(name, "").strip()
        return "" if v.upper() == "NA" else v

    return Party(bank=value(bank_attr), name=value("Nombre"), account=value("Cuenta"), rfc=value("RFC"))


def parse_cep_xml(data: bytes) -> CEPRecord:
    """Reads Banxico's CEP XML (<SPEI_Tercero ...>). Raises ValueError if it isn't one."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"not a CEP XML: {e}") from e
    sender = _party(root.find("Ordenante"), "BancoEmisor")
    beneficiary_element = root.find("Beneficiario")
    beneficiary = _party(beneficiary_element, "BancoReceptor")
    assert beneficiary_element is not None  # checked by _party
    try:
        year, month, day = root.attrib["FechaOperacion"].split("-")
        amount = Decimal(beneficiary_element.attrib["MontoPago"])
        tracking_key = root.attrib["claveRastreo"]
    except (KeyError, ValueError, InvalidOperation) as e:
        raise ValueError(f"not a CEP XML: missing or invalid {e}") from e
    return CEPRecord(
        operation_date=f"{day}-{month}-{year}",
        time=root.attrib.get("Hora", ""),
        tracking_key=tracking_key,
        amount=f"{amount:.2f}",
        concept=beneficiary_element.attrib.get("Concepto", ""),
        sender=sender,
        beneficiary=beneficiary,
        certificate=root.attrib.get("numeroCertificado", ""),
    )


class BanxicoError(Exception):
    """Banxico couldn't be reached or answered unexpectedly."""


class CEPFiles(StrEnum):
    """What to save for each CEP found."""

    PDF = "pdf"
    XML = "xml"  # Banxico's digitally signed data; the PDF if the XML can't be read
    ZIP = "zip"  # one .zip holding the PDF and the XML


@dataclass(frozen=True)
class CEPResult:
    status: CEPStatus
    message: str
    pdf_path: Path | None = None
    xml_path: Path | None = None
    zip_path: Path | None = None  # instead of separate PDF and XML files
    record: CEPRecord | None = None  # the CEP's data, when its XML could be read
    payment_status: str = ""  # Banxico's status for a payment without CEP ("Liquidado")

    @property
    def ok(self) -> bool:
        return self.status is CEPStatus.FOUND

    @property
    def saved_path(self) -> Path | None:
        """The file the CEP was saved as (ZIP, PDF or XML)."""
        return self.zip_path or self.pdf_path or self.xml_path


def _html_to_text(markup: str) -> str:
    text = re.sub(r"(?is)<(script|style|head)\b.*?</\1>|<!--.*?-->", " ", markup)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return " ".join(text.split())


def _rate_limited(body: str) -> bool:
    return bool(_RATE_LIMIT_MARK.search(html.unescape(body)))


def _safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_") or "CEP"


class CatalogCache:
    """Bank catalogs by date, safe to share between clients on different threads."""

    def __init__(self) -> None:
        self._catalogs: dict[str, BankCatalog] = {}
        self._date_locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def get(self, fecha: str, load: Callable[[], BankCatalog]) -> BankCatalog:
        # One lock per date: concurrent receipts for one date fetch its catalog once,
        # while receipts for other dates load theirs in parallel.
        with self._lock:
            date_lock = self._date_locks.setdefault(fecha, threading.Lock())
        with date_lock:
            if fecha not in self._catalogs:
                self._catalogs[fecha] = load()
            return self._catalogs[fecha]


class BanxicoCEPClient:
    """One Banxico session. Not thread-safe, and must not be shared between threads:
    descarga.do returns the CEP of the session's *last* valida.do, so two receipts
    checked concurrently on one session could each be saved with the other's CEP.
    Concurrent workers each use their own client, optionally sharing a CatalogCache."""

    def __init__(
        self,
        output_dir: Path | str,
        base_url: str = BASE_URL,
        timeout: float = REQUEST_TIMEOUT,
        catalogs: CatalogCache | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.base_url = base_url
        self.timeout = timeout
        self.session = requests.Session()
        adapter = HTTPAdapter(max_retries=RETRY)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update(
            {"User-Agent": USER_AGENT, "Referer": base_url, "Accept-Language": "es-MX,es;q=0.9"}
        )
        self._catalogs = catalogs if catalogs is not None else CatalogCache()
        self._started = False

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> BanxicoCEPClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _start(self) -> None:
        if not self._started:
            self.session.get(self.base_url, timeout=self.timeout).raise_for_status()
            self._started = True

    def _new_session(self) -> None:
        self.session.cookies.clear()
        self._started = False
        self._start()

    def get_catalog(self, fecha: str) -> BankCatalog:
        """Banks participating in SPEI on `fecha` (dd-mm-yyyy). Raises BanxicoError."""
        return self._catalogs.get(fecha, lambda: self._load_catalog(fecha))

    def _load_catalog(self, fecha: str) -> BankCatalog:
        try:
            self._start()
            resp = self.session.get(
                self.base_url + "instituciones.do",
                params={"fecha": fecha},
                headers=_XHR,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            rows = resp.json().get("instituciones")
        except (requests.RequestException, ValueError) as e:
            raise BanxicoError(f"Could not load Banxico bank list: {e}") from e
        if not rows:
            raise BanxicoError(f"Banxico returned no bank list for {fecha}")
        catalog = BankCatalog.from_rows(rows)
        logger.debug("Loaded %d banks for %s", len(catalog), fecha)
        return catalog

    def download_cep(
        self,
        *,
        fecha: str,
        clave_rastreo: str,
        sender: Bank,
        receiver: Bank,
        account: str,
        amount: str,
        pago_a_banco: bool = False,
        cep_files: CEPFiles = CEPFiles.PDF,
    ) -> CEPResult:
        """Looks up a SPEI transfer and saves its CEP into `output_dir` as `cep_files`
        says. `sender`/`receiver` come from this date's catalog (see identify.py).
        With `pago_a_banco`, `account` is the ordering account (see module docstring)."""
        account = re.sub(r"\D", "", account or "")
        clave = re.sub(r"[^A-Za-z0-9]", "", clave_rastreo or "").upper()

        if not re.fullmatch(r"\d{2}-\d{2}-\d{4}", fecha or ""):
            return CEPResult(CEPStatus.INPUT_ERROR, f"Invalid date '{fecha}' (expected dd-mm-yyyy)")
        if not 0 < len(clave) <= MAX_CLAVE_LEN:
            return CEPResult(CEPStatus.INPUT_ERROR, f"Invalid clave de rastreo '{clave_rastreo}'")
        if not 0 < len(account) <= 18:
            return CEPResult(CEPStatus.INPUT_ERROR, f"Invalid account '{account}'")
        try:
            amount_value = Decimal(str(amount).replace(",", ""))
        except InvalidOperation:
            amount_value = Decimal(0)
        if not amount_value.is_finite() or amount_value <= 0:
            return CEPResult(CEPStatus.INPUT_ERROR, f"Invalid amount '{amount}'")
        amount_fmt = f"{amount_value:.2f}"

        if sender.code == receiver.code:
            return CEPResult(
                CEPStatus.INPUT_ERROR,
                f"Sender and receiver are both {sender.name}; CEP only covers interbank transfers",
            )

        form = {
            "tipoCriterio": "T",  # T = clave de rastreo, R = número de referencia
            "fecha": fecha,
            "criterio": clave,
            "emisor": sender.code,
            "receptor": receiver.code,
            "cuenta": account,
            "receptorParticipante": "1" if pago_a_banco else "0",
            "monto": amount_fmt,
            "captcha": "c",  # what the official page sends while the captcha is disabled
            "tipoConsulta": "1",  # 1 = download CEP, 0 = only check payment status
        }

        # Every lookup gets a new Banxico session. descarga.do serves the session's last
        # CEP, so on a reused session a lookup Banxico rejects could still download the
        # previous receipt's CEP and report a fake receipt as real. One extra GET is a
        # small price for ruling that out whatever Banxico does with rejected lookups.
        try:
            self._new_session()
        except requests.RequestException as e:
            return CEPResult(CEPStatus.ERROR, f"Could not reach Banxico: {e}")

        try:
            resp = self.session.post(
                self.base_url + "valida.do", data=form, headers=_XHR, timeout=self.timeout
            )
        except requests.RequestException as e:
            return CEPResult(CEPStatus.ERROR, f"Banxico request failed: {e}")

        body = resp.text or ""
        plain = html.unescape(body)
        message = _html_to_text(body)[:300]

        if resp.status_code >= 500:
            return CEPResult(CEPStatus.ERROR, f"Banxico server error {resp.status_code}: {message}")
        if "meta:stats=ERR" in body:
            return CEPResult(CEPStatus.INPUT_ERROR, "Banxico rejected the data as incomplete or invalid")
        if _rate_limited(body):
            return CEPResult(CEPStatus.RATE_LIMITED, RATE_LIMIT_MESSAGE)
        if re.search(r"name=['\"]varHideCaptcha['\"][^>]*value=['\"]false", body):
            return CEPResult(
                CEPStatus.CAPTCHA,
                "Banxico is asking for the security image, which it does after too many lookups; "
                "try again later or check this receipt on Banxico's website",
            )
        # Checked before "not found": this page's legend also explains "No encontrado".
        if _NO_CEP_MARK.search(plain):
            status = m.group(1).strip() if (m := _PAYMENT_STATUS.search(plain)) else ""
            default = f"Banxico found the payment (status: {status or 'unknown'}) but has no CEP for it"
            return CEPResult(
                CEPStatus.NO_CEP, NO_CEP_MESSAGES.get(status.upper(), default), payment_status=status
            )
        if _NOT_FOUND_MARK.search(plain) or resp.status_code >= 400:
            return CEPResult(CEPStatus.NOT_FOUND, message or f"HTTP {resp.status_code}")

        # The CEP's data first: it's what the pipeline compares with the receipt. Not
        # getting it doesn't stop the PDF download; the result just has no record.
        xml, record = self._download_xml()
        if xml is not None and record is None and _rate_limited(xml.decode("utf-8", "replace")):
            return CEPResult(CEPStatus.RATE_LIMITED, RATE_LIMIT_MESSAGE)
        stem = f"CEP_{fecha}_{_safe_filename(clave)}"
        if cep_files is CEPFiles.XML and xml is not None and record is not None:
            # Only the XML wanted, and it's a real CEP XML: no need for the PDF at all.
            self.output_dir.mkdir(parents=True, exist_ok=True)
            xml_path = self.output_dir / f"{stem}.xml"
            xml_path.write_bytes(xml)
            return CEPResult(CEPStatus.FOUND, "CEP downloaded", xml_path=xml_path, record=record)

        try:
            pdf = self.session.get(
                self.base_url + "descarga.do", params={"formato": "PDF"}, timeout=self.timeout
            )
        except requests.RequestException as e:
            return CEPResult(CEPStatus.ERROR, f"CEP download failed: {e}")

        if pdf.status_code != 200 or not pdf.content.startswith(b"%PDF"):
            if _rate_limited(pdf.text or ""):
                return CEPResult(CEPStatus.RATE_LIMITED, RATE_LIMIT_MESSAGE)
            return CEPResult(CEPStatus.NOT_FOUND, message or "Banxico returned no CEP for this data")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        if cep_files is CEPFiles.ZIP:
            # Built here from what was already downloaded, rather than asking Banxico for
            # its own ZIP: that would cost one more of its limited lookups per receipt.
            # The XML goes in only if it's a real CEP XML, never an error page.
            zip_path = self.output_dir / f"{stem}.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(f"{stem}.pdf", pdf.content)
                if xml is not None and record is not None:
                    archive.writestr(f"{stem}.xml", xml)
            return CEPResult(CEPStatus.FOUND, "CEP downloaded", zip_path=zip_path, record=record)

        # PDF, or XML wanted but Banxico's XML couldn't be read: the PDF keeps the proof.
        pdf_path = self.output_dir / f"{stem}.pdf"
        pdf_path.write_bytes(pdf.content)
        return CEPResult(CEPStatus.FOUND, "CEP downloaded", pdf_path=pdf_path, record=record)

    def _download_xml(self) -> tuple[bytes | None, CEPRecord | None]:
        """The CEP XML of the session's lookup and its data. Never raises: (None, None)
        if it can't be downloaded, (content, None) if it isn't a CEP XML."""
        try:
            resp = self.session.get(
                self.base_url + "descarga.do", params={"formato": "XML"}, timeout=self.timeout
            )
        except requests.RequestException as e:
            logger.warning("CEP XML download failed: %s", e)
            return None, None
        if resp.status_code != 200:
            return None, None
        try:
            return resp.content, parse_cep_xml(resp.content)
        except ValueError as e:
            logger.warning("Couldn't read the CEP XML: %s", e)
            return resp.content, None
