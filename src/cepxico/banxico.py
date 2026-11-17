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
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import TracebackType

import requests

from cepxico.banks import Bank, BankCatalog

logger = logging.getLogger(__name__)

BASE_URL = "https://www.banxico.org.mx/cep/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) cep-client/2.0"
REQUEST_TIMEOUT = 90  # valida.do can take >25 s when searching historical data
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


class BanxicoCEPClient:
    """Use one instance per batch: it keeps the session cookie and caches catalogs per date."""

    def __init__(self, output_dir: Path | str, base_url: str = BASE_URL, timeout: float = REQUEST_TIMEOUT):
        self.output_dir = Path(output_dir)
        self.base_url = base_url
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": USER_AGENT, "Referer": base_url, "Accept-Language": "es-MX,es;q=0.9"}
        )
        self._catalogs: dict[str, BankCatalog] = {}
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

    def get_catalog(self, fecha: str) -> BankCatalog:
        """Banks participating in SPEI on `fecha` (dd-mm-yyyy). Raises BanxicoError."""
        if fecha not in self._catalogs:
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
            self._catalogs[fecha] = BankCatalog.from_rows(rows)
            logger.debug("Loaded %d banks for %s", len(self._catalogs[fecha]), fecha)
        return self._catalogs[fecha]

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
        if not 0 < len(clave) <= 30:
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
