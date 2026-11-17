"""Spanish and English for everything users read: the desktop app, the command line and
result messages.

Messages are written in English in the code, wrapped in tr(); translations.py maps
each one to Spanish. tests/test_i18n.py fails if a tr() message has no translation or
the two versions don't use the same {placeholders}.

The language is process-wide: set once at startup from the settings (or the system's
language), and changed when the user picks another in the desktop app. Messages are
translated when they're made, so a result keeps the language it was checked in.
"""

from __future__ import annotations

import contextlib
import locale
import os
import sys

from cepxico.translations import ES

LANGUAGES = {"es": "Español", "en": "English"}
DEFAULT_LANGUAGE = "es"  # receipts, banks and Banxico are all Mexican

_language = DEFAULT_LANGUAGE


def tr(message: str, /, **values: object) -> str:
    """`message` in the current language, with {placeholders} filled from `values`."""
    template = ES.get(message, message) if _language == "es" else message
    return template.format(**values) if values else template


def set_language(code: str) -> None:
    global _language
    _language = code if code in LANGUAGES else system_language()


def get_language() -> str:
    return _language


def system_language() -> str:
    """ "es" or "en" from the user's system language; Spanish if it can't be told."""
    candidates = [os.environ.get(name, "") for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")]
    if sys.platform == "win32":
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
            candidates.insert(0, "es" if lang_id & 0x3FF == 0x0A else "en")  # 0x0A: Spanish
        except (AttributeError, OSError):
            pass
    with contextlib.suppress(ValueError):
        candidates.append(locale.getlocale()[0] or "")
    for candidate in candidates:
        code = candidate.strip().lower()[:2]
        if code in LANGUAGES:
            return code
        if candidate.lower().startswith("spanish"):  # Windows locale names: "Spanish_Mexico"
            return "es"
        if candidate.lower().startswith("english"):
            return "en"
    return DEFAULT_LANGUAGE
