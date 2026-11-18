"""Command-line entry point. With no files, opens the desktop app."""

from __future__ import annotations

import argparse
import contextlib
import glob
import io
import logging
import logging.handlers
import re
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from cepxico import __version__
from cepxico.banxico import BanxicoError, CEPFiles
from cepxico.config import DEFAULT_CEP_DIR, app_data_dir, open_path
from cepxico.extraction import SUPPORTED_EXTENSIONS
from cepxico.history import History, history_path, write_csv
from cepxico.i18n import set_language, tr
from cepxico.pipeline import (
    DEFAULT_JOBS,
    MAX_CODE_ATTEMPTS,
    MAX_JOBS,
    AskCode,
    CodeRequest,
    FileResult,
    Outcome,
    check_from_result,
    process_files,
)
from cepxico.settings import load_settings, settings_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cepxico",
        description=tr(
            "Check SPEI receipts with Banxico and download their CEPs. Without files, opens the desktop app."
        ),
        epilog=tr(
            "Uses the desktop app's settings ({settings}) and history ({history}).",
            settings=settings_path(),
            history=history_path(),
        ),
    )
    parser.add_argument(
        "files", nargs="*", type=Path, help=tr("receipt PDF/image files, wildcards (*.pdf) or folders")
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_CEP_DIR,
        help=tr("folder for downloaded CEPs (default: {folder})", folder=DEFAULT_CEP_DIR),
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=_jobs,
        default=DEFAULT_JOBS,
        help=tr(
            "receipts to check at once, 1-{max} (default: {default})", max=MAX_JOBS, default=DEFAULT_JOBS
        ),
    )
    parser.add_argument(
        "--save",
        choices=[f.value for f in CEPFiles],
        help=tr("CEP files to save (default: as in Settings)"),
    )
    parser.add_argument("--csv", type=Path, metavar="FILE", help=tr("also save this run's results as CSV"))
    parser.add_argument(
        "--export-history",
        type=Path,
        metavar="FILE",
        help=tr("save the whole history as CSV and exit"),
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help=tr("don't use or update the history (no used-twice check)"),
    )
    parser.add_argument("--lang", choices=["es", "en"], help=tr("message language (default: as in Settings)"))
    parser.add_argument("-v", "--verbose", action="store_true", help=tr("show debug output"))
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _jobs(value: str) -> int:
    try:
        jobs = int(value)
    except ValueError:
        jobs = 0
    if not 1 <= jobs <= MAX_JOBS:
        raise argparse.ArgumentTypeError(tr("must be a whole number from 1 to {max}", max=MAX_JOBS))
    return jobs


def expand_paths(args: Sequence[Path]) -> list[Path]:
    """Expands wildcards and folders, keeping order and dropping repeats.

    Windows shells pass `*.pdf` to the program literally (unlike bash), so without this
    `cepxico *.pdf` would report a missing file named "*.pdf". A folder means every
    receipt directly inside it. A pattern matching nothing is kept, to be reported."""
    paths: list[Path] = []
    for arg in args:
        if arg.is_dir():
            paths += sorted(
                p for p in arg.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
            )
        elif not arg.exists() and any(ch in str(arg) for ch in "*?["):
            paths += sorted(Path(m) for m in glob.glob(str(arg)) if Path(m).is_file()) or [arg]
        else:
            paths.append(arg)
    seen: set[Path] = set()
    unique = []
    for path in paths:
        key = path.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _save_image(data: bytes) -> Path:
    """Banxico's security image as a PNG file the system's viewer can open."""
    from PIL import Image

    with tempfile.NamedTemporaryFile(prefix="cepxico_codigo_", suffix=".png", delete=False) as f:
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.save(f, "PNG")
        except Exception:  # not an image Pillow knows: hand the viewer the bytes as they came
            f.write(data)
    return Path(f.name)


def terminal_ask_code(request: CodeRequest) -> str | None:
    """Shows Banxico's security image in the system's image viewer and reads the code
    from the terminal. "?" asks for another image; Enter alone skips the receipt."""
    image = request.image
    print()
    print(
        tr(
            "{file}: dollar transfer (SPID) of {amount}; Banxico asks for a security code.",
            file=request.file_name,
            amount=request.amount,
        )
    )
    if request.retry:
        print(
            tr(
                "Wrong code. New image ({attempt} of {max}).",
                attempt=request.attempt,
                max=MAX_CODE_ATTEMPTS,
            )
        )
    while True:
        path = _save_image(image)
        try:
            open_path(path)
            print(tr("Image opened: {path}", path=path))
        except OSError:
            print(tr("Code image: {path}", path=path))
        try:
            code = input(tr("Code (? for another image, Enter to skip): ")).strip()
        except EOFError:
            code = ""
        finally:
            with contextlib.suppress(OSError):  # the viewer may still have it open
                path.unlink()
        if code != "?":
            return code or None
        try:
            image = request.new_image()
        except BanxicoError as e:
            print(e)


def interactive_ask_code() -> AskCode | None:
    """Asks for security codes only when a person is at the terminal; a script or a
    scheduled task gets dollar receipts reported instead of a prompt nobody answers."""
    return terminal_ask_code if sys.stdin.isatty() and sys.stdout.isatty() else None


LOG_FILE = "cepxico.log"
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

# Accounts, cards and phones (10+ digits), and claves de rastreo (16-30 letters and
# digits, with at least one of each, or 16+ digits).
_LONG_NUMBER = re.compile(r"\d{10,}")
_CLAVE = re.compile(r"\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{16,30}\b")


def mask(text: str) -> str:
    """`text` with account numbers and claves de rastreo cut to their last 4 characters,
    so a log can be attached to a public bug report."""
    text = _CLAVE.sub(lambda m: "…" + m.group()[-4:], text)
    return _LONG_NUMBER.sub(lambda m: "…" + m.group()[-4:], text)


class MaskingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return mask(super().format(record))


def log_file_handler(path: Path) -> logging.Handler:
    """The log file: about 1 MB, plus two older ones, with accounts and claves masked."""
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(MaskingFormatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
    return handler


def configure_logging(verbose: bool) -> None:
    """Logs to the console and to cepxico.log in the data folder. The desktop app has
    no console, so the file is what a bug report can include."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt="%H:%M:%S")
    root = logging.getLogger()
    if not any(getattr(h, "cepxico_log", False) for h in root.handlers):
        try:
            app_data_dir().mkdir(parents=True, exist_ok=True)
            handler = log_file_handler(app_data_dir() / LOG_FILE)
        except OSError as e:  # a read-only data folder mustn't stop the app
            logging.getLogger(__name__).warning("No log file: %s", e)
        else:
            handler.cepxico_log = True  # type: ignore[attr-defined]
            handler.setLevel(level)
            root.addHandler(handler)
    # Third-party libraries are chatty at INFO/DEBUG.
    for noisy in ("pdfminer", "urllib3", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def print_summary(results: Sequence[FileResult]) -> None:
    by_outcome = {outcome: [r for r in results if r.outcome is outcome] for outcome in Outcome}
    print(f"\n--- {tr('Summary')} ---")
    print(tr("Files: {count}", count=len(results)))
    print(tr("Confirmed: {count}", count=len(by_outcome[Outcome.SUCCESS])))
    for r in by_outcome[Outcome.SUCCESS]:
        print(f"  + {r.path.name} -> {r.cep.saved_path if r.cep else ''}")
    if by_outcome[Outcome.REVIEW]:
        print(
            tr(
                "Review: {count}",
                count=len(by_outcome[Outcome.REVIEW]),
            )
        )
        for r in by_outcome[Outcome.REVIEW]:
            print(f"  ? {r.path.name}: {r.message}")
    if by_outcome[Outcome.NOT_FOUND]:
        print(
            tr(
                "Not found (receipt may be fake): {count}",
                count=len(by_outcome[Outcome.NOT_FOUND]),
            )
        )
        for r in by_outcome[Outcome.NOT_FOUND]:
            print(f"  ! {r.path.name}: {r.message}")
    if by_outcome[Outcome.FAILED]:
        print(tr("Errors or not checked: {count}", count=len(by_outcome[Outcome.FAILED])))
        for r in by_outcome[Outcome.FAILED]:
            print(f"  - {r.path.name}: {r.message}")


def main(argv: Sequence[str] | None = None) -> int:
    """Returns 0 if every receipt's CEP was found, 1 otherwise."""
    settings = load_settings()
    set_language(settings.language)
    args = build_parser().parse_args(argv)
    if args.lang:
        set_language(args.lang)
    configure_logging(args.verbose)

    if args.export_history:
        checks = History().checks()
        write_csv(args.export_history, checks)
        print(tr("Wrote {count} checks to {file}", count=len(checks), file=args.export_history))
        return 0

    if not args.files:
        from cepxico.gui import run

        run(cep_dir=args.out)
        return 0

    if args.save:
        settings = replace(settings, cep_files=CEPFiles(args.save))
    paths = expand_paths(args.files)
    history = None if args.no_history else History()
    results = [
        r
        for r in process_files(
            paths,
            args.out,
            jobs=args.jobs,
            settings=settings,
            history=history,
            ask_code=interactive_ask_code(),
        )
        if r is not None
    ]

    print_summary(results)
    if args.csv:
        write_csv(args.csv, [check_from_result(r) for r in results])
        print(tr("Results written to {file}", file=args.csv))
    return 0 if all(r.outcome is Outcome.SUCCESS for r in results) else 1
