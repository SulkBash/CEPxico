"""
Parsing SPEI payment fields out of receipt text.

Each find_* function is pure (text in, value or None out) so it can be unit-tested
with plain strings. The patterns are heuristics built from real receipts of several
banks; when adding a bank, add a test in tests/test_parser.py with its wording.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, InvalidOperation

from cepxico.banks import clabe_is_valid
from cepxico.models import FIELD_LABELS, PaymentData

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Bank fields (as written on the receipt; matched to Banxico's catalog in identify.py)
# ------------------------------------------------------------------------------

SENDER_PATTERNS = (
    r"Banco\s*(?:emisor|ordenante|de\s*origen|origen)[:\s]*([^\n]+)",
    r"Instituci[oó]n\s*(?:emisora|ordenante|de\s*origen)[:\s]*([^\n]+)",
    r"Banco\s*que\s*env[ií]a[:\s]*([^\n]+)",
)

RECEIVER_PATTERNS = (
    r"Banco\s*destino[:\s]*([^\n]+)",
    r"Banco\s*receptor[:\s\"]*([^\n\"]+)",  # stops at a closing quote; skips an opening one
    r"Banco\s*beneficiario[:\s]*([^\n]+)",
    r"Instituci[oó]n\s*receptora[:\s]*([^\n]+)",
    # Inherited from v1, source receipt unknown. "Participante" can name either bank, so
    # it's tried last. If it names the sender, pipeline.py rejects the same-bank pair.
    r"Banco\s*participante[:\s]*([^\n]+)",
)


def _labelled_value(text: str, patterns: tuple[str, ...], flags: int = 0) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match and (value := match.group(1).replace('"', "").strip()):
            return value
    return None


def find_sender_bank(text: str) -> str | None:
    """Text next to a sending-bank label ("Banco emisor: ..."), or None."""
    return _labelled_value(text, SENDER_PATTERNS, re.IGNORECASE)


def find_receiver_bank(text: str) -> str | None:
    """Text next to a receiving-bank label ("Banco destino: ..."), or None."""
    return _labelled_value(text, RECEIVER_PATTERNS, re.IGNORECASE)


def _mentions(text: str, bank_name: str) -> bool:
    """Layout hint: whether the receipt names a bank whose format needs special handling."""
    return re.search(rf"\b{re.escape(bank_name)}\b", text, re.IGNORECASE) is not None


# ------------------------------------------------------------------------------
# Payment date
# ------------------------------------------------------------------------------

_MONTHS = {
    **dict.fromkeys(("ene", "jan"), 1),
    "feb": 2,
    "mar": 3,
    **dict.fromkeys(("abr", "apr"), 4),
    "may": 5,
    "jun": 6,
    "jul": 7,
    **dict.fromkeys(("ago", "aug"), 8),
    "sep": 9,
    "oct": 10,
    "nov": 11,
    **dict.fromkeys(("dic", "dec"), 12),
}
_MONTH_WORD = rf"(?:{'|'.join(_MONTHS)})[a-z]*\.?"  # "nov", "Nov.", "noviembre"

# Every date form receipts use: 2026-11-05, 5/11/26, 05-11-2026, "5 de noviembre de 2026",
# "05/Nov/2026". Numeric dates are day first (Mexican convention).
DATE = (
    r"\d{4}-\d{2}-\d{2}"
    r"|(?<!\d)\d{1,2}[/-]\d{1,2}[/-](?:\d{4}|\d{2})(?!\d)"
    rf"|(?<!\d)\d{{1,2}}(?:\s*de)?[\s/-]*{_MONTH_WORD}(?:\s*de|\s*del)?[\s/-]*\d{{4}}"
)

# Labels naming the date the transfer was made, most specific first. Any date on the
# receipt is the fallback, so a print or query date at the top can only win if no
# labelled date exists.
DATE_LABELS = (
    r"Fecha\s*(?:de\s*)?aplicaci[oó]n",
    r"Fecha\s*de\s*ejecuci[oó]n",
    r"Fecha\s*y\s*hora\s*(?:de\s*)?(?:la\s*)?operaci[oó]n",
    r"Fecha\s*(?:de\s*)?(?:la\s*)?operaci[oó]n",
    r"Fecha\s*y\s*hora\s*de\s*captura",
    r"Fecha\s*de\s*creaci[oó]n",
)


def _parse_date(date_str: str) -> datetime:
    """Parses one match of DATE. Raises ValueError for impossible dates (31/02/2026)."""
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", date_str):
        year, month, day = map(int, m.groups())
    elif m := re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2}|\d{4})", date_str):
        day, month, year = map(int, m.groups())
    else:
        day = int(re.match(r"\d+", date_str).group())  # type: ignore[union-attr]
        year = int(date_str[-4:])
        word = re.search(r"[A-Za-z]{3}", date_str[2:]).group().lower()  # type: ignore[union-attr]
        if word not in _MONTHS:
            raise ValueError(f"unknown month in {date_str!r}")
        month = _MONTHS[word]
    if year < 100:
        year += 2000
    return datetime(year, month, day)


def _first_valid_date(matches: Iterable[str]) -> str | None:
    for raw in matches:
        try:
            return _parse_date(raw).strftime("%d-%m-%Y")
        except ValueError:
            continue
    return None


def find_payment_date(text: str) -> str | None:
    """Payment date as dd-mm-yyyy: a labelled date if there is one, else the first date."""
    for label in DATE_LABELS:
        # The date may follow on the same line after a weekday ("martes, 5 de ...").
        pattern = rf"{label}[^\d\n]{{0,25}}?({DATE})"
        if date := _first_valid_date(m.group(1) for m in re.finditer(pattern, text, re.IGNORECASE)):
            return date
    return _first_valid_date(m.group() for m in re.finditer(DATE, text, re.IGNORECASE))


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
# Banxico accepts at most 30 characters; anything longer has a label glued on.
TRACKING_KEY_MIN_LEN, TRACKING_KEY_MAX_LEN = 16, 30

# Labels glued onto the end of the key when the label and the key end up with no space
# between them (seen with pdfplumber, the previous PDF reader, and possible with OCR).
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


def find_tracking_key(text: str) -> str | None:
    for pattern in TRACKING_KEY_PATTERNS:
        for raw in re.findall(pattern, text, re.IGNORECASE):
            if key := _plausible_key(raw):
                return key

    # Fallback: take the rest of the label's line and normalize aggressively.
    line = re.search(r"Clave\s*de\s*rastreo\s*[:\-]?\s*([^\n]+)", text, re.IGNORECASE)
    if line and (key := _plausible_key(line.group(1))):
        return key

    if _mentions(text, "Afirme"):  # Afirme splits the key across lines before "Folio Interbancario"
        block = re.search(r"Clave de rastreo[:\s]*([\s\S]*?)Folio Interbancario", text)
        if block and (key := _plausible_key(block.group(1))):
            return key
    return None


# ------------------------------------------------------------------------------
# Beneficiary account
# ------------------------------------------------------------------------------

ACCOUNT_LABELS = (
    r"Cuenta\s*CLABE\s*(?:del\s*)?Beneficiari[oa]",
    r"Cuenta/CLABE/Celular",
    r"Cuenta\s*Beneficiari[oa]",
    r"Cuenta\s*(?:de\s*)?dep[oó]sito",
    r"Cuenta\s*(?:de\s*)?abono",
    r"Cuenta\s*(?:de\s*)?destino",
    r"CLABE\s*(?:interbancaria\s*)?(?:del\s*)?(?:beneficiari[oa]|destino)",
)
ACCOUNT_LENGTHS = (18, 16, 10)  # CLABE, debit card, phone: the account types SPEI accepts

# Digits, optionally grouped: "012180001234567899", "0121 8000 1234 5678 99", "55-1234-5678".
_DIGIT_RUN = r"(?<![\d\-])\d(?:[ \-]?\d)*"


def _accounts_in_run(run: str) -> list[str]:
    """Accounts a run of digits can start with, longest first. Groups are never split,
    so "4152 3134 5678 9012 1,500.00" (card, then amount) gives the card."""
    found, digits = [], ""
    for group in re.split(r"[ \-]", run):
        digits += group
        if len(digits) > max(ACCOUNT_LENGTHS):
            break
        if len(digits) in ACCOUNT_LENGTHS:
            found.append(digits)
    return found[::-1]


def find_beneficiary_account(text: str) -> str | None:
    """CLABE (18), debit card (16) or phone (10) of the beneficiary.

    In order: a labelled 18-digit CLABE; the only valid CLABE on the receipt (its
    control digit makes a stray 18-digit number very unlikely to qualify); a labelled
    card or phone number."""
    labelled = [
        accounts[0]
        for label in ACCOUNT_LABELS
        for m in re.finditer(rf"{label}[:\s]*({_DIGIT_RUN})", text, re.IGNORECASE)
        if (accounts := _accounts_in_run(m.group(1)))
    ]
    if clabe := next((a for a in labelled if len(a) == 18), None):
        return clabe
    clabes = {
        account
        for m in re.finditer(_DIGIT_RUN, text)
        for account in _accounts_in_run(m.group())
        if clabe_is_valid(account)
    }
    if len(clabes) == 1:
        return clabes.pop()
    return labelled[0] if labelled else None


# ------------------------------------------------------------------------------
# Amount
# ------------------------------------------------------------------------------

# "$1,500.00", "$ 1,500.00" (OCR often spaces the sign), "-$1,500.00"; whole pesos
# ("$1,500") only after a label, where they can't be a folio or a phone number.
_CURRENCY = r"-?\s*\\?\$?\s*"
_LABELLED_AMOUNT = r"(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)(?!\d|[,.]\d)"
_DECIMAL_AMOUNT = r"([\d,]+\.\d{2})\b"

AMOUNT_PATTERNS = (
    rf"Importe[:\s]*{_CURRENCY}{_LABELLED_AMOUNT}\s*MX[NP]",
    rf"Importe\s*a\s*Transferir[:\s]*{_CURRENCY}{_LABELLED_AMOUNT}",
    rf"Importe\s*de\s*(?:la\s*)?transferencia[:\s]*{_CURRENCY}{_LABELLED_AMOUNT}",
    # BBVA Net Cash scans; an "IVA del pago" amount can follow it on the page.
    rf"Importe\s*de\s*(?:la\s*)?operaci[oó]n[:\s]*{_CURRENCY}{_LABELLED_AMOUNT}",
    rf"Monto(?:\s*(?:de\s*la\s*)?(?:transferencia|operaci[oó]n|transferido|enviado))?[:\s]*{_CURRENCY}{_LABELLED_AMOUNT}",
    rf"IMPORTE\s*TOTAL[:\s]*{_CURRENCY}{_LABELLED_AMOUNT}",
    rf"Descripci[oó]n:.*?Importe[:\s]*{_CURRENCY}{_DECIMAL_AMOUNT}",
    rf"\$?\s*{_DECIMAL_AMOUNT}",  # last resort: any number with 2 decimals
)
_BBVA_AMOUNT = rf"Descripci[oó]n:.*?Importe[:\s]*{_CURRENCY}{_DECIMAL_AMOUNT}"


def _clean_amount(raw: str) -> str | None:
    """ "1,500" -> "1500.00"; None unless it's a positive amount."""
    try:
        amount = Decimal(re.sub(r"[$,\\\s]", "", raw))
    except InvalidOperation:
        return None
    return f"{amount:.2f}" if amount > 0 else None


def find_amount(text: str) -> str | None:
    if _mentions(text, "BBVA"):  # BBVA lists the amount after the description
        match = re.search(_BBVA_AMOUNT, text, re.DOTALL | re.IGNORECASE)
        if match and (amount := _clean_amount(match.group(1))):
            return amount

    for pattern in AMOUNT_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        # The last amount on a receipt is usually the total.
        if matches and (amount := _clean_amount(matches[-1])):
            return amount
    return None


# ------------------------------------------------------------------------------
# All fields
# ------------------------------------------------------------------------------


def clean_field(name: str, raw: str) -> str | None:
    """A value the user typed for field `name`, normalized like the parser's output.
    Empty means "unknown" (None). Raises ValueError with a message for the user."""
    raw = raw.strip()
    if not raw:
        return None
    if name == "payment_date":
        if not re.fullmatch(DATE, raw, re.IGNORECASE) or not (date := _first_valid_date([raw])):
            raise ValueError(f"'{raw}' isn't a valid date (day/month/year, e.g. 05/11/2026)")
        return date
    if name == "tracking_key":
        # Banxico takes letters and digits only; separators shown on receipts are dropped.
        key = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
        if not 0 < len(key) <= TRACKING_KEY_MAX_LEN:
            raise ValueError(f"must be 1 to {TRACKING_KEY_MAX_LEN} letters and digits")
        return key
    if name == "beneficiary_account":
        if re.search(r"[^\d\s-]", raw):
            raise ValueError("must contain digits only")
        digits = re.sub(r"\D", "", raw)
        if len(digits) not in ACCOUNT_LENGTHS:
            raise ValueError(f"has {len(digits)} digits; expected 18 (CLABE), 16 (debit card) or 10 (phone)")
        if len(digits) == 18 and not clabe_is_valid(digits):
            raise ValueError("isn't a valid CLABE (its last digit doesn't match); check for a typo")
        return digits
    if name == "amount":
        if not re.fullmatch(rf"{_CURRENCY}[\d,]+(?:\.\d{{1,2}})?\s*(?:MXN|MXP)?", raw, re.IGNORECASE) or not (
            amount := _clean_amount(re.sub(r"(?i)MX[NP]", "", raw))
        ):
            raise ValueError(f"'{raw}' isn't a valid amount (e.g. 1,500.00)")
        return amount
    if name in ("sender_bank", "receiver_bank"):
        return " ".join(raw.split())  # matched against Banxico's list for the date later
    raise KeyError(name)


def correct_payment(payment: PaymentData, values: Mapping[str, str]) -> tuple[PaymentData, dict[str, str]]:
    """`payment` with the fields in `values` replaced by what the user typed.

    Returns (corrected payment, {}) or, if any value is invalid, (`payment` unchanged,
    {field: problem}). Fields whose value changes are added to `edited_fields`."""
    cleaned: dict[str, str | None] = {}
    errors: dict[str, str] = {}
    for name, raw in values.items():
        try:
            cleaned[name] = clean_field(name, raw)
        except ValueError as e:
            errors[name] = str(e)
    if errors:
        return payment, errors
    edited = set(payment.edited_fields) | {n for n, v in cleaned.items() if v != getattr(payment, n)}
    corrected = replace(
        payment,
        **cleaned,
        error_reason="",  # the pipeline reports whatever is still missing
        edited_fields=tuple(f for f in FIELD_LABELS if f in edited),
    )
    return corrected, {}


def parse_payment(text: str, source_file: str = "") -> PaymentData:
    payment = PaymentData(
        source_file=source_file,
        payment_date=find_payment_date(text),
        tracking_key=find_tracking_key(text),
        sender_bank=find_sender_bank(text),
        receiver_bank=find_receiver_bank(text),
        beneficiary_account=find_beneficiary_account(text),
        amount=find_amount(text),
        text=text,
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
