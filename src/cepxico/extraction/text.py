"""Getting raw text out of receipts: embedded PDF text first, OCR as a fallback.

OCR engines:
  - RapidOCR (default): PaddleOCR's PP-OCRv6 models on ONNX Runtime. About 50 MB
    installed, models bundled, multilingual including Spanish accents.
  - EasyOCR (optional, `pip install cepxico[easyocr]`): the v1 engine. Pulls in PyTorch
    (about 2 GB). Used if RapidOCR is missing, or forced with CEPXICO_OCR=easyocr.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Sequence
from functools import lru_cache
from pathlib import Path

import pdfplumber
import pymupdf

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}

# PDFs with less embedded text than this are treated as scans and OCR'd.
MIN_PDF_TEXT_CHARS = 20
OCR_RENDER_ZOOM = 2  # render PDF pages at 2x for better OCR accuracy

OCR_ENGINE_ENV = "CEPXICO_OCR"  # "rapidocr" or "easyocr"; unset = RapidOCR if installed
OCR_ENGINES = ("rapidocr", "easyocr")

OcrEngine = Callable[[bytes], str]  # encoded PNG/JPEG bytes -> text

# One OCR at a time: the engines aren't documented as thread-safe, and ONNX Runtime
# already uses every CPU core for a single image, so parallel OCR wouldn't be faster.
_ocr_lock = threading.Lock()


class ExtractionError(Exception):
    """The file couldn't be read."""


# ------------------------------------------------------------------------------
# OCR
# ------------------------------------------------------------------------------

Box = Sequence[Sequence[float]]  # 4 corner points [[x, y], ...]


def lines_from_boxes(boxes: Sequence[Box], texts: Sequence[str]) -> list[str]:
    """Groups OCR text boxes into lines, the way pdfplumber lays out PDF text.

    Receipts often put a label and its value in separate columns ("Clave de rastreo"
    ... "MBAN0100..."); OCR returns those as separate boxes. Boxes whose vertical centre
    falls inside the current line's height are joined left to right, so the parser
    sees "Clave de rastreo MBAN0100..." on one line.
    """
    items = []
    for box, text in zip(boxes, texts, strict=True):
        ys = [p[1] for p in box]
        items.append((min(ys), max(ys), min(p[0] for p in box), text))
    items.sort(key=lambda it: (it[0] + it[1]) / 2)

    rows: list[list[tuple[float, float, float, str]]] = []
    for item in items:
        centre = (item[0] + item[1]) / 2
        if rows:
            row = rows[-1]
            top = min(it[0] for it in row)
            bottom = max(it[1] for it in row)
            if top <= centre <= bottom:
                row.append(item)
                continue
        rows.append([item])
    return [" ".join(it[3] for it in sorted(row, key=lambda it: it[2])) for row in rows]


def _rapidocr_engine() -> OcrEngine:
    from rapidocr import RapidOCR

    engine = RapidOCR(params={"Global.log_level": "error"})

    def run(image: bytes) -> str:
        result = engine(image)
        if result.boxes is None or not result.txts:
            return ""
        return "\n".join(lines_from_boxes(result.boxes.tolist(), result.txts)) + "\n"

    return run


def _easyocr_engine() -> OcrEngine:
    import easyocr

    logger.info("Loading EasyOCR models (this may take a moment on first run)...")
    reader = easyocr.Reader(["es", "en"])

    def run(image: bytes) -> str:
        lines = reader.readtext(image, detail=0, paragraph=True)
        return "\n".join(lines) + "\n"

    return run


_ENGINE_FACTORIES = {"rapidocr": _rapidocr_engine, "easyocr": _easyocr_engine}


@lru_cache(maxsize=2)
def get_ocr_engine(name: str | None = None) -> OcrEngine:
    """The OCR engine `name`, else the one CEPXICO_OCR names, else the first installed.
    Raises ExtractionError if none is available."""
    choice = (name or os.environ.get(OCR_ENGINE_ENV, "")).strip().lower()
    if choice and choice not in _ENGINE_FACTORIES:
        raise ExtractionError(f"Unknown OCR engine '{choice}' (choose from {', '.join(OCR_ENGINES)})")
    for candidate in [choice] if choice else OCR_ENGINES:
        try:
            engine = _ENGINE_FACTORIES[candidate]()
        except ImportError as e:
            if e.name != candidate:  # installed, but one of its dependencies is broken
                raise ExtractionError(f"OCR engine '{candidate}' failed to load: {e}") from e
            logger.debug("OCR engine %s is not installed", candidate)
            continue
        logger.debug("Using OCR engine %s", candidate)
        return engine
    raise ExtractionError(
        "OCR needed but no OCR engine is installed (pip install rapidocr)"
        if not choice
        else f"OCR engine '{choice}' is not installed"
    )


def _ocr(image: bytes) -> str:
    with _ocr_lock:
        engine = get_ocr_engine()
        return engine(image)


# ------------------------------------------------------------------------------
# Files
# ------------------------------------------------------------------------------


def _pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "".join(page_text + "\n" for page in pdf.pages if (page_text := page.extract_text()))


def _ocr_pdf(path: Path) -> str:
    with pymupdf.open(path) as doc:
        matrix = pymupdf.Matrix(OCR_RENDER_ZOOM, OCR_RENDER_ZOOM)
        return "".join(_ocr(page.get_pixmap(matrix=matrix).tobytes("png")) for page in doc)


def extract_text(path: Path | str) -> str:
    """All text in a receipt. Raises ExtractionError if the file can't be read."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ExtractionError(f"Unsupported file type '{suffix}'")

    try:
        if suffix in IMAGE_EXTENSIONS:
            logger.info("%s: image detected, running OCR", path.name)
            # Bytes, not the path: OpenCV-based readers fail on non-ASCII Windows paths.
            return _ocr(path.read_bytes())

        text = _pdf_text(path)
        if len(text.strip()) < MIN_PDF_TEXT_CHARS:
            logger.info("%s: little embedded text, running OCR", path.name)
            text = _ocr_pdf(path)
        return text
    except ExtractionError:
        raise
    except Exception as e:  # pdfplumber/pymupdf/OCR engines raise many unrelated types
        raise ExtractionError(f"Failed to read file: {e}") from e
