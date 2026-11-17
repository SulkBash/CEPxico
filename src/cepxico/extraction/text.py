"""Getting raw text out of receipts: embedded PDF text first, OCR as a fallback.

PDF text and OCR text share one layout: words are grouped into lines by position
(lines_from_boxes), so the parser sees the same thing whichever way a receipt was read.
Photos are turned upright first (EXIF orientation), and text boxes of a photo taken at
an angle are straightened before grouping, so labels and values still share a line.

OCR engines:
  - RapidOCR (default): PaddleOCR's PP-OCRv6 models on ONNX Runtime. About 50 MB
    installed, models bundled, multilingual including Spanish accents.
  - EasyOCR (optional, `pip install cepxico[easyocr]`): the v1 engine. Pulls in PyTorch
    (about 2 GB). Used if RapidOCR is missing, or forced with CEPXICO_OCR=easyocr.
"""

from __future__ import annotations

import io
import logging
import math
import os
import statistics
import threading
from collections.abc import Callable, Sequence
from functools import lru_cache
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

from cepxico.i18n import tr

logger = logging.getLogger(__name__)

# Word boxes as tall as the glyphs instead of the font's full ascent and descent. With
# the full height, boxes on tightly spaced lines overlap and lines_from_boxes merges
# those lines into one. A process-wide setting, used only by text extraction here.
pymupdf.TOOLS.set_small_glyph_heights(True)

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

Box = Sequence[Sequence[float]]  # 4 corner points: top-left, top-right, bottom-right, bottom-left

# Text tilted less than this is left alone; more than MAX_SKEW_DEGREES isn't a tilted
# photo but a sideways one, which EXIF orientation (or the OCR's own classifier) handles.
MIN_SKEW_DEGREES = 0.5
MAX_SKEW_DEGREES = 45.0


def skew_degrees(boxes: Sequence[Box]) -> float:
    """How far the text is tilted, clockwise in degrees: the median slope of the top
    edge of boxes at least twice as wide as tall (a short box's slope is mostly noise)."""
    angles = []
    for box in boxes:
        (x0, y0), (x1, y1), (x3, y3) = box[0][:2], box[1][:2], box[3][:2]
        width = math.hypot(x1 - x0, y1 - y0)
        height = math.hypot(x3 - x0, y3 - y0)
        if width > 0 and width >= 2 * height:
            angles.append(math.degrees(math.atan2(y1 - y0, x1 - x0)))
    return statistics.median(angles) if angles else 0.0


def _straighten(boxes: Sequence[Box]) -> list[list[tuple[float, float]]]:
    """The boxes rotated so the text they hold runs horizontally."""
    angle = skew_degrees(boxes)
    points = [[(float(p[0]), float(p[1])) for p in box] for box in boxes]
    if not MIN_SKEW_DEGREES <= abs(angle) <= MAX_SKEW_DEGREES:
        return points
    logger.debug("Straightening text tilted %.1f degrees", angle)
    cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return [[(x * cos + y * sin, -x * sin + y * cos) for x, y in box] for box in points]


def lines_from_boxes(boxes: Sequence[Box], texts: Sequence[str]) -> list[str]:
    """Groups words or OCR text boxes into lines, left to right.

    Receipts often put a label and its value in separate columns ("Clave de rastreo"
    ... "MBAN0100..."), which come back as separate boxes. Boxes whose vertical centre
    falls inside the current line's height are joined left to right, so the parser
    sees "Clave de rastreo MBAN0100..." on one line. Boxes from a photo taken at an
    angle are straightened first: tilted a few degrees, a value in a far column would
    otherwise sit a line above or below its label.
    """
    items = []
    for box, text in zip(_straighten(boxes), texts, strict=True):
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
        raise ExtractionError(
            tr(
                "Unknown OCR engine '{name}' (choose from {choices})",
                name=choice,
                choices=", ".join(OCR_ENGINES),
            )
        )
    for candidate in [choice] if choice else OCR_ENGINES:
        try:
            engine = _ENGINE_FACTORIES[candidate]()
        except ImportError as e:
            if e.name != candidate:  # installed, but one of its dependencies is broken
                raise ExtractionError(
                    tr("OCR engine '{name}' failed to load: {error}", name=candidate, error=e)
                ) from e
            logger.debug("OCR engine %s is not installed", candidate)
            continue
        logger.debug("Using OCR engine %s", candidate)
        return engine
    raise ExtractionError(
        tr("OCR needed but no OCR engine is installed (pip install rapidocr)")
        if not choice
        else tr("OCR engine '{name}' is not installed", name=choice)
    )


def _ocr(image: bytes) -> str:
    with _ocr_lock:
        engine = get_ocr_engine()
        return engine(image)


# ------------------------------------------------------------------------------
# Files
# ------------------------------------------------------------------------------


def upright_image(data: bytes) -> bytes:
    """The image turned the way it was shot. Phones save photos sideways and record the
    turn in EXIF; OCR reads pixels as stored. Unreadable images are returned as given,
    for the OCR to report."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.getexif().get(0x0112, 1) == 1:  # Orientation tag: already upright
                return data
            upright = ImageOps.exif_transpose(image)
            if upright.mode not in ("RGB", "L"):
                upright = upright.convert("RGB")
            out = io.BytesIO()
            upright.save(out, "PNG")
            return out.getvalue()
    except Exception as e:  # Pillow raises many types for damaged files
        logger.debug("Couldn't read EXIF orientation: %s", e)
        return data


def _page_text(page: pymupdf.Page) -> str:
    # Each word: (x0, y0, x1, y1, text, block, line, word number). MuPDF splits words at
    # spaces and at gaps between glyphs, so PDFs that place every glyph separately
    # still come out with spaces between words.
    words = page.get_text("words")
    if not words:
        return ""
    boxes = [[(w[0], w[1]), (w[2], w[1]), (w[2], w[3]), (w[0], w[3])] for w in words]
    return "\n".join(lines_from_boxes(boxes, [w[4] for w in words])) + "\n"


def _pdf_text(path: Path) -> str:
    with pymupdf.open(path) as doc:
        return "".join(_page_text(page) for page in doc)


def _ocr_pdf(path: Path) -> str:
    with pymupdf.open(path) as doc:
        matrix = pymupdf.Matrix(OCR_RENDER_ZOOM, OCR_RENDER_ZOOM)
        return "".join(_ocr(page.get_pixmap(matrix=matrix).tobytes("png")) for page in doc)


def extract_text(path: Path | str) -> str:
    """All text in a receipt. Raises ExtractionError if the file can't be read."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ExtractionError(tr("Unsupported file type '{suffix}'", suffix=suffix))

    try:
        if suffix in IMAGE_EXTENSIONS:
            logger.info("%s: image detected, running OCR", path.name)
            # Bytes, not the path: OpenCV-based readers fail on non-ASCII Windows paths.
            return _ocr(upright_image(path.read_bytes()))

        text = _pdf_text(path)
        if len(text.strip()) < MIN_PDF_TEXT_CHARS:
            logger.info("%s: little embedded text, running OCR", path.name)
            text = _ocr_pdf(path)
        return text
    except ExtractionError:
        raise
    except Exception as e:  # pymupdf and the OCR engines raise many unrelated types
        raise ExtractionError(tr("Failed to read file: {error}", error=e)) from e
