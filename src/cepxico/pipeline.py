"""Processing receipts end to end: extract fields, identify the banks, look up the CEP.

Shared by the CLI and the GUI so both behave identically.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from cepxico.banks import Bank, BankCatalog, BankDirectory
from cepxico.banxico import BanxicoCEPClient, BanxicoError, CatalogCache, CEPResult, CEPStatus
from cepxico.extraction import extract_payment
from cepxico.identify import BankMatch, identify_receiver, identify_sender
from cepxico.models import FIELD_LABELS, PaymentData

logger = logging.getLogger(__name__)

# Receipts checked at once. Most of the time per receipt is spent waiting on Banxico,
# so a few workers speed batches up a lot; more would just load Banxico's servers.
DEFAULT_JOBS = 4
MAX_JOBS = 8


class CEPClient(Protocol):
    """What the pipeline needs from BanxicoCEPClient (lets tests use a fake)."""

    def get_catalog(self, fecha: str) -> BankCatalog: ...

    def download_cep(
        self, *, fecha: str, clave_rastreo: str, sender: Bank, receiver: Bank, account: str, amount: str
    ) -> CEPResult: ...

    def close(self) -> None: ...


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
    client: CEPClient,
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


def _process(path: Path, client: CEPClient, step: Callable[[str], None]) -> FileResult:
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
    if sender.bank == receiver.bank:
        # SPEI moves money between two different banks, so no CEP can exist. Either the
        # receipt isn't a SPEI transfer or a field was misread; don't report it as fake.
        return FileResult(
            path,
            Outcome.FAILED,
            f"Sending and receiving bank are both {sender.bank.name}; check the extracted fields",
            payment,
            sender,
            receiver,
        )

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


def process_files(
    paths: Sequence[Path | str],
    output_dir: Path | str,
    *,
    jobs: int = DEFAULT_JOBS,
    on_step: Callable[[Path | str, str], None] | None = None,
    on_done: Callable[[Path | str, FileResult], None] | None = None,
    cancel: threading.Event | None = None,
    client_factory: Callable[[CatalogCache], CEPClient] | None = None,
) -> list[FileResult | None]:
    """Processes receipts `jobs` at a time and returns their results in input order.

    Once `cancel` is set, files not yet started are skipped (None in the results);
    files in progress finish. Callbacks receive each path exactly as given and run on
    worker threads. Each worker thread gets its own Banxico session (see
    BanxicoCEPClient for why sharing one would mix up CEPs); bank catalogs are shared.
    """
    jobs = max(1, min(jobs, MAX_JOBS, len(paths) or 1))
    catalogs = CatalogCache()
    make_client = client_factory or (lambda cache: BanxicoCEPClient(output_dir, catalogs=cache))
    local = threading.local()
    clients: list[CEPClient] = []
    clients_lock = threading.Lock()

    def thread_client() -> CEPClient:
        client = getattr(local, "client", None)
        if client is None:
            client = local.client = make_client(catalogs)
            with clients_lock:
                clients.append(client)
        return client

    def work(path: Path | str) -> FileResult | None:
        if cancel is not None and cancel.is_set():
            return None
        step = (lambda message: on_step(path, message)) if on_step else None
        result = process_file(path, thread_client(), on_step=step)
        if on_done:
            on_done(path, result)
        return result

    try:
        with ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="cepxico") as pool:
            return list(pool.map(work, paths))
    finally:
        for client in clients:
            client.close()
