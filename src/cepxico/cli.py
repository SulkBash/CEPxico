"""Command-line entry point. With no files, opens the desktop app."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from cepxico import __version__
from cepxico.config import DEFAULT_CEP_DIR
from cepxico.pipeline import DEFAULT_JOBS, MAX_JOBS, FileResult, Outcome, process_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cepxico",
        description="Extract SPEI transfer data from receipts and download their CEP from Banxico. "
        "Run without files to open the desktop app.",
    )
    parser.add_argument("files", nargs="*", type=Path, help="receipt PDF/image file(s) to process")
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
        print(f"  + {r.path.name} -> {r.cep.pdf_path if r.cep else ''}")
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

    results = [r for r in process_files(args.files, args.out, jobs=args.jobs) if r is not None]

    print_summary(results)
    return 0 if all(r.outcome is Outcome.SUCCESS for r in results) else 1
