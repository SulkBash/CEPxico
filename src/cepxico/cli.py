"""Command-line entry point. With no files, opens the desktop app."""

from __future__ import annotations

import argparse
import glob
import logging
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from cepxico import __version__
from cepxico.banxico import CEPFiles
from cepxico.config import DEFAULT_CEP_DIR
from cepxico.extraction import SUPPORTED_EXTENSIONS
from cepxico.pipeline import DEFAULT_JOBS, MAX_JOBS, FileResult, Outcome, process_files
from cepxico.settings import load_settings, settings_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cepxico",
        description="Extract SPEI transfer data from receipts and download their CEP from Banxico. "
        "Run without files to open the desktop app.",
        epilog=f"Settings made in the desktop app (own accounts, files to save) also apply here: "
        f"{settings_path()}",
    )
    parser.add_argument(
        "files", nargs="*", type=Path, help="receipt PDF/image files, wildcards (*.pdf) or folders"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_CEP_DIR,
        help=f"folder for downloaded CEPs (default: {DEFAULT_CEP_DIR})",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=_jobs,
        default=DEFAULT_JOBS,
        help=f"receipts to check at once, 1-{MAX_JOBS} (default: {DEFAULT_JOBS})",
    )
    parser.add_argument(
        "--save",
        choices=[f.value for f in CEPFiles],
        help="what to save for each CEP: the PDF, the XML, or both in one ZIP "
        "(default: as set in the desktop app)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug output")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _jobs(value: str) -> int:
    try:
        jobs = int(value)
    except ValueError:
        jobs = 0
    if not 1 <= jobs <= MAX_JOBS:
        raise argparse.ArgumentTypeError(f"must be a whole number from 1 to {MAX_JOBS}")
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
    print("\n--- Summary ---")
    print(f"Files: {len(results)}")
    print(f"CEP found and saved: {len(by_outcome[Outcome.SUCCESS])}")
    for r in by_outcome[Outcome.SUCCESS]:
        print(f"  + {r.path.name} -> {r.cep.saved_path if r.cep else ''}")
    if by_outcome[Outcome.REVIEW]:
        print(f"NEEDS REVIEW (real payment, but not a clean confirmation): {len(by_outcome[Outcome.REVIEW])}")
        for r in by_outcome[Outcome.REVIEW]:
            print(f"  ? {r.path.name}: {r.message}")
    if by_outcome[Outcome.NOT_FOUND]:
        print(f"NOT FOUND at Banxico (check data; receipt may be fake): {len(by_outcome[Outcome.NOT_FOUND])}")
        for r in by_outcome[Outcome.NOT_FOUND]:
            print(f"  ! {r.path.name}: {r.message}")
    if by_outcome[Outcome.FAILED]:
        print(f"Errors / skipped: {len(by_outcome[Outcome.FAILED])}")
        for r in by_outcome[Outcome.FAILED]:
            print(f"  - {r.path.name}: {r.message}")


def main(argv: Sequence[str] | None = None) -> int:
    """Returns 0 if every receipt's CEP was found, 1 otherwise."""
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    if not args.files:
        from cepxico.gui import run

        run(cep_dir=args.out)
        return 0

    settings = load_settings()
    if args.save:
        settings = replace(settings, cep_files=CEPFiles(args.save))
    paths = expand_paths(args.files)
    results = [r for r in process_files(paths, args.out, jobs=args.jobs, settings=settings) if r is not None]

    print_summary(results)
    return 0 if all(r.outcome is Outcome.SUCCESS for r in results) else 1
