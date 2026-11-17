"""
Parsing SPEI payment fields out of receipt text.

Each find_* function is pure (text in, value or None out) so it can be unit-tested
with plain strings. The patterns are heuristics built from real receipts of several
banks; when adding a bank, add a test in tests/test_parser.py with its wording.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from cepxico.models import FIELD_LABELS, PaymentData

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Sending bank
# ------------------------------------------------------------------------------

# Checked in order; the first one found anywhere in the text wins.
# KNOWN ISSUE: this doesn't distinguish the sending bank from the receiving bank
# (a transfer *to* BBVA is reported as *from* BBVA). See tests/test_parser.py.
SENDER_KEYWORDS: tuple[str, ...] = (
    "BBVA", "Santander", "Afirme", "STP", "Banamex", "HSBC",
    "KUSPIT Disponibilidad de pago: Mismo día",  # wording seen on Kuspit receipts
    "ACTINVER", "AFIRME", "ARCUS FI", "ASP INTEGRA OPC", "AUTOFIN", "AZTECA", "BaBien", "BAJIO",
    "BANAMEX", "BANCO COVALTO", "BANCOMEXT", "BANCOPPEL", "BANCO S3", "BANCREA", "BANJERCITO",
    "BANKAOOL", "BANK OF AMERICA", "BANK OF CHINA", "BANOBRAS", "BANORTE", "BANREGIO", "BANSI",
    "BANXICO", "BARCLAYS", "BBASE", "BBVA MEXICO", "BMONEX", "CAJA POP MEXICA", "CAJA TELEFONIST",
    "Cartera Digital", "CB INTERCAM", "CIBANCO", "CI BOLSA", "CITI MEXICO", "CLS", "CoDi Valida",
    "COMPARTAMOS", "CONSUBANCO", "CREDICAPITAL", "CREDICLUB", "CRISTOBAL COLON", "Cuenca", "DONDE",
    "FINAMEX", "FINCOMUN", "FINCO PAY", "FOMPED", "FONDEADORA", "FONDO (FIRA)", "GBM",
    "HIPOTECARIA FED", "ICBC", "INBURSA", "INDEVAL", "INMOBILIARIO", "INTERCAM BANCO", "INVEX",
    "JP MORGAN", "KLAR", "KUSPIT", "LIBERTAD", "MASARI", "Mercado Pago W", "MIFEL", "MIZUHO BANK",
    "MONEXCB", "MUFG", "MULTIVA BANCO", "NAFIN", "NU MEXICO", "NVIO", "PAGATODO", "Peibo",
    "PROFUTURO", "SABADELL", "SANTANDER", "SCOTIABANK", "SHINHAN", "SPIN BY OXXO", "TESORED",
    "TRANSFER", "UALA", "UNAGRA", "VALMEX", "VALUE", "VECTOR", "VE POR MAS", "VOLKSWAGEN",
)  # fmt: skip


def find_sender_bank(text: str) -> str | None:
    sender = next(
        (name for name in SENDER_KEYWORDS if re.search(re.escape(name), text, re.IGNORECASE)),
        None,
    )
    # Bank-specific signatures override the keyword scan.
    if re.search(r"BANCO MERCANTIL DEL NORTE", text, re.IGNORECASE):
        sender = "Banorte"
    elif re.search(r"Comprobante de Operación", text, re.IGNORECASE):
        sender = "Santander"  # KNOWN ISSUE: other banks use this wording too
    return sender


# ------------------------------------------------------------------------------
# Payment date
# ------------------------------------------------------------------------------

DATE_PATTERNS = (
    r"Fecha Aplicación[:\s]*(\d{1,2}/\d{1,2}/\d{4})",
    r"Fecha de Ejecución[:\s]*(\d{1,2}/\d{1,2}/\d{4})",
    r"Fecha de aplicación[:\s]*(\d{1,2}/\d{1,2}/\d{4})",
    r"Fecha y Hora Operación[:\s]*(\d{4}-\d{2}-\d{2})",
    r"Fecha y Hora de Captura[:\s]*(\d{1,2}/\d{1,2}/\d{4})",
    r"Fecha de creación[:\s]*(\d{1,2}/\d{1,2}/\d{4})",
    r"(\d{1,2}/\d{1,2}/\d{4})\b",
    r"(\d{1,2}/\d{1,2}/\d{2})\b",
    r"Operación[:\s]*(\d{4}-\d{2}-\d{2})",
)


def _parse_date(date_str: str) -> datetime:
    """Parses yyyy-mm-dd, d/m/yy or d/m/yyyy (day first, Mexican convention)."""
    if "-" in date_str:
        return datetime.strptime(date_str, "%Y-%m-%d")
    day, month, year = date_str.split("/")
    year_format = "%y" if len(year) == 2 else "%Y"
    return datetime.strptime(f"{day.zfill(2)}/{month.zfill(2)}/{year}", f"%d/%m/{year_format}")


def find_payment_date(text: str) -> str | None:
    """Payment date as dd-mm-yyyy."""
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            try:
                return _parse_date(match.group(1)).strftime("%d-%m-%Y")
            except ValueError:
                continue
    return None


# ------------------------------------------------------------------------------
# Clave de rastreo
# ------------------------------------------------------------------------------

TRACKING_KEY_PATTERNS = (
    # Prefer a contiguous token right after the label, to avoid swallowing the next label.
    r"Clave\s*de\s*Rastreo[:\s]*([A-Za-z0-9\-]{16,40})",
    r"Referencia\s*Spei[:\s]*([A-Za-z0-9\-]{10,40})",
    r"Rastreo[:\s]*([A-Za-z0-9\-]{16,40})",
    r"\b(BNET[A-Za-z0-9]{12,40})\b",  # BBVA signature
)
TRACKING_KEY_MIN_LEN, TRACKING_KEY_MAX_LEN = 16, 35

# Labels that pdfplumber sometimes glues onto the end of the key.
_GLUED_LABELS = (
    "FECHAYHORADECAPTURA",
    "FECHAYHORADECAPT",
    "FOLIODEINTERNET",
    "CONCEPTODEPAGO",
    "FORMADEDEPOSITO",
    "RESULTADODELTRASPASO",
)


def _clean_tracking_key(raw: str) -> str:
    key = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    for label in _GLUED_LABELS:
        position = key.find(label)
        if position >= TRACKING_KEY_MIN_LEN:
            return key[:position]
    return key


def _plausible_key(raw: str) -> str | None:
    key = _clean_tracking_key(raw)
    return key if TRACKING_KEY_MIN_LEN <= len(key) <= TRACKING_KEY_MAX_LEN else None


def find_tracking_key(text: str, sender_bank: str | None = None) -> str | None:
    for pattern in TRACKING_KEY_PATTERNS:
        for raw in re.findall(pattern, text, re.IGNORECASE):
            if key := _plausible_key(raw):
                return key

    # Fallback: take the rest of the label's line and normalize aggressively.
    line = re.search(r"Clave\s*de\s*rastreo\s*[:\-]?\s*([^\n]+)", text, re.IGNORECASE)
    if line and (key := _plausible_key(line.group(1))):
        return key

    if sender_bank == "Afirme":  # Afirme splits the key across lines before "Folio Interbancario"
        block = re.search(r"Clave de rastreo[:\s]*([\s\S]*?)Folio Interbancario", text)
        if block and (key := _plausible_key(block.group(1))):
            return key
    return None


# ------------------------------------------------------------------------------
# Receiving bank
# ------------------------------------------------------------------------------

RECEIVER_PATTERNS = (
    r"Banco Destino[:\s]*([^\n]+)",
    r"Banco receptor\s*[:\s]*([^\n\"]+)",
    r"Banco beneficiario[:\s]*([^\n]+)",
    r"Banco\s*Participante[:\s]*([^\n]+)",
    r"Banco destino[:\s]*([^\n]+)",
)


def find_receiver_bank(text: str) -> str | None:
    for pattern in RECEIVER_PATTERNS:
        match = re.search(pattern, text)
        if match and (name := match.group(1).replace('"', "").strip()):
            return name
    return None


# ------------------------------------------------------------------------------
# Beneficiary account
# ------------------------------------------------------------------------------

ACCOUNT_PATTERNS = (
    # 18-digit CLABE first
    r"Cuenta CLABE\s*Beneficiario[:\s]*(\d{18})",
    r"Cuenta/CLABE/Celular[:\s]*(\d{18})",
    r"Cuenta\s*Beneficiaria[:\s]*(\d{18})",
    r"Cuenta de depósito[:\s]*(\d{18})",
    r"Cuenta de abono[:\s]*(\d{18})",
    # then debit card (16) / phone (10) / other
    r"Cuenta/CLABE/Celular[:\s]*(\d{10,16})",
    r"Cuenta de depósito[:\s]*(\d{10,16})",
    r"Cuenta de abono[:\s]*(\d{10,16})",
    r"CUENTA\s*BENEFICIARIA[\s:]*(\d+)",
)
MIN_ACCOUNT_DIGITS = 10


def find_beneficiary_account(text: str) -> str | None:
    for pattern in ACCOUNT_PATTERNS:
        match = re.search(pattern, text)
        if match and len(match.group(1)) >= MIN_ACCOUNT_DIGITS:
            return match.group(1)
    return None


# ------------------------------------------------------------------------------
# Amount
# ------------------------------------------------------------------------------

AMOUNT_PATTERNS = (
    r"Importe[:\s]*-?\$?([\d,]+\.\d{2})\s*MXN",
    r"Importe[:\s]*-?\$?([\d,]+\.\d{2})\s*MXP",
    r"Importe a Transferir[:\s]*\\?\$?([\d,]+\.\d{2})",
    r"Importe de transferencia[:\s]*([\d,]+\.\d{2})\s*MX[NP]",
    r"Monto[:\s]*-?\$?([\d,]+\.\d{2})",
    r"IMPORTE TOTAL\s*\$?([\d,]+\.\d{2})",
    r"Descripción:.*?Importe[:\s]*\$?([\d,]+\.\d{2})",
    r"\$?([\d,]+\.\d{2})\b",  # last resort: any number with 2 decimals
)
_BBVA_AMOUNT = r"Descripción:.*?Importe[:\s]*\$?([\d,]+\.\d{2})"


def _clean_amount(raw: str) -> str:
    return re.sub(r"[$,\\]", "", raw).strip()


def find_amount(text: str, sender_bank: str | None = None) -> str | None:
    if sender_bank == "BBVA":
        match = re.search(_BBVA_AMOUNT, text, re.DOTALL | re.IGNORECASE)
        if match:
            return _clean_amount(match.group(1))

    for pattern in AMOUNT_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            amount = _clean_amount(matches[-1])  # the last amount on a receipt is usually the total
            try:
                if float(amount) > 0:
                    return amount
            except ValueError:
                continue
    return None


# ------------------------------------------------------------------------------
# All fields
# ------------------------------------------------------------------------------


def parse_payment(text: str, source_file: str = "") -> PaymentData:
    sender = find_sender_bank(text)
    payment = PaymentData(
        source_file=source_file,
        payment_date=find_payment_date(text),
        tracking_key=find_tracking_key(text, sender),
        sender_bank=sender,
        receiver_bank=find_receiver_bank(text),
        beneficiary_account=find_beneficiary_account(text),
        amount=find_amount(text, sender),
    )

    missing = payment.missing_fields()
    if missing:
        first = "tracking_key" if "tracking_key" in missing else missing[0]
        payment.error_reason = f"Missing {FIELD_LABELS[first]}"
        logger.info("%s: missing %s", source_file, ", ".join(FIELD_LABELS[f] for f in missing))

    logger.info(
        "%s: date=%s key=%s sender=%s receiver=%s account=%s amount=%s",
        source_file,
        payment.payment_date,
        payment.tracking_key,
        payment.sender_bank,
        payment.receiver_bank,
        payment.beneficiary_account,
        payment.amount,
    )
    return payment
