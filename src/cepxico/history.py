"""Every receipt checked, kept in history.sqlite3 in the app's data folder.

Two uses:
  - Reused receipts. A transfer Banxico confirmed belongs to the receipt it was
    confirmed for. The same transfer coming back on another receipt file (a second
    customer forwarding the same screenshot, or one customer sending it again days
    later) is reported for review instead of passing as a new payment.
  - The History window and CSV export, for bookkeeping and audits.

A receipt is "the same" only if it's the same file: same path and same content. A copy
of the file under another name or folder counts as another receipt, because that's
exactly what a forwarded receipt looks like.

The history holds account numbers and names, like the CEPs themselves, and never
leaves this computer.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import astuple, dataclass, fields
from datetime import datetime
from pathlib import Path

from cepxico.config import app_data_dir
from cepxico.i18n import tr

logger = logging.getLogger(__name__)

HISTORY_FILE = "history.sqlite3"


@dataclass(frozen=True)
class TransferKey:
    """Identifies one SPEI transfer: a clave de rastreo is unique per sending bank and day."""

    tracking_key: str
    payment_date: str  # dd-mm-yyyy
    sender_code: str  # Banxico's code for the sending bank


@dataclass(frozen=True)
class Check:
    """One receipt checked: what was read, and what Banxico said."""

    checked_at: str  # ISO 8601, local time with its UTC offset
    file_name: str
    file_path: str
    file_hash: str  # SHA-256 of the receipt file, "" if it couldn't be read
    outcome: str  # pipeline.Outcome value
    message: str
    payment_date: str = ""
    tracking_key: str = ""
    sender_code: str = ""
    sender_bank: str = ""
    receiver_bank: str = ""
    account: str = ""
    amount: str = ""
    sender_name: str = ""  # from the CEP
    beneficiary_name: str = ""  # from the CEP
    cep_file: str = ""
    edited: bool = False  # checked with fields the user typed in
    id: int = 0  # row in the history; 0 until it's stored

    @property
    def checked_at_text(self) -> str:
        """When it was checked, as dd/mm/yyyy hh:mm."""
        try:
            return datetime.fromisoformat(self.checked_at).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            return self.checked_at


_COLUMNS = [f.name for f in fields(Check) if f.name != "id"]
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    {", ".join(f"{name} TEXT NOT NULL DEFAULT ''" for name in _COLUMNS if name != "edited")},
    edited INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS checks_transfer ON checks (tracking_key, payment_date, sender_code, outcome);
"""


def file_hash(path: Path | str) -> str:
    """SHA-256 of a file's content, or "" if it can't be read."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 16), b""):
                digest.update(block)
    except OSError:
        return ""
    return digest.hexdigest()


def history_path() -> Path:
    return app_data_dir() / HISTORY_FILE


class History:
    """The check history. Safe to share between threads; `transaction()` makes a
    lookup and the record that depends on it atomic for every thread using this object."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else history_path()
        self._lock = threading.RLock()
        self._ready = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if not self._ready:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            # timeout: another CEPxico window or command line may be writing too.
            with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
                if not self._ready:
                    db.executescript(_SCHEMA)
                    self._ready = True
                yield db

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Holds other threads off the history until the block ends."""
        with self._lock:
            yield

    def add(self, check: Check) -> None:
        values = [int(v) if isinstance(v, bool) else v for v in astuple(check)[: len(_COLUMNS)]]
        with self._connect() as db:
            db.execute(
                f"INSERT INTO checks ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})",
                values,
            )

    def earlier_use(self, key: TransferKey, file_path: str, file_hash: str) -> Check | None:
        """The first time Banxico confirmed this transfer for a different receipt file."""
        with self._connect() as db:
            row = db.execute(
                f"SELECT {', '.join(_COLUMNS)}, id FROM checks "
                "WHERE tracking_key = ? AND payment_date = ? AND sender_code = ? AND outcome = 'success' "
                "AND NOT (file_path = ? AND file_hash = ?) ORDER BY id LIMIT 1",
                (key.tracking_key, key.payment_date, key.sender_code, file_path, file_hash),
            ).fetchone()
        return _check(row) if row else None

    def checks(self, limit: int | None = None) -> list[Check]:
        """Checks, newest first."""
        query = f"SELECT {', '.join(_COLUMNS)}, id FROM checks ORDER BY id DESC"
        with self._connect() as db:
            rows = db.execute(query + (" LIMIT ?" if limit else ""), (limit,) if limit else ()).fetchall()
        return [_check(row) for row in rows]

    def forget(self, check: Check) -> None:
        """Deletes a check, for example a receipt wrongly taken as used twice: once
        forgotten, a confirmation no longer counts as a use of its transfer."""
        with self._connect() as db:
            db.execute("DELETE FROM checks WHERE id = ?", (check.id,))


def _check(row: Sequence[object]) -> Check:
    values = dict(zip([*_COLUMNS, "id"], row, strict=True))
    values["edited"] = bool(values["edited"])
    return Check(**values)  # type: ignore[arg-type]


def outcome_label(outcome: str) -> str:
    labels = {
        "success": tr("Success"),
        "review": tr("Review"),
        "not_found": tr("Not Found"),
        "failed": tr("Failed"),
    }
    return labels.get(outcome, outcome)


def csv_columns() -> list[tuple[str, str]]:
    """(Check field, column title) for the CSV export, in order."""
    return [
        ("checked_at_text", tr("Checked")),
        ("file_name", tr("File")),
        ("outcome", tr("Result")),
        ("message", tr("Details")),
        ("payment_date", tr("Payment date")),
        ("tracking_key", tr("Clave de rastreo")),
        ("amount", tr("Amount")),
        ("sender_bank", tr("Sending bank")),
        ("sender_name", tr("Sender")),
        ("receiver_bank", tr("Receiving bank")),
        ("beneficiary_name", tr("Beneficiary")),
        ("account", tr("Account")),
        ("cep_file", tr("CEP file")),
        ("edited", tr("Typed by user")),
        ("file_path", tr("File path")),
    ]


def write_csv(path: Path | str, checks: Sequence[Check]) -> None:
    """Writes checks as CSV. UTF-8 with a byte order mark, so Excel shows accents right;
    long numbers (accounts, claves) are written as text so Excel doesn't round them."""
    columns = csv_columns()
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(title for _, title in columns)
        for check in checks:
            row = []
            for name, _ in columns:
                value = getattr(check, name)
                if name == "outcome":
                    value = outcome_label(value)
                elif name == "edited":
                    value = tr("yes") if value else ""
                elif name in ("account", "tracking_key") and value:
                    value = f'="{value}"'  # Excel: keep as text, leading zeros included
                row.append(value)
            writer.writerow(row)
