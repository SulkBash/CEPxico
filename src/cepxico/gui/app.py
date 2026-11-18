"""Qt desktop app: queue receipts, process them in the background, inspect results."""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QCloseEvent,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QKeySequence,
    QPainter,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QProgressBar,
    QSplitter,
    QStatusBar,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from cepxico import __version__
from cepxico.banxico import Party
from cepxico.config import open_path
from cepxico.extraction import SUPPORTED_EXTENSIONS, correct_payment
from cepxico.gui import messages, theme
from cepxico.gui.code_dialog import CodeDialog
from cepxico.gui.fields_dialog import FieldsDialog
from cepxico.gui.history_dialog import HistoryDialog
from cepxico.gui.settings_dialog import SettingsDialog
from cepxico.history import History
from cepxico.i18n import LANGUAGES, get_language, set_language, tr
from cepxico.models import FIELD_NAMES, PaymentData, field_label
from cepxico.pipeline import CodeRequest, FileResult, Outcome
from cepxico.pipeline import process_files as run_batch
from cepxico.settings import Settings, load_settings, save_settings

logger = logging.getLogger(__name__)

PATH_ROLE = Qt.ItemDataRole.UserRole  # where each row keeps its file's path


def paste_shortcut() -> str:
    """Ctrl+V, or ⌘V on a Mac."""
    return QKeySequence(QKeySequence.StandardKey.Paste).toString(QKeySequence.SequenceFormat.NativeText)


class ItemStatus(Enum):
    PENDING = "status_pending"
    PROCESSING = "status_processing"
    SUCCESS = "status_success"
    NOT_FOUND = "status_notfound"
    REVIEW = "status_review"
    FAILED = "status_failed"
    CANCELLED = "status_cancelled"

    @property
    def tag(self) -> str:
        return self.value

    @property
    def label(self) -> str:
        labels = {
            ItemStatus.PENDING: tr("Pending"),
            ItemStatus.PROCESSING: tr("Checking"),
            ItemStatus.SUCCESS: tr("Confirmed"),
            ItemStatus.NOT_FOUND: tr("Not Found"),
            ItemStatus.REVIEW: tr("Review"),
            ItemStatus.FAILED: tr("Error"),
            ItemStatus.CANCELLED: tr("Skipped"),
        }
        return labels[self]


OUTCOME_STATUS = {
    Outcome.SUCCESS: ItemStatus.SUCCESS,
    Outcome.NOT_FOUND: ItemStatus.NOT_FOUND,
    Outcome.REVIEW: ItemStatus.REVIEW,
    Outcome.FAILED: ItemStatus.FAILED,
}
FINISHED_STATUSES = frozenset(OUTCOME_STATUS.values())
MUTED_STATUSES = frozenset({ItemStatus.PENDING, ItemStatus.CANCELLED})  # not checked (yet): grayed

UI_POLL_MS = 50  # how often the UI thread applies updates posted by the worker
SPINNER_MS = 110  # frame time of the spinner shown on receipts being checked
SPINNER_FRAMES = 8

# Results counted in the status bar, each with its glyph.
COUNTED = (ItemStatus.SUCCESS, ItemStatus.REVIEW, ItemStatus.NOT_FOUND, ItemStatus.FAILED)
COUNT_KEYS = {
    ItemStatus.SUCCESS: "success",
    ItemStatus.REVIEW: "review",
    ItemStatus.NOT_FOUND: "notfound",
    ItemStatus.FAILED: "failed",
    ItemStatus.PENDING: "pending",
}


def file_types() -> list[tuple[str, str]]:
    return [
        (tr("Receipts"), " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))),
        (tr("All Files"), "*.*"),
    ]


def money(amount: str | None, spid: bool = False) -> str | None:
    """ "12500.5" -> "$12,500.50" (US$ for dollar transfers); anything else as it is."""
    if not amount:
        return None
    try:
        value = Decimal(amount.replace(",", ""))
    except InvalidOperation:
        return amount
    return f"{'US$' if spid else '$'}{value:,.2f}"


@dataclass
class QueueItem:
    path: str
    row: Any = None  # its QTreeWidgetItem in the queue
    status: ItemStatus = ItemStatus.PENDING
    result_text: str = ""
    result: FileResult | None = None
    corrected: PaymentData | None = None  # fields the user typed in; used instead of re-reading


def can_edit(item: QueueItem) -> bool:
    """Fields can be typed in for receipts that failed, weren't found at Banxico or need
    review, and edited again until they're checked."""
    if item.status in (ItemStatus.FAILED, ItemStatus.NOT_FOUND, ItemStatus.REVIEW):
        return True
    return item.corrected is not None and item.status in (ItemStatus.PENDING, ItemStatus.CANCELLED)


def is_confirmed(item: QueueItem) -> bool:
    """Whether Banxico already confirmed this receipt and its CEP is still on disk.

    Process Files skips confirmed receipts: checking one again can't change the answer,
    only load Banxico and risk showing a real transfer as Failed after a network error.
    A receipt whose CEP file was deleted is checked again, which downloads it anew."""
    cep = item.result.cep if item.result else None
    return (
        item.status is ItemStatus.SUCCESS
        and cep is not None
        and cep.saved_path is not None
        and cep.saved_path.is_file()
    )


class TreeWithPlaceholder(QTreeWidget):
    """A list that says what to do in gray when it's empty, as Windows Explorer does."""

    def __init__(self, placeholder: str):
        super().__init__()
        self.placeholder = placeholder

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        super().paintEvent(event)
        if self.topLevelItemCount() or not self.placeholder:
            return
        painter = QPainter(self.viewport())
        painter.setPen(theme.muted_color())
        area = self.viewport().rect().adjusted(24, 24, -24, -24)
        painter.drawText(area, Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, self.placeholder)


class PropertyGrid(TreeWithPlaceholder):
    """A receipt's details as name/value rows in collapsible groups, like a Properties
    window. Ctrl+C (or right-click) copies the value of the selected row."""

    def __init__(self, placeholder: str):
        super().__init__(placeholder)
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.setIndentation(14)
        self.header().setStretchLastSection(True)
        self.header().resizeSection(0, 150)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        copy = QAction(tr("Copy"), self, shortcut=QKeySequence.StandardKey.Copy)
        copy.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        copy.triggered.connect(self.copy_value)
        self.addAction(copy)
        self._copy = copy

    def group(self, title: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self, [title])
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setFirstColumnSpanned(True)
        item.setExpanded(True)
        return item

    def add(
        self,
        parent: QTreeWidget | QTreeWidgetItem,
        name: str,
        value: object,
        *,
        mono: bool = False,
        color: str = "",
    ) -> QTreeWidgetItem:
        text = str(value) if value else ""
        item = QTreeWidgetItem(parent, [name, text])
        item.setToolTip(1, text)
        if mono:
            item.setFont(1, theme.mono())
        if color:
            item.setForeground(1, QBrush(QColor(color)))
        return item

    def note(self, parent: QTreeWidgetItem, text: str) -> None:
        item = QTreeWidgetItem(parent, [text])
        item.setFirstColumnSpanned(True)
        item.setToolTip(0, text)
        font = item.font(0)
        font.setItalic(True)
        item.setFont(0, font)

    def copy_value(self) -> None:
        item = self.currentItem()
        if item is not None:
            QGuiApplication.clipboard().setText(item.toolTip(1) or item.text(0))

    def _show_menu(self, position: QPoint) -> None:
        if self.itemAt(position) is not None:
            menu = QMenu(self)
            menu.addAction(self._copy)
            menu.exec(self.viewport().mapToGlobal(position))


class CEPApp(QMainWindow):
    def __init__(self, cep_dir: Path, history: History | None = None):
        app = theme.application()
        super().__init__()
        self.cep_dir = Path(cep_dir)
        self.settings = load_settings()
        set_language(self.settings.language)
        theme.translate_qt(get_language())
        self.history = history or History()
        self.items: dict[str, QueueItem] = {}  # insertion-ordered queue, keyed by file path
        self._temp_files: list[str] = []  # pasted clipboard images, deleted on exit
        self.processing = False
        self.processed_count = 0  # files finished in the current/last batch
        self._batch_size = 0  # files sent to the current/last batch
        self._skipped_confirmed = 0  # confirmed files the current/last batch left alone
        self._cancel = threading.Event()
        self._code_dialog: CodeDialog | None = None  # open while a SPID receipt waits for its code
        self._ui_queue: queue.Queue[tuple[Callable[..., object], tuple[object, ...]]] = queue.Queue()
        self._spinner_frame = 0
        self.counts = dict.fromkeys(("success", "review", "notfound", "failed", "pending"), 0)

        self.setAcceptDrops(True)
        self._build_ui()
        self._place_window()
        # Icons are drawn in the text color: redraw them when the system turns dark or light.
        app.styleHints().colorSchemeChanged.connect(self._on_color_scheme_changed)

        self._ui_timer = QTimer(self, interval=UI_POLL_MS, timeout=self._drain_ui_queue)
        self._ui_timer.start()
        self._spinner_timer = QTimer(self, interval=SPINNER_MS, timeout=self._tick_spinner)
        self._spinner_timer.start()

    def _place_window(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        width, height = min(1100, area.width() - 40), min(680, area.height() - 80)
        self.resize(width, height)
        self.move(
            area.x() + (area.width() - width) // 2, area.y() + max(0, (area.height() - height - 40) // 2)
        )

    def _on_color_scheme_changed(self) -> None:
        theme.clear_icons()
        self._rebuild_ui()

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        self.setWindowTitle("CEPxico")
        self._build_actions()
        self._build_menu()
        self.addToolBar(self._build_toolbar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_queue())
        self.details = PropertyGrid(tr("No receipt selected"))
        splitter.addWidget(self.details)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([660, 420])
        self.setCentralWidget(splitter)  # replaces (and deletes) the old one on a rebuild
        self.setStatusBar(self._build_status_bar())
        self._refresh_counters()

    def _rebuild_ui(self) -> None:
        """Builds the window again, in the current language, keeping the queue."""
        if self._toolbar is not None:
            self.removeToolBar(self._toolbar)
            self._toolbar.deleteLater()
        self._build_ui()
        for item in self.items.values():
            item.row = self._insert_row(item)
        self._refresh_counters()

    def _action(
        self,
        text: str,
        slot: Callable[[], object],
        icon_name: str = "",
        shortcut: QKeySequence.StandardKey | str = "",
    ) -> QAction:
        action = QAction(text, self._menubar)
        action.setIconText(text.rstrip("…"))  # the toolbar's label: no "…" there
        if icon_name:
            action.setIcon(theme.icon(icon_name))
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            native = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            action.setToolTip(f"{text.rstrip('…')} ({native})")
        action.triggered.connect(lambda _checked=False: slot())
        return action

    def _build_actions(self) -> None:
        """Every command, shared by the menu bar, the toolbar and the right-click menu, so
        their names, shortcuts and enabled states always agree."""
        self._menubar = QMenuBar()  # the actions belong to it, and go when it's replaced
        key = QKeySequence.StandardKey
        self.add_action = self._action(tr("Add Files") + "…", self.add_files, "add", key.Open)
        self.paste_action = self._action(tr("Paste"), self.on_paste, "", key.Paste)
        self.folder_action = self._action(tr("Open CEP Folder"), self.open_cep_folder, "folder")
        self.exit_action = self._action(tr("Exit"), self.close, "", key.Quit)
        self.process_action = self._action(tr("Check"), self.process_files, "play", "F5")
        self.cancel_action = self._action(tr("Stop"), self.cancel_processing, "stop", "Esc")
        self.edit_action = self._action(tr("Edit Fields") + "…", self.edit_selected, "edit", "F2")
        self.remove_action = self._action(tr("Remove"), self.remove_selected, "remove", key.Delete)
        self.clear_action = self._action(tr("Clear List"), self.clear_files, "trash")
        self.select_all_action = self._action(tr("Select All"), self.select_all, "", key.SelectAll)
        self.history_action = self._action(tr("History") + "…", self.open_history, "history", "Ctrl+H")
        self.settings_action = self._action(tr("Settings") + "…", self.open_settings, "settings", "Ctrl+,")
        self.about_action = self._action(tr("About CEPxico"), self.show_about)
        self.cancel_action.setEnabled(self.processing and not self._cancel.is_set())
        self.process_action.setEnabled(not self.processing)

    def _build_menu(self) -> None:
        bar = self._menubar
        files = bar.addMenu("&" + tr("File"))
        files.addActions([self.add_action, self.paste_action])
        files.addSeparator()
        files.addAction(self.folder_action)
        files.addSeparator()
        files.addAction(self.exit_action)

        receipts = bar.addMenu("&" + tr("Receipts"))
        receipts.addActions([self.process_action, self.cancel_action])
        receipts.addSeparator()
        receipts.addActions([self.edit_action, self.remove_action, self.clear_action])
        receipts.addSeparator()
        receipts.addAction(self.select_all_action)

        tools = bar.addMenu("&" + tr("Tools"))
        tools.addActions([self.history_action, self.settings_action])
        tools.addSeparator()
        languages = tools.addMenu(tr("Language"))
        group = QActionGroup(languages)
        for code, name in LANGUAGES.items():
            action = languages.addAction(name)
            action.setCheckable(True)
            action.setChecked(code == get_language())
            action.triggered.connect(lambda _checked=False, code=code: self.switch_language(code))
            group.addAction(action)

        help_menu = bar.addMenu("&" + tr("Help"))
        help_menu.addAction(self.about_action)
        self.setMenuBar(bar)  # replaces (and deletes) the old one on a rebuild

    _toolbar: QToolBar | None = None

    def _build_toolbar(self) -> QToolBar:
        bar = self._toolbar = QToolBar()
        bar.setObjectName("toolbar")
        bar.setMovable(False)
        bar.setIconSize(QSize(16, 16))
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        bar.addActions([self.add_action, self.edit_action, self.remove_action, self.clear_action])
        bar.addSeparator()
        bar.addActions([self.process_action, self.cancel_action])
        bar.addSeparator()
        bar.addActions([self.folder_action, self.history_action, self.settings_action])
        self.process_button = bar.widgetForAction(self.process_action)
        return bar

    def _build_queue(self) -> QTreeWidget:
        tree = TreeWithPlaceholder(
            tr(
                "Drop receipts here or paste a screenshot ({shortcut})",
                shortcut=paste_shortcut(),
            )
        )
        tree.setColumnCount(3)
        tree.setHeaderLabels([tr("File"), tr("Status"), tr("Result")])
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setAlternatingRowColors(True)
        tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        tree.setAllColumnsShowFocus(True)
        header = tree.header()
        header.setStretchLastSection(True)
        header.resizeSection(0, 260)
        header.resizeSection(1, 100)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        tree.itemSelectionChanged.connect(self._on_select)
        tree.itemActivated.connect(lambda _item, _column: self.edit_selected())
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree = tree
        return tree

    def _build_status_bar(self) -> QStatusBar:
        bar = QStatusBar()
        self.status_label = QLabel(tr("Ready"))
        bar.addWidget(self.status_label, 1)

        # Shown only while a batch runs.
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedSize(140, 14)
        self.progress_label = QLabel("0 / 0")
        bar.addPermanentWidget(self.progress)
        bar.addPermanentWidget(self.progress_label)

        # How many receipts have each result: a glyph and a number, named in its tooltip.
        self._count_labels: dict[ItemStatus, QLabel] = {}
        for status in COUNTED:
            pane = QWidget()
            pane.setToolTip(status.label)
            row = QHBoxLayout(pane)
            row.setContentsMargins(6, 0, 2, 0)
            row.setSpacing(4)
            glyph = QLabel()
            glyph.setPixmap(theme.status_icon(status.tag).pixmap(14, 14))
            number = QLabel("0")
            row.addWidget(glyph)
            row.addWidget(number)
            bar.addPermanentWidget(pane)
            self._count_labels[status] = number
        return bar

    def _show_context_menu(self, position: QPoint) -> None:
        row = self.tree.itemAt(position)
        if row is None:
            return
        if not row.isSelected():
            self.tree.setCurrentItem(row)
        item = self._selected_item()
        if not item:
            return
        cep = item.result.cep if item.result else None
        cep_path = cep.saved_path if cep and cep.saved_path and cep.saved_path.is_file() else None
        menu = QMenu(self)
        menu.addAction(tr("Open Receipt"), lambda: self._open(item.path, tr("Open Receipt")))
        open_cep = menu.addAction(
            tr("Open CEP"), lambda: self._open(cep_path, tr("Open CEP")) if cep_path else None
        )
        open_cep.setEnabled(cep_path is not None)
        menu.addSeparator()
        menu.addActions([self.edit_action, self.remove_action])
        menu.exec(self.tree.viewport().mapToGlobal(position))

    # ------------------------------------------------------------------ drag & drop

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 (Qt's name)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 (Qt's name)
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.on_drop(paths)

    # ------------------------------------------------------------------ queue management

    def set_status_message(self, text: str) -> None:
        self.status_label.setText(text)

    def _refuse_if_busy(self) -> bool:
        if self.processing:
            messages.warning(self, tr("Checking"), tr("Wait for the check to finish."))
        return self.processing

    def _insert_row(self, item: QueueItem) -> QTreeWidgetItem:
        row = QTreeWidgetItem([os.path.basename(item.path), item.status.label, item.result_text])
        row.setData(0, PATH_ROLE, item.path)
        row.setToolTip(0, item.path)
        row.setToolTip(2, item.result_text)
        self.tree.addTopLevelItem(row)
        self._paint_row(row, item.status)
        return row

    def _paint_row(self, row: QTreeWidgetItem, status: ItemStatus) -> None:
        row.setIcon(0, theme.status_icon(status.tag, self._spinner_frame))
        for column in range(3):
            if status in MUTED_STATUSES:
                row.setForeground(column, QBrush(theme.muted_color()))
            else:
                row.setData(column, Qt.ItemDataRole.ForegroundRole, None)  # the normal text color

    def add_file(self, path: str) -> bool:
        """Queues a file. Returns False if it was already queued."""
        if path in self.items:
            return False
        item = QueueItem(path=path)
        item.row = self._insert_row(item)
        self.items[path] = item
        self._refresh_counters()
        return True

    def add_files(self) -> None:
        if self._refuse_if_busy():
            return
        for path in messages.open_files(self, tr("Add Files"), file_types()):
            self.add_file(path)

    def _add_dropped(self, paths: list[str]) -> None:
        duplicates = 0
        for path in paths:
            if Path(path).suffix.lower() not in SUPPORTED_EXTENSIONS:
                messages.warning(self, tr("Add Files"), tr("{path} isn't a PDF or an image.", path=path))
            elif not self.add_file(path):
                duplicates += 1
        if duplicates:
            self.set_status_message(tr("Already in the list: {count}", count=duplicates))

    def on_drop(self, paths: list[str]) -> None:
        if self._refuse_if_busy():
            return
        self._add_dropped(paths)

    def on_paste(self) -> None:
        if self._refuse_if_busy():
            return
        clipboard = QGuiApplication.clipboard()
        data = clipboard.mimeData()
        files = [url.toLocalFile() for url in data.urls() if url.isLocalFile()] if data.hasUrls() else []
        if files:  # files copied in the file manager
            self._add_dropped(files)
            return
        picture = clipboard.image() if data.hasImage() else None
        if picture is None or picture.isNull():
            self.set_status_message(tr("Nothing to paste"))
            return
        with tempfile.NamedTemporaryFile(prefix="cepxico_paste_", suffix=".png", delete=False) as tf:
            path = tf.name
        picture.save(path, "PNG")
        self._temp_files.append(path)
        self.add_file(path)
        self.set_status_message(tr("Screenshot added"))

    def select_all(self) -> None:
        self.tree.selectAll()

    def remove_selected(self) -> None:
        if self._refuse_if_busy():
            return
        for row in self.tree.selectedItems():
            self.items.pop(row.data(0, PATH_ROLE), None)
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(row))
        self._refresh_counters()
        self._show_selected_details()

    def clear_files(self) -> None:
        if self._refuse_if_busy():
            return
        self.tree.clear()
        self.items.clear()
        self.processed_count = 0
        self._refresh_counters()
        self._show_selected_details()

    def _open(self, path: Path | str, title: str) -> None:
        try:
            open_path(path)
        except OSError as e:
            messages.error(self, title, tr("Couldn't open {path}: {error}", path=path, error=e))

    def open_cep_folder(self) -> None:
        self.cep_dir.mkdir(parents=True, exist_ok=True)
        self._open(self.cep_dir, tr("Open CEP Folder"))

    def open_history(self) -> None:
        HistoryDialog(self, history=self.history, on_open=lambda path: self._open(path, tr("History")))

    def open_settings(self) -> None:
        if self._refuse_if_busy():
            return
        SettingsDialog(self, settings=self.settings, on_save=self.apply_settings)

    def show_about(self) -> None:
        messages.info(
            self,
            tr("About CEPxico"),
            f"CEPxico {__version__}\n\n"
            + tr("Checks SPEI receipts with Banxico and saves their CEPs.")
            + "\n\nGNU AGPL-3.0-or-later",
        )

    def apply_settings(self, settings: Settings) -> str | None:
        """Saves new settings; they apply from the next check. Returns a problem, or None."""
        try:
            save_settings(settings)
        except OSError as e:
            return tr("Couldn't save the settings: {error}", error=e)
        language_changed = settings.language != self.settings.language
        self.settings = settings
        if language_changed:
            set_language(settings.language)
            theme.translate_qt(get_language())
            self._rebuild_ui()
        self.set_status_message(tr("Settings saved"))
        return None

    def switch_language(self, code: str) -> None:
        """Tools > Language: saves the choice and redraws the window."""
        problem = self.apply_settings(replace(self.settings, language=code))
        if problem:
            messages.error(self, tr("Settings"), problem)

    # ------------------------------------------------------------------ typing in fields

    def _selected_item(self) -> QueueItem | None:
        rows = sorted(self.tree.selectedItems(), key=self.tree.indexOfTopLevelItem)
        return self.items.get(rows[0].data(0, PATH_ROLE)) if rows else None

    def edit_selected(self) -> None:
        if self._refuse_if_busy():
            return
        item = self._selected_item()
        if not item:
            messages.info(self, tr("Edit Fields"), tr("Select a receipt first."))
            return
        if not can_edit(item):
            messages.info(
                self,
                tr("Edit Fields"),
                tr("Only receipts marked Error, Not Found or Review can be edited."),
            )
            return

        FieldsDialog(
            self,
            filename=os.path.basename(item.path),
            initial=self._initial_values(item),
            on_save=lambda values, check_now: self.save_corrections(item.path, values, check_now),
            on_open_receipt=lambda: self._open(item.path, tr("Open Receipt")),
        )

    @staticmethod
    def _current_payment(item: QueueItem) -> PaymentData:
        """The latest data for a receipt: the user's corrections, else what was read."""
        if item.corrected:
            return item.corrected
        if item.result and item.result.payment:
            return item.result.payment
        return PaymentData(source_file=os.path.basename(item.path))

    def _initial_values(self, item: QueueItem) -> dict[str, str]:
        payment = self._current_payment(item)
        values = {name: getattr(payment, name) or "" for name in FIELD_NAMES}
        values["pago_a_banco"] = "1" if payment.pago_a_banco else ""
        values["spid"] = "1" if payment.spid else ""
        # Show the banks the app identified when the receipt doesn't name them.
        result = item.result
        if result and result.sender and not values["sender_bank"]:
            values["sender_bank"] = result.sender.bank.name
        if result and result.receiver and not values["receiver_bank"]:
            values["receiver_bank"] = result.receiver.bank.name
        return values

    def save_corrections(self, path: str, values: dict[str, str], check_now: bool) -> dict[str, str]:
        """Applies the fields typed for `path`; checks it at Banxico if `check_now`.
        Returns {field: problem} for invalid values, and then changes nothing."""
        item = self.items.get(path)
        if not item or self.processing:
            return {}
        corrected, errors = correct_payment(self._current_payment(item), values)
        if errors:
            return errors
        if values:
            item.corrected = corrected
            self._set_status(path, ItemStatus.PENDING, tr("Edited"))
        if check_now:
            self._start_batch([item])
        return {}

    # ------------------------------------------------------------------ display

    def _show_selected_details(self) -> None:
        grid = self.details
        grid.clear()
        item = self._selected_item()
        if not item:
            grid.viewport().update()  # shows the placeholder
            return

        result = item.result
        payment = item.corrected or (result.payment if result else None)
        cep = result.cep if result else None
        pago_a_banco = bool(payment and payment.pago_a_banco)
        spid = bool(payment and payment.spid)

        status = grid.add(grid, tr("Status"), item.status.label, color=theme.STATUS_COLORS[item.status.tag])
        status.setIcon(1, theme.status_icon(item.status.tag, self._spinner_frame))
        grid.add(grid, tr("Result"), item.result_text)

        receipt = grid.group(tr("Receipt"))
        grid.add(receipt, tr("Date"), payment and payment.payment_date)
        grid.add(receipt, tr("Clave de rastreo"), payment and payment.tracking_key, mono=True)
        account = tr("Ordering account") if pago_a_banco else tr("Account")
        grid.add(receipt, account, payment and payment.beneficiary_account, mono=True)
        grid.add(receipt, tr("Amount"), money(payment.amount if payment else None, spid))
        if pago_a_banco:
            grid.note(receipt, tr("Paid to the bank itself (pago a banco)"))
        if spid:
            grid.note(receipt, tr("Dollar transfer (SPID)"))

        banks = grid.group(tr("Banks"))
        # Bank as identified in Banxico's catalog, and how it was identified.
        grid.add(banks, tr("Sending bank"), result and result.sender)
        grid.add(banks, tr("Receiving bank"), result and result.receiver)
        if cep and cep.payment_status:
            grid.add(banks, tr("Status at Banxico"), cep.payment_status)

        if cep and cep.record:
            # Banxico's own record of the transfer, read from the CEP's XML.
            r = cep.record

            def party(p: Party) -> str:
                details = ", ".join(v for v in (p.bank, p.account) if v)
                return f"{p.name} ({details})" if p.name and details else (p.name or details)

            record = grid.group("CEP")
            grid.add(record, tr("Date"), f"{r.operation_date} {r.time}")
            grid.add(record, tr("Sender"), party(r.sender))
            grid.add(record, tr("Beneficiary"), party(r.beneficiary))
            grid.add(record, tr("Concept"), r.concept)

        files = grid.group(tr("File"))
        grid.add(files, tr("Path"), item.path)
        if cep and cep.saved_path:  # name only: Open CEP Folder shows where it is
            grid.add(files, "CEP", cep.saved_path.name)
        if payment and payment.edited_fields:
            grid.add(
                files, tr("Edited fields"), ", ".join(field_label(name) for name in payment.edited_fields)
            )

    def _set_status(self, path: str, status: ItemStatus, text: str) -> None:
        item = self.items.get(path)
        if not item:
            return
        item.status, item.result_text = status, text
        item.row.setText(1, status.label)
        item.row.setText(2, text)
        item.row.setToolTip(2, text)
        self._paint_row(item.row, status)
        if item.row.isSelected():
            self._show_selected_details()
        self._refresh_counters()

    def _on_select(self) -> None:
        self._show_selected_details()
        self._update_tools()

    def _update_tools(self) -> None:
        """Enables the commands that can act on the queue and selection as they are."""
        item = self._selected_item()
        idle = not self.processing
        self.edit_action.setEnabled(idle and item is not None and can_edit(item))
        self.remove_action.setEnabled(idle and bool(self.tree.selectedItems()))
        self.clear_action.setEnabled(idle and bool(self.items))

    def _tick_spinner(self) -> None:
        """Turns the spinner on receipts being checked."""
        if not self.processing:
            return
        self._spinner_frame = (self._spinner_frame + 1) % SPINNER_FRAMES
        spinner = theme.status_icon(ItemStatus.PROCESSING.tag, self._spinner_frame)
        for item in self.items.values():
            if item.status is ItemStatus.PROCESSING:
                item.row.setIcon(0, spinner)

    def _count(self, status: ItemStatus) -> int:
        return sum(1 for item in self.items.values() if item.status is status)

    def _refresh_counters(self) -> None:
        total = len(self.items)
        # Files with a result, whether from this batch or an earlier one (confirmed files
        # a batch skips count as done).
        done = sum(1 for item in self.items.values() if item.status in FINISHED_STATUSES)
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        self.progress_label.setText(f"{done} / {total}")
        self.progress.setVisible(self.processing)
        self.progress_label.setVisible(self.processing)
        for status, key in COUNT_KEYS.items():
            self.counts[key] = self._count(status)
        for status, number in self._count_labels.items():
            number.setText(str(self.counts[COUNT_KEYS[status]]))
        self._update_tools()

    # ------------------------------------------------------------------ processing

    def process_files(self) -> None:
        if self._refuse_if_busy():
            return
        if not self.items:
            messages.warning(self, tr("Check"), tr("The list is empty."))
            return
        to_check = [item for item in self.items.values() if not is_confirmed(item)]
        if not to_check:
            messages.info(
                self,
                tr("Check"),
                tr("All receipts are already confirmed. To check one again, remove it and add it back."),
            )
            return
        self._start_batch(to_check)

    def _start_batch(self, to_check: list[QueueItem]) -> None:
        self.processing = True
        self._cancel.clear()
        self.processed_count = 0
        self._batch_size = len(to_check)
        in_batch = {item.path for item in to_check}
        self._skipped_confirmed = sum(
            1 for item in self.items.values() if item.path not in in_batch and is_confirmed(item)
        )
        self.set_status_message(tr("Checking…"))
        self.process_action.setEnabled(False)
        self.cancel_action.setEnabled(True)
        for item in to_check:
            item.result = None
            self._set_status(item.path, ItemStatus.PENDING, tr("Waiting"))

        paths = [item.path for item in to_check]
        payments = {item.path: item.corrected for item in to_check if item.corrected}
        threading.Thread(target=self._worker, args=(paths, payments), daemon=True).start()

    def cancel_processing(self) -> None:
        if self.processing:
            self._cancel.set()
            self.set_status_message(tr("Stopping after the receipts in progress…"))
            self.cancel_action.setEnabled(False)

    def _worker(self, paths: list[str], payments: dict[str, PaymentData]) -> None:
        """Runs in a background thread. It never touches Qt widgets: UI updates go through
        self._ui_queue and are applied on the UI thread by _drain_ui_queue()."""
        post = self._post_to_ui

        def on_step(path: str, step: str) -> None:
            post(self._set_status, path, ItemStatus.PROCESSING, step)

        def on_done(path: str, result: FileResult) -> None:
            post(self._on_file_done, path, result)

        try:
            results = run_batch(
                paths,
                self.cep_dir,
                on_step=on_step,
                on_done=on_done,
                cancel=self._cancel,
                payments=payments,
                settings=self.settings,
                history=self.history,
                ask_code=self._ask_code,
            )
            skipped = [path for path, result in zip(paths, results, strict=True) if result is None]
            if skipped:
                post(self._mark_cancelled, skipped)
        except Exception:
            logger.exception("Batch processing failed")
        finally:
            post(self._on_batch_done)

    def _ask_code(self, request: CodeRequest) -> str | None:
        """Runs on a worker thread: shows Banxico's security image on the UI thread and
        waits for the code typed. None if the person skips it or cancels the batch."""
        answer: queue.Queue[str | None] = queue.Queue(maxsize=1)
        self._post_to_ui(self._show_code_dialog, request, answer)
        while True:
            try:
                return answer.get(timeout=0.2)
            except queue.Empty:
                if self._cancel.is_set():
                    self._post_to_ui(self._close_code_dialog)
                    return None

    def _show_code_dialog(self, request: CodeRequest, answer: queue.Queue[str | None]) -> None:
        self._code_dialog = CodeDialog(self, request=request, on_answer=answer.put)

    def _close_code_dialog(self) -> None:
        if self._code_dialog is not None:
            # RuntimeError: answered just now, so Qt already deleted it.
            with contextlib.suppress(RuntimeError):
                self._code_dialog.skip()
        self._code_dialog = None

    def _post_to_ui(self, func: Callable[..., object], *args: object) -> None:
        """Thread-safe: schedules func(*args) on the UI thread."""
        self._ui_queue.put((func, args))

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                func, args = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            func(*args)

    def _on_file_done(self, path: str, result: FileResult) -> None:
        item = self.items.get(path)
        if item:
            item.result = result
        self.processed_count += 1
        message = result.message
        if result.payment and result.payment.edited_fields:
            message += f"  [{tr('edited')}]"  # checked with fields the user typed in
        self._set_status(path, OUTCOME_STATUS[result.outcome], message)
        self.set_status_message(
            tr(
                "{done} of {total}: {name}",
                done=self.processed_count,
                total=self._batch_size,
                name=os.path.basename(path),
            )
        )

    def _mark_cancelled(self, paths: list[str]) -> None:
        for path in paths:
            item = self.items.get(path)
            if item and item.status is ItemStatus.PENDING:
                self._set_status(path, ItemStatus.CANCELLED, tr("Not checked"))

    def _on_batch_done(self) -> None:
        self.processing = False
        self.process_action.setEnabled(True)
        self.cancel_action.setEnabled(False)
        cancelled = self._cancel.is_set()
        self.set_status_message(tr("Stopped") if cancelled else tr("Done"))
        self._refresh_counters()
        messages.info(self, tr("Results"), self._summary(cancelled))

    def _summary(self, cancelled: bool) -> str:
        def files_with(status: ItemStatus) -> list[QueueItem]:
            return [item for item in self.items.values() if item.status is status]

        def listed(items: list[QueueItem]) -> list[str]:
            return [f"- {os.path.basename(i.path)}: {i.result_text}" for i in items]

        found, not_found = files_with(ItemStatus.SUCCESS), files_with(ItemStatus.NOT_FOUND)
        review = files_with(ItemStatus.REVIEW)
        failed, skipped = files_with(ItemStatus.FAILED), files_with(ItemStatus.CANCELLED)

        lines = [tr("Stopped"), ""] if cancelled else []
        lines += [
            tr("Receipts: {count}", count=len(self.items)),
            tr("Checked: {count}", count=self.processed_count),
        ]
        if self._skipped_confirmed:
            lines.append(tr("Already confirmed: {count}", count=self._skipped_confirmed))
        lines.append(tr("Confirmed: {count}", count=len(found)))
        if skipped:
            lines.append(tr("Not checked: {count}", count=len(skipped)))
        if found:
            lines.append(tr("CEPs in {folder}", folder=self.cep_dir))
        if review:
            lines += [
                "",
                tr(
                    "Review ({count}): the payment exists, but something doesn't match:",
                    count=len(review),
                ),
            ]
            lines += listed(review)
        if not_found:
            lines += [
                "",
                tr(
                    "Not found ({count}): check the data; the receipt may be fake:",
                    count=len(not_found),
                ),
            ]
            lines += listed(not_found)
        if failed:
            lines += ["", tr("Errors ({count}):", count=len(failed))]
            lines += listed(failed)
        return "\n".join(lines)

    # ------------------------------------------------------------------ shutdown

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt's name)
        for path in self._temp_files:
            with contextlib.suppress(OSError):
                os.remove(path)
        self._temp_files.clear()
        super().closeEvent(event)
