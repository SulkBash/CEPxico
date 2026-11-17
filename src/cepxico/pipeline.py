"""Processing one receipt end to end: extract fields, then look up the CEP at Banxico.

Shared by the CLI and the GUI so both behave identically.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from cepxico.banxico import BanxicoCEPClient, CEPResult, CEPStatus
from cepxico.extraction import extract_payment
from cepxico.models import FIELD_LABELS, PaymentData

logger = logging.getLogger(__name__)


class Outcome(Enum):
    SUCCESS = "success"  # CEP found and saved: the transfer is real
    NOT_FOUND = "not_found"  # Banxico has no such transfer: check the data, receipt may be fake
    FAILED = "failed"  # couldn't check (unreadable file, missing data, network...)


@dataclass(frozen=True)
class FileResult:
    path: Path
    outcome: Outcome
    message: str
    payment: PaymentData | None = None
    cep: CEPResult | None = None


def process_file(
    path: Path | str,
    client: BanxicoCEPClient,
    on_step: Callable[[str], None] | None = None,
) -> FileResult:
    """Processes one receipt. Never raises: every problem becomes a FAILED result."""
    path = Path(path)
    step = on_step or (lambda _msg: None)
    try:
        return _process(path, client, step)
    except Exception as e:  # keep a batch going whatever happens to one file
        logger.exception("Unexpected error processing %s", path.name)
        return FileResult(path, Outcome.FAILED, f"Unexpected error: {e}")


def _process(path: Path, client: BanxicoCEPClient, step: Callable[[str], None]) -> FileResult:
    if not path.is_file():
        return FileResult(path, Outcome.FAILED, "File not found")

    step("Extracting")
    payment = extract_payment(path)
    missing = payment.missing_fields()
    if missing:
        reason = payment.error_reason or f"Missing {FIELD_LABELS[missing[0]]}"
        return FileResult(path, Outcome.FAILED, reason, payment)

    step("Checking at Banxico")
    # missing_fields() guarantees these are set (receiver_bank may be None when the CLABE identifies it).
    cep = client.download_cep(
        fecha=payment.payment_date or "",
        clave_rastreo=payment.tracking_key or "",
        sender_name=payment.sender_bank,
        receiver_name=payment.receiver_bank,
        account=payment.beneficiary_account or "",
        amount=payment.amount or "",
    )
    logger.info("%s: Banxico %s - %s", path.name, cep.status.value, cep.message)

    if cep.status is CEPStatus.FOUND and cep.pdf_path:
        return FileResult(path, Outcome.SUCCESS, f"CEP saved: {cep.pdf_path.name}", payment, cep)
    if cep.status is CEPStatus.NOT_FOUND:
        return FileResult(path, Outcome.NOT_FOUND, f"No CEP at Banxico: {cep.message}", payment, cep)
    return FileResult(path, Outcome.FAILED, cep.message, payment, cep)
