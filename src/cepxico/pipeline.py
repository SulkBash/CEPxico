"""Processing receipts end to end: extract fields, identify the banks, look up the CEP.

Shared by the CLI and the GUI so both behave identically.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Protocol

from cepxico.banks import Bank, BankCatalog, BankDirectory
from cepxico.banxico import (
    BLOCKED_STATUSES,
    BanxicoCEPClient,
    BanxicoError,
    CatalogCache,
    CEPFiles,
    CEPRecord,
    CEPResult,
    CEPStatus,
)
from cepxico.extraction import extract_payment
from cepxico.identify import BankMatch, identify_receiver, identify_sender
from cepxico.models import PaymentData
from cepxico.settings import Settings

logger = logging.getLogger(__name__)

# Receipts checked at once. Most of the time per receipt is spent waiting on Banxico,
# so a few workers speed batches up a lot; more would just load Banxico's servers.
DEFAULT_JOBS = 4
MAX_JOBS = 8

# Banxico's CEP page: "El horario de consulta es de 09:30-23:00 hrs de Lunes a Domingo".
# Mexico City has had no daylight saving time since 2022, so it's UTC-6 all year.
MEXICO_CITY = timezone(timedelta(hours=-6), "Mexico City")
BANXICO_HOURS = (time(9, 30), time(23, 0))
CLOSED_MESSAGE = (
    "Banxico's CEP service only answers from 09:30 to 23:00 (Mexico City time); check this receipt then"
)
BLOCKED_MESSAGE = "Not checked: Banxico stopped answering lookups for now; try again later"


def banxico_open(now: datetime | None = None) -> bool:
    """Whether it's within the hours Banxico answers CEP lookups."""
    local = (now or datetime.now(MEXICO_CITY)).astimezone(MEXICO_CITY).time()
    return BANXICO_HOURS[0] <= local < BANXICO_HOURS[1]


class CEPClient(Protocol):
    """What the pipeline needs from BanxicoCEPClient (lets tests use a fake)."""

    def get_catalog(self, fecha: str) -> BankCatalog: ...

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
    ) -> CEPResult: ...

    def close(self) -> None: ...


class Outcome(Enum):
    SUCCESS = "success"  # CEP found, saved and matching the receipt: the transfer is real
    NOT_FOUND = "not_found"  # Banxico has no such transfer: check the data, receipt may be fake
    # A real payment that isn't a clean confirmation: paid to an account that isn't
    # yours, a CEP that doesn't match the receipt, or a payment without CEP (pending,
    # cancelled, returned). The message says which.
    REVIEW = "review"
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


def _mask(account: str) -> str:
    return f"…{account[-4:]}"


def cep_mismatches(payment: PaymentData, record: CEPRecord) -> list[str]:
    """Where the CEP's own data contradicts the receipt. Banxico found the CEP with the
    receipt's data, so any difference means the CEP belongs to another transfer."""
    problems = []
    if record.tracking_key.upper() != (payment.tracking_key or "").upper():
        problems.append(f"clave de rastreo {record.tracking_key}")
    if payment.amount and Decimal(record.amount) != Decimal(payment.amount):
        problems.append(f"monto {record.amount}")
    # The account Banxico was given: the beneficiary's, or the sender's for a pago a
    # banco. Compared only when both are the same kind (a card payment's CEP may show
    # the account behind the card).
    cep_account = record.sender.account if payment.pago_a_banco else record.beneficiary.account
    account = payment.beneficiary_account or ""
    if cep_account and len(cep_account) == len(account) and cep_account != account:
        problems.append(f"{payment.label('beneficiary_account')} {_mask(cep_account)}")
    return problems


def process_file(
    path: Path | str,
    client: CEPClient,
    on_step: Callable[[str], None] | None = None,
    payment: PaymentData | None = None,
    settings: Settings | None = None,
) -> FileResult:
    """Processes one receipt. Never raises: every problem becomes a FAILED result.

    `payment` is data already read from the file, possibly corrected by the user (see
    extraction.correct_payment); the file isn't read again when it's given."""
    path = Path(path)
    step = on_step or (lambda _msg: None)
    try:
        return _process(path, client, step, payment, settings or Settings())
    except Exception as e:  # keep a batch going whatever happens to one file
        logger.exception("Unexpected error processing %s", path.name)
        return FileResult(path, Outcome.FAILED, f"Unexpected error: {e}", payment)


def _process(
    path: Path,
    client: CEPClient,
    step: Callable[[str], None],
    payment: PaymentData | None,
    settings: Settings,
) -> FileResult:
    if not path.is_file():
        return FileResult(path, Outcome.FAILED, "File not found", payment)

    if payment is None:
        step("Extracting")
        payment = extract_payment(path)
    missing = payment.missing_fields()
    if missing:
        reason = payment.error_reason or f"Missing {payment.label(missing[0])}"
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
    if (
        "sender_bank" in payment.edited_fields
        and payment.sender_bank
        and not directory.resolve(payment.sender_bank)
    ):
        # Typed by the user: report it rather than fall back to guessing from the receipt.
        return FileResult(
            path,
            Outcome.FAILED,
            f"Sending bank '{payment.sender_bank}' not in Banxico's list",
            payment,
            receiver=receiver,
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

    def done(outcome: Outcome, message: str, cep: CEPResult | None = None) -> FileResult:
        return FileResult(path, outcome, message, payment, sender, receiver, cep)

    accepted = settings.accepted_accounts
    if accepted is not None:
        # Checked before asking Banxico: a payment to someone else's account is no
        # payment to you, real or not, and it saves one of Banxico's limited lookups.
        if payment.pago_a_banco:
            message = f"Paid to {receiver.bank.name} itself (pago a banco), not to one of your accounts"
            return done(Outcome.REVIEW, message)
        if payment.beneficiary_account not in accepted:
            return done(
                Outcome.REVIEW,
                f"Paid to account {_mask(payment.beneficiary_account)}, which isn't one of your "
                "accounts (Settings); not checked at Banxico",
            )

    step("Checking at Banxico")
    cep = client.download_cep(
        fecha=payment.payment_date,
        clave_rastreo=payment.tracking_key,
        sender=sender.bank,
        receiver=receiver.bank,
        account=payment.beneficiary_account,
        amount=payment.amount,
        pago_a_banco=payment.pago_a_banco,
        cep_files=settings.cep_files,
    )
    logger.info("%s: Banxico %s - %s", path.name, cep.status.value, cep.message)

    if cep.status is CEPStatus.FOUND and cep.saved_path:
        if cep.record and (problems := cep_mismatches(payment, cep.record)):
            return done(Outcome.REVIEW, f"CEP doesn't match the receipt: it shows {', '.join(problems)}", cep)
        return done(Outcome.SUCCESS, f"CEP saved: {cep.saved_path.name}", cep)
    if cep.status is CEPStatus.NO_CEP:
        return done(Outcome.REVIEW, cep.message, cep)
    if cep.status is not CEPStatus.INPUT_ERROR and not banxico_open():
        # Outside its hours Banxico's answers say nothing about the receipt.
        return done(Outcome.FAILED, CLOSED_MESSAGE, cep)
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
    payments: Mapping[Path | str, PaymentData] | None = None,
    settings: Settings | None = None,
) -> list[FileResult | None]:
    """Processes receipts `jobs` at a time and returns their results in input order.

    `payments` maps paths (as given) to data to use instead of reading those files,
    such as fields the user corrected.
    Once `cancel` is set, files not yet started are skipped (None in the results);
    files in progress finish. Once Banxico refuses lookups (too many of them), files not
    yet started fail without asking it again. Callbacks receive each path exactly as
    given and run on worker threads. Each worker thread gets its own Banxico client
    (see BanxicoCEPClient for why sharing one would mix up CEPs); bank catalogs are shared.
    """
    jobs = max(1, min(jobs, MAX_JOBS, len(paths) or 1))
    blocked = threading.Event()
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
        payment = payments.get(path) if payments else None
        if blocked.is_set():
            result = FileResult(Path(path), Outcome.FAILED, BLOCKED_MESSAGE, payment)
        else:
            result = process_file(path, thread_client(), on_step=step, payment=payment, settings=settings)
            if result.cep and result.cep.status in BLOCKED_STATUSES:
                blocked.set()
        if on_done:
            on_done(path, result)
        return result

    try:
        with ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="cepxico") as pool:
            return list(pool.map(work, paths))
    finally:
        for client in clients:
            client.close()
