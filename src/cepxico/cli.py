"""Command-line entry point. With no files, opens the desktop app."""

from __future__ import annotations

import argparse
import contextlib
import glob
import io
import logging
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from cepxico import __version__
from cepxico.banxico import BanxicoError, CEPFiles
from cepxico.config import DEFAULT_CEP_DIR, open_path
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
            "Extract SPEI transfer data from receipts and download their CEP from Banxico. "
            "Run without files to open the desktop app."
        ),
        epilog=tr(
            "Settings made in the desktop app (own accounts, files to save, language) also apply "
            "here: {settings}. Every check is recorded in {history}.",
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
        help=tr(
            "what to save for each CEP: the PDF, the XML, or both in one ZIP "
            "(default: as set in the desktop app)"
        ),
    )
    parser.add_argument(
        "--csv", type=Path, metavar="FILE", help=tr("also write this run's results to a CSV file")
    )
    parser.add_argument(
        "--export-history",
        type=Path,
        metavar="FILE",
        help=tr("write every check ever made to a CSV file, and exit"),
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help=tr(
            "don't record this run, and don't flag receipts for transfers already confirmed for "
            "another receipt"
        ),
    )
    parser.add_argument("--lang", choices=["es", "en"], help=tr("language of the messages (default: as set)"))
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
            "{file}: dollar transfer (SPID) of {amount}. Banxico's CEP-SPID service asks for the "
            "characters in a security image.",
            file=request.file_name,
            amount=request.amount,
        )
    )
    if request.retry:
        print(
            tr(
                "Banxico didn't accept the last code; this is a new image (attempt {attempt} of {max}).",
                attempt=request.attempt,
                max=MAX_CODE_ATTEMPTS,
            )
        )
    while True:
        path = _save_image(image)
        try:
            open_path(path)
            print(tr("The image is open in your image viewer: {path}", path=path))
        except OSError:
            print(tr("Open this image to see the code: {path}", path=path))
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


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Third-party libraries are chatty at INFO/DEBUG.
    for noisy in ("pdfminer", "urllib3", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def print_summary(results: Sequence[FileResult]) -> None:
    by_outcome = {outcome: [r for r in results if r.outcome is outcome] for outcome in Outcome}
    print(f"\n--- {tr('Summary')} ---")
    print(tr("Files: {count}", count=len(results)))
    print(tr("CEP found and saved: {count}", count=len(by_outcome[Outcome.SUCCESS])))
    for r in by_outcome[Outcome.SUCCESS]:
        print(f"  + {r.path.name} -> {r.cep.saved_path if r.cep else ''}")
    if by_outcome[Outcome.REVIEW]:
        print(
            tr(
                "NEEDS REVIEW (real payment, but not a clean confirmation): {count}",
                count=len(by_outcome[Outcome.REVIEW]),
            )
        )
        for r in by_outcome[Outcome.REVIEW]:
            print(f"  ? {r.path.name}: {r.message}")
    if by_outcome[Outcome.NOT_FOUND]:
        print(
            tr(
                "NOT FOUND at Banxico (check data; receipt may be fake): {count}",
                count=len(by_outcome[Outcome.NOT_FOUND]),
            )
        )
        for r in by_outcome[Outcome.NOT_FOUND]:
            print(f"  ! {r.path.name}: {r.message}")
    if by_outcome[Outcome.FAILED]:
        print(tr("Errors / skipped: {count}", count=len(by_outcome[Outcome.FAILED])))
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
