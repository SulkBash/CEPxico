"""User settings, kept between runs in %APPDATA%\\CEPxico\\settings.json.

Shared by the desktop app (Settings button) and the command line. A missing or
damaged file means default settings: the app must start whatever is on disk.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from cepxico.banxico import CEPFiles
from cepxico.extraction.parser import clean_field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    # What to save for each CEP: the PDF, the PDF and its XML (Banxico's digitally
    # signed data), or both in one ZIP.
    cep_files: CEPFiles = CEPFiles.PDF
    # Only accept receipts paid to one of `own_accounts`; others are reported for review
    # without asking Banxico.
    check_own_accounts: bool = False
    own_accounts: tuple[str, ...] = ()  # CLABE, debit card or phone; digits only

    @property
    def accepted_accounts(self) -> frozenset[str] | None:
        """Accounts receipts must be paid to, or None if any account is fine."""
        return frozenset(self.own_accounts) if self.check_own_accounts else None


def settings_path() -> Path:
    base = os.environ.get("APPDATA")
    return (Path(base) / "CEPxico" if base else Path.home() / ".cepxico") / "settings.json"


def parse_accounts(text: str | Iterable[str]) -> tuple[tuple[str, ...], list[str]]:
    """Accounts typed one per line (or separated by commas): (accounts, problems).
    Spaces and dashes inside an account are fine; repeats are dropped."""
    raw = re.split(r"[\n,;]+", text) if isinstance(text, str) else list(text)
    accounts: list[str] = []
    problems: list[str] = []
    for entry in (r.strip() for r in raw):
        if not entry:
            continue
        try:
            account = clean_field("beneficiary_account", entry)
        except ValueError as e:
            problems.append(f"{entry}: {e}")
            continue
        if account and account not in accounts:
            accounts.append(account)
    return tuple(accounts), problems


def load_settings(path: Path | None = None) -> Settings:
    path = path or settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError) as e:
        logger.warning("Ignoring unreadable settings file %s: %s", path, e)
        return Settings()
    if not isinstance(data, dict):
        logger.warning("Ignoring settings file %s: not a JSON object", path)
        return Settings()

    known = {f.name for f in fields(Settings)}
    values = {k: v for k, v in data.items() if k in known}
    if "check_own_accounts" in values and not isinstance(values["check_own_accounts"], bool):
        del values["check_own_accounts"]
    if "cep_files" in values:
        try:
            values["cep_files"] = CEPFiles(values["cep_files"])
        except ValueError:
            del values["cep_files"]
    if "own_accounts" in values:
        accounts = values["own_accounts"]
        valid = isinstance(accounts, list) and all(isinstance(a, str) for a in accounts)
        values["own_accounts"], problems = parse_accounts(accounts if valid else [])
        for problem in problems:
            logger.warning("Ignoring account in settings: %s", problem)
    return Settings(**values)


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Writes the settings atomically, so a crash never leaves half a file."""
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(settings)
    data["own_accounts"] = list(settings.own_accounts)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)
