"""
Direct HTTP client for Banxico's CEP service (https://www.banxico.org.mx/cep/).

Makes the same requests as the official page's JavaScript (js/cep-min.js):

  1. GET  /cep/                          -> session cookie
  2. GET  /cep/instituciones.do?fecha=   -> JSON bank catalog [[code, name], ...]
  3. POST /cep/valida.do                 -> validates the operation (HTML fragment)
  4. GET  /cep/descarga.do?formato=PDF   -> the CEP itself, same session

Banxico currently disables the security image ("overrideCaptcha": true); the page
then sends the fixed value "c", and so do we. If Banxico turns the captcha back on,
we report it instead of trying to get around it.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
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
    NOT_FOUND = "not_found"  # Banxico has no CEP for this data (possible fake receipt)
    INPUT_ERROR = "input_error"  # data invalid
    CAPTCHA = "captcha"  # Banxico is asking for the security image
    ERROR = "error"  # network/server problem; says nothing about the receipt


class BanxicoError(Exception):
    """Banxico couldn't be reached or answered unexpectedly."""


@dataclass(frozen=True)
class CEPResult:
    status: CEPStatus
    message: str
    pdf_path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.status is CEPStatus.FOUND


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"<[^>]+>", " ", text).replace("&nbsp;", " ")
    return " ".join(text.split())


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
    ) -> CEPResult:
        """Looks up a SPEI transfer and saves its CEP PDF into `output_dir`.
        `sender`/`receiver` come from this date's catalog (see identify.py)."""
        account = re.sub(r"\D", "", account or "")
        clave = re.sub(r"[^A-Za-z0-9]", "", clave_rastreo or "").upper()

        if not re.fullmatch(r"\d{2}-\d{2}-\d{4}", fecha or ""):
            return CEPResult(CEPStatus.INPUT_ERROR, f"Invalid date '{fecha}' (expected dd-mm-yyyy)")
        if not 0 < len(clave) <= MAX_CLAVE_LEN:
            return CEPResult(CEPStatus.INPUT_ERROR, f"Invalid clave de rastreo '{clave_rastreo}'")
        if not 0 < len(account) <= 18:
            return CEPResult(CEPStatus.INPUT_ERROR, f"Invalid beneficiary account '{account}'")
        try:
            amount_fmt = f"{float(str(amount).replace(',', '')):.2f}"
        except ValueError:
            return CEPResult(CEPStatus.INPUT_ERROR, f"Invalid amount '{amount}'")

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
            "receptorParticipante": "0",
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
        message = _html_to_text(body)[:300]

        if resp.status_code >= 500:
            return CEPResult(CEPStatus.ERROR, f"Banxico server error {resp.status_code}: {message}")
        if "meta:stats=ERR" in body:
            return CEPResult(CEPStatus.INPUT_ERROR, "Banxico rejected the data as incomplete or invalid")
        if re.search(r"name=['\"]varHideCaptcha['\"][^>]*value=['\"]false", body):
            return CEPResult(
                CEPStatus.CAPTCHA,
                "Banxico is asking for the security image; check this receipt on the website",
            )
        if resp.status_code >= 400:
            return CEPResult(CEPStatus.NOT_FOUND, message or f"HTTP {resp.status_code}")

        # Banxico only serves the PDF when the operation was found.
        try:
            pdf = self.session.get(
                self.base_url + "descarga.do", params={"formato": "PDF"}, timeout=self.timeout
            )
        except requests.RequestException as e:
            return CEPResult(CEPStatus.ERROR, f"CEP download failed: {e}")

        if pdf.status_code != 200 or not pdf.content.startswith(b"%PDF"):
            return CEPResult(CEPStatus.NOT_FOUND, message or "Banxico returned no CEP for this data")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = self.output_dir / f"CEP_{fecha}_{_safe_filename(clave)}.pdf"
        pdf_path.write_bytes(pdf.content)
        return CEPResult(CEPStatus.FOUND, "CEP downloaded", pdf_path=pdf_path)
