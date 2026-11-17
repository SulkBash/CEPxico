"""Reading payment receipts (PDF or image) into PaymentData."""

from __future__ import annotations

import logging
from pathlib import Path

from cepxico.extraction.parser import correct_payment, parse_payment
from cepxico.extraction.text import SUPPORTED_EXTENSIONS, ExtractionError, extract_text
from cepxico.i18n import tr
from cepxico.models import PaymentData

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "ExtractionError",
    "correct_payment",
    "extract_payment",
    "extract_text",
    "parse_payment",
]

logger = logging.getLogger(__name__)


def extract_payment(path: Path | str) -> PaymentData:
    """Reads a receipt and parses its payment fields. Never raises for unreadable files:
    the problem is reported in `PaymentData.error_reason`."""
    path = Path(path)
    try:
        text = extract_text(path)
    except ExtractionError as e:
        logger.warning("%s: %s", path.name, e)
        return PaymentData(source_file=path.name, error_reason=str(e))

    if not text.strip():
        logger.warning("%s: no text could be extracted", path.name)
        return PaymentData(source_file=path.name, error_reason=tr("No text extracted"))

    return parse_payment(text, source_file=path.name)
