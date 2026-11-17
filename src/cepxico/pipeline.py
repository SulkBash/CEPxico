"""Processing one receipt end to end: extract fields, identify the banks, look up the CEP.

Shared by the CLI and the GUI so both behave identically.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from cepxico.banks import BankDirectory
from cepxico.banxico import BanxicoCEPClient, BanxicoError, CEPResult, CEPStatus
from cepxico.extraction import extract_payment
from cepxico.identify import BankMatch, identify_receiver, identify_sender
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
    sender: BankMatch | None = None
    receiver: BankMatch | None = None
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
    # Guaranteed by missing_fields(); narrows the types for the checker.
    assert payment.payment_date and payment.tracking_key and payment.beneficiary_account and payment.amount

    step("Identifying banks")
    try:
        directory = BankDirectory(client.get_catalog(payment.payment_date))
    except BanxicoError as e:
        return FileResult(path, Outcome.FAILED, str(e), payment)

    receiver = identify_receiver(payment, directory)
    if not receiver:
        return FileResult(
            path, Outcome.FAILED, f"Receiving bank '{payment.receiver_bank}' not in Banxico's list", payment
        )
    sender = identify_sender(payment, directory, receiver=receiver.bank)
    if not sender:
        return FileResult(
            path, Outcome.FAILED, "Couldn't identify the sending bank", payment, receiver=receiver
        )
    logger.info("%s: sender %s, receiver %s", path.name, sender, receiver)

    def done(outcome: Outcome, message: str, cep: CEPResult) -> FileResult:
        return FileResult(path, outcome, message, payment, sender, receiver, cep)

    step("Checking at Banxico")
    cep = client.download_cep(
        fecha=payment.payment_date,
        clave_rastreo=payment.tracking_key,
        sender=sender.bank,
        receiver=receiver.bank,
        account=payment.beneficiary_account,
        amount=payment.amount,
    )
    logger.info("%s: Banxico %s - %s", path.name, cep.status.value, cep.message)

    if cep.status is CEPStatus.FOUND and cep.pdf_path:
        return done(Outcome.SUCCESS, f"CEP saved: {cep.pdf_path.name}", cep)
    if cep.status is CEPStatus.NOT_FOUND:
        return done(Outcome.NOT_FOUND, f"No CEP at Banxico: {cep.message}", cep)
    return done(Outcome.FAILED, cep.message, cep)
