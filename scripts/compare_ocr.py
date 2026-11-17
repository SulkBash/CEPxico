"""Compare OCR engines on your own receipts: speed and the fields each one extracts.

Needs both engines installed in the current environment:
    pip install -e ".[easyocr]"
    python scripts/compare_ocr.py receipt1.png scan.pdf ...

PDFs are always OCR'd here (rendered like a scan), even if they contain text, so the
engines are compared on every file. Nothing is sent anywhere and nothing is saved;
the output shows receipt data, so don't paste it anywhere public.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pymupdf

from cepxico.extraction.parser import parse_payment
from cepxico.extraction.text import OCR_ENGINES, OCR_RENDER_ZOOM, ExtractionError, get_ocr_engine

FIELDS = ("payment_date", "tracking_key", "sender_bank", "receiver_bank", "beneficiary_account", "amount")


def images(path: Path) -> list[bytes]:
    if path.suffix.lower() != ".pdf":
        return [path.read_bytes()]
    with pymupdf.open(path) as doc:
        matrix = pymupdf.Matrix(OCR_RENDER_ZOOM, OCR_RENDER_ZOOM)
        return [page.get_pixmap(matrix=matrix).tobytes("png") for page in doc]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--engines", nargs="+", default=list(OCR_ENGINES), choices=OCR_ENGINES)
    parser.add_argument("--text", action="store_true", help="also print each engine's raw text")
    args = parser.parse_args()

    engines = {}
    for name in args.engines:
        start = time.perf_counter()
        try:
            engines[name] = get_ocr_engine(name)
        except ExtractionError as e:
            print(f"{name}: {e}", file=sys.stderr)
            return 2
        print(f"{name}: loaded in {time.perf_counter() - start:.1f}s")

    totals = dict.fromkeys(engines, 0.0)
    found = dict.fromkeys(engines, 0)
    disagreements = 0
    for path in args.files:
        pages = images(path)
        print(f"\n== {path.name}")
        results = {}
        for name, engine in engines.items():
            start = time.perf_counter()
            raw = "".join(engine(page) for page in pages)
            elapsed = time.perf_counter() - start
            totals[name] += elapsed
            payment = parse_payment(raw, source_file=path.name)
            results[name] = payment
            found[name] += sum(getattr(payment, f) is not None for f in FIELDS)
            print(f"  {name:<9} {elapsed:5.2f}s")
            if args.text:
                print("    " + raw.strip().replace("\n", "\n    "))
        width = max(len(f) for f in FIELDS)
        for field in FIELDS:
            values = [getattr(results[name], field) for name in engines]
            mark = "  " if len(set(values)) == 1 else "≠ "
            disagreements += mark != "  "
            print(f"  {mark}{field:<{width}}  " + "  |  ".join(str(v) for v in values))

    print("\n== Summary")
    for name in engines:
        per_file = totals[name] / len(args.files)
        print(f"  {name:<9} {totals[name]:6.1f}s total, {per_file:5.2f}s/file, {found[name]} fields found")
    print(f"  fields where the engines disagree: {disagreements}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
