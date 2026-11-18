"""What the desktop app shares across windows: the application object, status colors,
icons, and placing dialogs.

The app uses each system's own style, fonts and colors (light or dark, as the system
is set), like any other program there. Only the status colors and the icons are its own.
"""

from __future__ import annotations

import contextlib
import math
import sys
from collections.abc import Callable

from PIL import Image
from PySide6.QtCore import QLibraryInfo, QSize, Qt, QTranslator
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QImage, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QWidget

from cepxico.gui import icons

# The color of each status, for its glyph and its name in the details. Readable on
# light and dark backgrounds alike.
STATUS_COLORS = {
    "status_pending": "#8A93A3",
    "status_processing": "#D08A12",
    "status_success": "#23A05A",
    "status_notfound": "#D9600F",
    "status_review": "#3B7DED",
    "status_failed": "#DC3B36",
    "status_cancelled": "#8E7CC3",
}
ERROR_COLOR = STATUS_COLORS["status_failed"]

# The detail color of each toolbar icon (its lines take the text color).
ICON_ACCENTS = {
    "add": "#23A05A",
    "remove": "#DC3B36",
    "edit": "#E8A93A",
    "trash": "#DC3B36",
    "history": "#3B7DED",
    "open": "#3B7DED",
    "receipt": "#8A9BB5",
    "stop": "#DC3B36",
    "play": "#23A05A",
}
LOGO_INK = "#1F3A5F"

_app: QApplication | None = None


def application() -> QApplication:
    """The QApplication, created on first use."""
    global _app
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _app = existing
        return existing
    _set_windows_app_id()
    _app = QApplication(sys.argv[:1])
    _app.setApplicationName("CEPxico")
    _app.setWindowIcon(app_icon())
    return _app


def _set_windows_app_id() -> None:
    """Windows: group the app's windows under its own taskbar icon, not Python's."""
    if sys.platform != "win32":
        return
    import ctypes

    with contextlib.suppress(AttributeError, OSError):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("mx.cepxico.app")  # type: ignore[attr-defined]


_translator: QTranslator | None = None


def translate_qt(language: str) -> None:
    """Qt's own words (Yes, No, Cancel in message boxes; the text box menu) in the
    app's language. English needs nothing."""
    global _translator
    app = application()
    if _translator is not None:
        app.removeTranslator(_translator)
        _translator = None
    if language == "en":
        return
    translator = QTranslator(app)
    if translator.load(f"qtbase_{language}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
        _translator = translator


def mono(size_change: float = 0) -> QFont:
    """The system's fixed-width font, for claves and account numbers."""
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    families = set(QFontDatabase.families())
    for family in ("Cascadia Mono", "Consolas"):  # nicer than Courier New, on Windows
        if family in families:
            font.setFamily(family)
            break
    font.setPointSizeF(QApplication.font().pointSizeF() + size_change)
    return font


def text_color() -> str:
    return QApplication.palette().color(QPalette.ColorRole.WindowText).name()


def muted_color() -> QColor:
    return QApplication.palette().color(QPalette.ColorRole.PlaceholderText)


# --- icons -----------------------------------------------------------------------------

_cache: dict[tuple, QIcon | QPixmap | QImage] = {}


def clear_icons() -> None:
    """Forget drawn icons, after the system switches between light and dark."""
    _cache.clear()


def qimage(image: Image.Image) -> QImage:
    image = image.convert("RGBA")
    data = image.tobytes("raw", "RGBA")
    return QImage(data, image.width, image.height, QImage.Format.Format_RGBA8888).copy()


def _screen_ratio() -> float:
    return max([s.devicePixelRatio() for s in QGuiApplication.screens()] or [1.0])


def _icon(key: tuple, size: int, draw: Callable[[int], Image.Image]) -> QIcon:
    """A QIcon drawn at every scale a screen might ask for, so it's never blurry."""
    if key not in _cache:
        result = QIcon()
        for scale in sorted({1.0, 1.25, 1.5, 2.0, 3.0, _screen_ratio()}):
            result.addPixmap(QPixmap.fromImage(qimage(draw(math.ceil(size * scale)))))
        _cache[key] = result
    return _cache[key]  # type: ignore[return-value]


def icon(name: str, size: int = 16) -> QIcon:
    """A toolbar icon: lines in the text color, its detail in its own color."""
    ink = text_color()
    accent = ICON_ACCENTS.get(name, ink)
    return _icon(("icon", name, ink, size), size, lambda s: icons.draw(name, s, ink, accent))


def status_icon(tag: str, frame: int = 0) -> QIcon:
    """The glyph of a status tag ("status_success"...); `frame` turns the processing spinner."""
    kind = tag.removeprefix("status_")
    frame = frame if kind == "processing" else 0
    return _icon(("status", kind, frame), 16, lambda s: icons.status(kind, s, STATUS_COLORS[tag], frame))


def app_icon() -> QIcon:
    """CEPxico's mark at the sizes title bars, taskbars and docks pick from."""
    key = ("appicon",)
    if key not in _cache:
        result = QIcon()
        for s in (16, 20, 24, 32, 40, 48, 64, 128, 256):
            result.addPixmap(
                QPixmap.fromImage(qimage(icons.logo(s, LOGO_INK, STATUS_COLORS["status_success"])))
            )
        _cache[key] = result
    return _cache[key]  # type: ignore[return-value]


# --- dialogs -----------------------------------------------------------------------------


def wrapped(text: str, width: int = 460) -> QLabel:
    """A paragraph of explanation, wrapped at `width` pixels. Its height is fixed from
    the start: dialogs size themselves before Qt knows how tall wrapped text is."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setFixedWidth(width)
    label.setMinimumHeight(label.heightForWidth(width))
    return label


def error_label() -> QLabel:
    """Where a dialog says what's wrong with what was typed; empty until then."""
    label = QLabel()
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {ERROR_COLOR}")
    return label


def present(dialog: QDialog, parent: QWidget | None, size: QSize | None = None) -> None:
    """Opens a dialog over its parent, modal, kept on screen. It's deleted once closed;
    the code after show() keeps running (no nested event loop)."""
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.finished.connect(dialog.deleteLater)
    if size is not None:
        dialog.resize(size)
    else:
        dialog.adjustSize()
    screen = (parent.screen() if parent else None) or QGuiApplication.primaryScreen()
    area = screen.availableGeometry()
    frame = 32  # title bar, outside the size Qt reports before the window is shown
    width, height = min(dialog.width(), area.width()), min(dialog.height(), area.height() - frame)
    dialog.resize(width, height)
    center = parent.window().frameGeometry().center() if parent else area.center()
    x = max(area.left(), min(center.x() - width // 2, area.right() - width))
    y = max(area.top(), min(center.y() - height // 2 - frame, area.bottom() - height - frame))
    dialog.move(x, y)
    dialog.show()
