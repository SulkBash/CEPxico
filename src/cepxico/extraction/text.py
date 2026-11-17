"""Getting raw text out of receipts: embedded PDF text first, OCR as a fallback."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import pdfplumber
import pymupdf

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}

# PDFs with less embedded text than this are treated as scans and OCR'd.
MIN_PDF_TEXT_CHARS = 20
OCR_RENDER_ZOOM = 2  # render PDF pages at 2x for better OCR accuracy


class ExtractionError(Exception):
    """The file couldn't be read."""


@lru_cache(maxsize=1)
def _ocr_reader() -> Any:
    try:
        import easyocr
    except ImportError as e:
        raise ExtractionError("OCR needed but easyocr is not installed (pip install cepxico[ocr])") from e
    logger.info("Loading EasyOCR models (this may take a moment on first run)...")
    return easyocr.Reader(["es", "en"])


def _ocr(image: str | bytes) -> str:
    """OCR an image given as a file path or encoded (PNG/JPEG) bytes."""
    lines = _ocr_reader().readtext(image, detail=0, paragraph=True)
    return "\n".join(lines) + "\n"


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
            return _ocr(str(path))

        text = _pdf_text(path)
        if len(text.strip()) < MIN_PDF_TEXT_CHARS:
            logger.info("%s: little embedded text, running OCR", path.name)
            text = _ocr_pdf(path)
        return text
    except ExtractionError:
        raise
    except Exception as e:  # pdfplumber/pymupdf/easyocr raise many unrelated types
        raise ExtractionError(f"Failed to read file: {e}") from e
