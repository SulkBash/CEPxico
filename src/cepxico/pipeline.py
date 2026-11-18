"""Processing receipts end to end: extract fields, identify the banks, look up the CEP.

Shared by the CLI and the GUI so both behave identically.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
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
    SPIDClient,
)
from cepxico.extraction import extract_payment
from cepxico.history import Check, History, TransferKey, file_hash
from cepxico.i18n import tr
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
SPID_URL = "https://www.banxico.org.mx/cep-spid/"


def closed_message() -> str:
    return tr("Banxico only answers 09:30–23:00 (Mexico City); check then")


def blocked_message() -> str:
    return tr("Not checked: Banxico stopped answering; try again later")


def spid_message() -> str:
    """For a dollar receipt when nobody is there to type Banxico's security image."""
    return tr(
        "Dollar transfer (SPID): needs a security code; check it in the desktop app or at {url}",
        url=SPID_URL,
    )


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


class SPIDCEPClient(CEPClient, Protocol):
    """What the pipeline needs from SPIDClient: a CEP client whose lookups need a
    security code typed from an image."""

    def security_image(self) -> bytes: ...

    def new_image(self) -> bytes: ...


# How many security codes a person may type for one receipt before it's reported.
MAX_CODE_ATTEMPTS = 3


@dataclass(frozen=True)
class CodeRequest:
    """Asks a person to type the code in Banxico's security image for one receipt."""

    image: bytes  # PNG/JPEG as Banxico sent it
    file_name: str
    amount: str
    tracking_key: str
    attempt: int  # 1 for the first image; more after Banxico didn't accept a code
    new_image: Callable[[], bytes]  # another image for the same lookup; raises BanxicoError

    @property
    def retry(self) -> bool:
        return self.attempt > 1


# Shows the image and returns what the person typed, or None if they skipped it.
AskCode = Callable[[CodeRequest], "str | None"]


@dataclass
class SPIDLookup:
    """What a dollar receipt's check needs: Banxico's CEP-SPID client and a person to
    type its security images. `lock` puts one image at a time in front of the person,
    shared by every worker of a batch."""

    client: SPIDCEPClient
    ask_code: AskCode
    lock: threading.Lock = field(default_factory=threading.Lock)


class Outcome(Enum):
    SUCCESS = "success"  # CEP found, saved and matching the receipt: the transfer is real
    NOT_FOUND = "not_found"  # Banxico has no such transfer: check the data, receipt may be fake
    # A real payment that isn't a clean confirmation: paid to an account that isn't
    # yours, a CEP that doesn't match the receipt, a payment without CEP (pending,
    # cancelled, returned), or a transfer already confirmed for another receipt. The
    # message says which.
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
        problems.append(f"{tr('clave de rastreo')} {record.tracking_key}")
    if payment.amount and Decimal(record.amount) != Decimal(payment.amount):
        problems.append(f"{tr('amount')} {record.amount}")
    # The account Banxico was given: the beneficiary's, or the sender's for a pago a
    # banco. Compared only when both are the same kind (a card payment's CEP may show
    # the account behind the card).
    cep_account = record.sender.account if payment.pago_a_banco else record.beneficiary.account
    account = payment.beneficiary_account or ""
    if cep_account and len(cep_account) == len(account) and cep_account != account:
        problems.append(f"{payment.label('beneficiary_account')} {_mask(cep_account)}")
    return problems


def reused_message(earlier: Check, *, checked: bool) -> str:
    """For a transfer Banxico already confirmed for another receipt file."""
    values = {"date": earlier.checked_at_text, "file": earlier.file_name}
    if checked:
        return tr("Already used: confirmed on {date} for {file}", **values)
    return tr(
        "Already used: confirmed on {date} for {file} (not checked again)",
        **values,
    )


def transfer_key(result: FileResult) -> TransferKey | None:
    payment, sender = result.payment, result.sender
    if not (payment and sender and payment.tracking_key and payment.payment_date):
        return None
    return TransferKey(payment.tracking_key.upper(), payment.payment_date, sender.bank.code)


def check_from_result(
    result: FileResult, receipt_hash: str | None = None, when: datetime | None = None
) -> Check:
    """The history entry for a result."""
    payment, cep = result.payment, result.cep
    record = cep.record if cep else None
    return Check(
        checked_at=(when or datetime.now().astimezone()).isoformat(timespec="seconds"),
        file_name=result.path.name,
        file_path=str(result.path.resolve()),
        file_hash=file_hash(result.path) if receipt_hash is None else receipt_hash,
        outcome=result.outcome.value,
        message=result.message,
        payment_date=(payment.payment_date or "") if payment else "",
        tracking_key=(payment.tracking_key or "") if payment else "",
        sender_code=result.sender.bank.code if result.sender else "",
        sender_bank=result.sender.bank.name if result.sender else "",
        receiver_bank=result.receiver.bank.name if result.receiver else "",
        account=(payment.beneficiary_account or "") if payment else "",
        amount=(payment.amount or "") if payment else "",
        sender_name=record.sender.name if record else "",
        beneficiary_name=record.beneficiary.name if record else "",
        cep_file=str(cep.saved_path) if cep and cep.saved_path else "",
        edited=bool(payment and payment.edited_fields),
    )


def process_file(
    path: Path | str,
    client: CEPClient,
    on_step: Callable[[str], None] | None = None,
    payment: PaymentData | None = None,
    settings: Settings | None = None,
    history: History | None = None,
    spid: SPIDLookup | None = None,
) -> FileResult:
    """Processes one receipt. Never raises: every problem becomes a FAILED result.

    `payment` is data already read from the file, possibly corrected by the user (see
    extraction.correct_payment); the file isn't read again when it's given.
    With a `history`, the check is recorded there, and a transfer Banxico already
    confirmed for another receipt file is reported for review (see history.py).
    Dollar (SPID) receipts are checked with `spid`; without it they fail with a link."""
    path = Path(path)
    step = on_step or (lambda _msg: None)
    receipt_hash = file_hash(path) if history else ""
    try:
        result = _process(path, client, step, payment, settings or Settings(), history, receipt_hash, spid)
    except Exception as e:  # keep a batch going whatever happens to one file
        logger.exception("Unexpected error processing %s", path.name)
        result = FileResult(path, Outcome.FAILED, tr("Unexpected error: {error}", error=e), payment)
    if history is None:
        return result
    try:
        return _record(history, result, receipt_hash)
    except Exception:  # the check itself is done; a broken history mustn't hide it
        logger.exception("Couldn't record %s in the history", path.name)
        return result


def _record(history: History, result: FileResult, receipt_hash: str) -> FileResult:
    """Records the result. A confirmation of a transfer already confirmed for another
    receipt becomes a review; the lookup and the record are atomic, so two receipts of
    one transfer checked at the same time can't both pass."""
    with history.transaction():
        key = transfer_key(result)
        if (
            result.outcome is Outcome.SUCCESS
            and key
            and (earlier := history.earlier_use(key, str(result.path.resolve()), receipt_hash))
        ):
            result = replace(result, outcome=Outcome.REVIEW, message=reused_message(earlier, checked=True))
        history.add(check_from_result(result, receipt_hash))
    return result


def _process(
    path: Path,
    client: CEPClient,
    step: Callable[[str], None],
    payment: PaymentData | None,
    settings: Settings,
    history: History | None,
    receipt_hash: str,
    spid: SPIDLookup | None = None,
) -> FileResult:
    if not path.is_file():
        return FileResult(path, Outcome.FAILED, tr("File not found"), payment)

    if payment is None:
        step(tr("Reading"))
        payment = extract_payment(path)
    if payment.spid:
        # A different Banxico service; the SPEI one would answer "not found" and make a
        # real dollar transfer look fake.
        if spid is None:
            return FileResult(path, Outcome.FAILED, spid_message(), payment)
        client = spid.client
    missing = payment.missing_fields()
    if missing:
        reason = payment.error_reason or tr("Missing {field}", field=payment.label(missing[0]))
        return FileResult(path, Outcome.FAILED, reason, payment)
    # Guaranteed by missing_fields(); narrows the types for the checker.
    assert payment.payment_date and payment.tracking_key and payment.beneficiary_account and payment.amount

    step(tr("Identifying banks"))
    try:
        directory = BankDirectory(client.get_catalog(payment.payment_date))
    except BanxicoError as e:
        return FileResult(path, Outcome.FAILED, str(e), payment)

    receiver = identify_receiver(payment, directory)
    if not receiver:
        return FileResult(
            path,
            Outcome.FAILED,
            tr("Receiving bank '{bank}' not in Banxico's list", bank=payment.receiver_bank),
            payment,
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
            tr("Sending bank '{bank}' not in Banxico's list", bank=payment.sender_bank),
            payment,
            receiver=receiver,
        )
    sender = identify_sender(payment, directory, receiver=receiver.bank)
    if not sender:
        return FileResult(
            path, Outcome.FAILED, tr("Couldn't identify the sending bank"), payment, receiver=receiver
        )
    logger.info("%s: sender %s, receiver %s", path.name, sender, receiver)
    if sender.bank == receiver.bank:
        # SPEI moves money between two different banks, so no CEP can exist. Either the
        # receipt isn't a SPEI transfer or a field was misread; don't report it as fake.
        return FileResult(
            path,
            Outcome.FAILED,
            tr(
                "Both banks read as {bank}; check the fields",
                bank=sender.bank.name,
            ),
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
            message = tr(
                "Paid to {bank} itself (pago a banco), not to your accounts", bank=receiver.bank.name
            )
            return done(Outcome.REVIEW, message)
        if payment.beneficiary_account not in accepted:
            return done(
                Outcome.REVIEW,
                tr(
                    "Paid to {account}, not one of your accounts",
                    account=_mask(payment.beneficiary_account),
                ),
            )

    if history is not None:
        # Saves one of Banxico's limited lookups; _record checks again atomically.
        key = TransferKey(payment.tracking_key.upper(), payment.payment_date, sender.bank.code)
        try:
            earlier = history.earlier_use(key, str(path.resolve()), receipt_hash)
        except Exception:  # an unreadable history mustn't stop the check itself
            logger.exception("Couldn't read the history for %s", path.name)
            earlier = None
        if earlier:
            return done(Outcome.REVIEW, reused_message(earlier, checked=False))

    query = {
        "fecha": payment.payment_date,
        "clave_rastreo": payment.tracking_key,
        "sender": sender.bank,
        "receiver": receiver.bank,
        "account": payment.beneficiary_account,
        "amount": payment.amount,
        "pago_a_banco": payment.pago_a_banco,
        "cep_files": settings.cep_files,
    }
    if payment.spid and spid is not None:
        found = _spid_lookup(spid, query, payment, path, step)
        if found is None:
            return done(Outcome.FAILED, tr("Not checked: no code typed"))
        cep = found
    else:
        step(tr("Checking at Banxico"))
        cep = client.download_cep(**query)
    logger.info("%s: Banxico %s - %s", path.name, cep.status.value, cep.message)

    if cep.status is CEPStatus.FOUND and cep.saved_path:
        if cep.record and (problems := cep_mismatches(payment, cep.record)):
            message = tr("CEP doesn't match the receipt: it shows {problems}", problems=", ".join(problems))
            return done(Outcome.REVIEW, message, cep)
        return done(Outcome.SUCCESS, tr("CEP saved: {file}", file=cep.saved_path.name), cep)
    if cep.status is CEPStatus.NO_CEP:
        return done(Outcome.REVIEW, cep.message, cep)
    if cep.status is not CEPStatus.INPUT_ERROR and not banxico_open():
        # Outside its hours Banxico's answers say nothing about the receipt.
        return done(Outcome.FAILED, closed_message(), cep)
    if cep.status is CEPStatus.NOT_FOUND:
        return done(Outcome.NOT_FOUND, tr("Banxico: {reason}", reason=cep.message), cep)
    return done(Outcome.FAILED, cep.message, cep)


def _spid_lookup(
    spid: SPIDLookup,
    query: dict,
    payment: PaymentData,
    path: Path,
    step: Callable[[str], None],
) -> CEPResult | None:
    """Looks up a dollar transfer, asking for the security code of each image shown.
    None if the person skipped it. Each image is fetched right before it's shown, so
    it's never stale while the person is busy with another receipt's image."""
    step(tr("Waiting for the security code"))
    with spid.lock:
        for attempt in range(1, MAX_CODE_ATTEMPTS + 1):
            try:
                image = spid.client.security_image()
            except BanxicoError as e:
                return CEPResult(CEPStatus.ERROR, str(e))
            code = spid.ask_code(
                CodeRequest(
                    image=image,
                    file_name=path.name,
                    amount=payment.amount or "",
                    tracking_key=payment.tracking_key or "",
                    attempt=attempt,
                    new_image=spid.client.new_image,
                )
            )
            if not code or not code.strip():
                return None
            step(tr("Checking at Banxico"))
            cep = spid.client.download_cep(**query, captcha=code.strip())
            if cep.status is not CEPStatus.WRONG_CODE:
                return cep
    return CEPResult(
        CEPStatus.INPUT_ERROR,
        tr(
            "Code rejected {count} times; check the fields and try again",
            count=MAX_CODE_ATTEMPTS,
        ),
    )


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
    history: History | None = None,
    ask_code: AskCode | None = None,
    spid_client_factory: Callable[[CatalogCache], SPIDCEPClient] | None = None,
) -> list[FileResult | None]:
    """Processes receipts `jobs` at a time and returns their results in input order.

    `payments` maps paths (as given) to data to use instead of reading those files,
    such as fields the user corrected.
    Once `cancel` is set, files not yet started are skipped (None in the results);
    files in progress finish. Once Banxico refuses lookups (too many of them), files not
    yet started fail without asking it again. Callbacks receive each path exactly as
    given and run on worker threads. With a `history`, every check is recorded and reused
    receipts are caught (see process_file). With `ask_code`, dollar (SPID) receipts are
    checked too, showing Banxico's security images one at a time (see SPIDLookup).
    Each worker thread gets its own Banxico clients (see BanxicoCEPClient for why
    sharing one would mix up CEPs); bank catalogs are shared.
    """
    jobs = max(1, min(jobs, MAX_JOBS, len(paths) or 1))
    blocked = threading.Event()
    catalogs = CatalogCache()
    make_client = client_factory or (lambda cache: BanxicoCEPClient(output_dir, catalogs=cache))
    spid_catalogs = CatalogCache()  # SPID has its own, shorter list of banks
    make_spid_client = spid_client_factory or (lambda cache: SPIDClient(output_dir, catalogs=cache))
    spid_lock = threading.Lock()
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

    def thread_spid() -> SPIDLookup | None:
        if ask_code is None:
            return None
        lookup = getattr(local, "spid", None)
        if lookup is None:  # creating a client doesn't contact Banxico; using it does
            lookup = local.spid = SPIDLookup(make_spid_client(spid_catalogs), ask_code, spid_lock)
            with clients_lock:
                clients.append(lookup.client)
        return lookup

    def work(path: Path | str) -> FileResult | None:
        if cancel is not None and cancel.is_set():
            return None
        step = (lambda message: on_step(path, message)) if on_step else None
        payment = payments.get(path) if payments else None
        if blocked.is_set():
            result = FileResult(Path(path), Outcome.FAILED, blocked_message(), payment)
        else:
            result = process_file(
                path,
                thread_client(),
                on_step=step,
                payment=payment,
                settings=settings,
                history=history,
                spid=thread_spid(),
            )
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
