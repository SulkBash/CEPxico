"""Tkinter desktop app: queue receipts, process them in the background, inspect results."""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import sys
import tempfile
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageGrab
from tkinterdnd2 import DND_FILES, TkinterDnD

from cepxico.banxico import Party
from cepxico.config import open_path
from cepxico.extraction import SUPPORTED_EXTENSIONS, correct_payment
from cepxico.gui import theme
from cepxico.gui.code_dialog import CodeDialog
from cepxico.gui.fields_dialog import FieldsDialog
from cepxico.gui.history_dialog import HistoryDialog
from cepxico.gui.settings_dialog import SettingsDialog
from cepxico.history import History
from cepxico.i18n import LANGUAGES, get_language, set_language, tr
from cepxico.models import FIELD_NAMES, PaymentData, field_label
from cepxico.pipeline import SPID_URL, CodeRequest, FileResult, Outcome
from cepxico.pipeline import process_files as run_batch
from cepxico.settings import Settings, load_settings, save_settings

logger = logging.getLogger(__name__)

# Command-V on a Mac, Control-V elsewhere (the uppercase form fires with Caps Lock on).
PASTE_KEYS = ("<Command-v>", "<Command-V>") if sys.platform == "darwin" else ("<Control-v>", "<Control-V>")
PASTE_SHORTCUT = "Cmd+V" if sys.platform == "darwin" else "Ctrl+V"


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
            ItemStatus.PROCESSING: tr("Processing"),
            ItemStatus.SUCCESS: tr("Success"),
            ItemStatus.NOT_FOUND: tr("Not Found"),
            ItemStatus.REVIEW: tr("Review"),
            ItemStatus.FAILED: tr("Failed"),
            ItemStatus.CANCELLED: tr("Cancelled"),
        }
        return labels[self]


OUTCOME_STATUS = {
    Outcome.SUCCESS: ItemStatus.SUCCESS,
    Outcome.NOT_FOUND: ItemStatus.NOT_FOUND,
    Outcome.REVIEW: ItemStatus.REVIEW,
    Outcome.FAILED: ItemStatus.FAILED,
}
FINISHED_STATUSES = frozenset(OUTCOME_STATUS.values())

UI_POLL_MS = 50  # how often the Tk thread applies updates posted by the worker


def file_types() -> list[tuple[str, str]]:
    return [
        (tr("Documents & Images"), " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))),
        (tr("All Files"), "*.*"),
    ]


@dataclass
class QueueItem:
    path: str
    tree_id: str
    status: ItemStatus = ItemStatus.PENDING
    result_text: str = field(default_factory=lambda: tr("Ready"))
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


class CEPApp(TkinterDnD.Tk):
    def __init__(self, cep_dir: Path, history: History | None = None):
        super().__init__()
        self.cep_dir = Path(cep_dir)
        self.settings = load_settings()
        set_language(self.settings.language)
        self.history = history or History()
        self.items: dict[str, QueueItem] = {}  # insertion-ordered queue, keyed by file path
        self._path_by_tree_id: dict[str, str] = {}
        self._temp_files: list[str] = []  # pasted clipboard images, deleted on exit
        self.processing = False
        self.processed_count = 0  # files finished in the current/last batch
        self._batch_size = 0  # files sent to the current/last batch
        self._skipped_confirmed = 0  # confirmed files the current/last batch left alone
        self._cancel = threading.Event()
        self._code_dialog: CodeDialog | None = None  # open while a SPID receipt waits for its code
        self._ui_queue: queue.Queue[tuple[Callable[..., object], tuple[object, ...]]] = queue.Queue()

        self.geometry("1180x780")
        self.minsize(1080, 700)
        self.configure(bg=theme.APP_BG)
        theme.apply(self)

        self.stat_vars = {
            name: tk.StringVar(value="0")
            for name in ("loaded", "processed", "success", "review", "notfound", "failed", "pending")
        }
        self.status_var = tk.StringVar(value=tr("Ready"))
        self.progress_label_var = tk.StringVar(value="0 / 0")

        self._main: ttk.Frame | None = None
        self._build_ui()
        for key in PASTE_KEYS:
            self.bind(key, self.on_paste)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(UI_POLL_MS, self._drain_ui_queue)

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        self.title(tr("CEPxico - SPEI receipt checker"))
        main = self._main = ttk.Frame(self, padding=16, style="App.TFrame")
        main.pack(fill=tk.BOTH, expand=True)
        self._build_header(main)
        self._build_stats(main)
        self._build_actions(main)
        workspace = ttk.Panedwindow(main, orient=tk.HORIZONTAL)
        workspace.pack(fill=tk.BOTH, expand=True)
        self._build_queue_panel(workspace)
        self._build_side_panel(workspace)
        ttk.Label(main, textvariable=self.status_var, anchor=tk.W, style="StatusBar.TLabel").pack(
            fill=tk.X, pady=(2, 0)
        )

    def _rebuild_ui(self) -> None:
        """Builds the window again, in the current language, keeping the queue."""
        if self._main is not None:
            self._main.destroy()
        self._path_by_tree_id.clear()
        self._build_ui()
        for item in self.items.values():
            item.tree_id = self.tree.insert(
                "",
                tk.END,
                text=os.path.basename(item.path),
                values=(item.status.label, item.result_text),
                tags=(item.status.tag,),
            )
            self._path_by_tree_id[item.tree_id] = item.path
        self._refresh_counters()

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent, style="App.TFrame")
        header.pack(fill=tk.X, pady=(0, 12))
        # App-wide actions; the toolbar below is for the queue.
        other = "en" if get_language() == "es" else "es"
        theme.make_button(header, LANGUAGES[other], lambda: self.switch_language(other)).pack(
            side=tk.RIGHT, anchor=tk.N
        )
        theme.make_button(header, tr("Settings"), self.open_settings).pack(side=tk.RIGHT, anchor=tk.N, padx=5)
        theme.make_button(header, tr("History"), self.open_history).pack(side=tk.RIGHT, anchor=tk.N, padx=5)
        titles = ttk.Frame(header, style="App.TFrame")
        titles.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(titles, text=tr("SPEI receipt checker"), style="HeaderTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            titles,
            text=tr(
                "Drop SPEI receipts, monitor every file in real time, and download CEPs with clear "
                "diagnostics."
            ),
            style="HeaderSubtitle.TLabel",
        ).pack(anchor=tk.W, pady=(2, 0))

    def _build_stats(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent, style="App.TFrame")
        row.pack(fill=tk.X, pady=(0, 12))
        cards = [
            (tr("Loaded"), "loaded"),
            (tr("Processed"), "processed"),
            (tr("CEP Found"), "success"),
            (tr("Needs Review"), "review"),
            (tr("Not Found at Banxico"), "notfound"),
            (tr("Failed"), "failed"),
        ]
        for i, (title, key) in enumerate(cards):
            card = ttk.Frame(row, style="Card.TFrame", padding=(12, 10))
            ttk.Label(card, text=title, style="CardHint.TLabel").pack(anchor=tk.W)
            ttk.Label(card, textvariable=self.stat_vars[key], style="CardValue.TLabel").pack(
                anchor=tk.W, pady=(2, 0)
            )
            padx = (0, 8) if i == 0 else (4, 0) if i == len(cards) - 1 else 4
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=padx)

    def _build_actions(self, parent: ttk.Frame) -> None:
        bar = tk.Frame(parent, bg=theme.APP_BG)
        bar.pack(fill=tk.X, pady=(0, 10))
        theme.make_button(bar, tr("Add Files"), self.add_files).pack(side=tk.LEFT, padx=5)
        theme.make_button(bar, tr("Remove Selected"), self.remove_selected).pack(side=tk.LEFT, padx=5)
        theme.make_button(bar, tr("Edit Fields"), self.edit_selected).pack(side=tk.LEFT, padx=5)
        theme.make_button(bar, tr("Clear All"), self.clear_files, variant="danger").pack(side=tk.LEFT, padx=5)
        theme.make_button(bar, tr("Open CEP Folder"), self.open_cep_folder).pack(side=tk.LEFT, padx=5)
        self.process_button = theme.make_button(
            bar, tr("Process Files"), self.process_files, variant="primary"
        )
        self.process_button.pack(side=tk.RIGHT, padx=5)
        self.cancel_button = theme.make_button(
            bar,
            tr("Cancel"),
            self.cancel_processing,
            state=tk.NORMAL if self.processing and not self._cancel.is_set() else tk.DISABLED,
        )
        self.cancel_button.pack(side=tk.RIGHT, padx=5)
        if self.processing:
            self.process_button.configure(state=tk.DISABLED)

    def _build_queue_panel(self, workspace: ttk.Panedwindow) -> None:
        panel = ttk.Frame(workspace, style="Card.TFrame", padding=12)
        workspace.add(panel, weight=3)
        ttk.Label(panel, text=tr("Receipt Queue"), style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            panel,
            text=tr(
                "Drag and drop files, paste a screenshot ({shortcut}), or use Add Files.",
                shortcut=PASTE_SHORTCUT,
            ),
            style="CardHint.TLabel",
        ).pack(anchor=tk.W, pady=(0, 8))

        frame = ttk.Frame(panel, style="Card.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        tree = ttk.Treeview(
            frame,
            columns=("status", "result"),
            yscrollcommand=scrollbar.set,
            selectmode="extended",
            height=16,
            style="Modern.Treeview",
        )
        tree.heading("#0", text=tr("File"))
        tree.heading("status", text=tr("Status"))
        tree.heading("result", text=tr("Result"))
        tree.column("#0", width=460, anchor=tk.W)
        tree.column("status", width=120, anchor=tk.CENTER)
        tree.column("result", width=360, anchor=tk.W)
        for tag, color in theme.STATUS_COLORS.items():
            tree.tag_configure(tag, foreground=color)
        tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar.config(command=tree.yview)

        tree.drop_target_register(DND_FILES)
        tree.dnd_bind("<<Drop>>", self.on_drop)
        tree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected_details())
        tree.bind("<Double-1>", lambda _e: self.edit_selected())
        self.tree = tree

    def _build_side_panel(self, workspace: ttk.Panedwindow) -> None:
        panel = ttk.Frame(workspace, style="Card.TFrame", padding=12)
        workspace.add(panel, weight=2)
        ttk.Label(panel, text=tr("File Details"), style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            panel, text=tr("Select any row to inspect extracted fields and status."), style="CardHint.TLabel"
        ).pack(anchor=tk.W, pady=(0, 8))

        self.details_text = tk.Text(
            panel,
            height=18,
            bg="#F9FBFF",
            fg="#182234",
            insertbackground="#182234",
            relief=tk.FLAT,
            padx=12,
            pady=10,
            wrap=tk.WORD,
            font=theme.mono(10),
        )
        self.details_text.pack(fill=tk.BOTH, expand=True)
        self._set_details(tr("Select a file to view details."))

        ttk.Label(panel, text=tr("Batch Progress"), style="CardTitle.TLabel").pack(anchor=tk.W, pady=(12, 2))
        ttk.Label(
            panel, text=tr("Tracks processed files in the active queue."), style="CardHint.TLabel"
        ).pack(anchor=tk.W, pady=(0, 6))
        progress_row = ttk.Frame(panel, style="Card.TFrame")
        progress_row.pack(fill=tk.X, pady=(0, 8))
        self.progress = ttk.Progressbar(
            progress_row, mode="determinate", style="Modern.Horizontal.TProgressbar"
        )
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10), ipady=2)
        ttk.Label(progress_row, textvariable=self.progress_label_var, style="CardHint.TLabel").pack(
            side=tk.RIGHT
        )

        pending_row = ttk.Frame(panel, style="Card.TFrame")
        pending_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(pending_row, text=tr("Pending Files"), style="CardHint.TLabel").pack(side=tk.LEFT)
        ttk.Label(pending_row, textvariable=self.stat_vars["pending"], style="CardTitle.TLabel").pack(
            side=tk.RIGHT
        )

    # ------------------------------------------------------------------ queue management

    def _refuse_if_busy(self) -> bool:
        if self.processing:
            messagebox.showwarning(tr("Processing"), tr("Please wait until current processing finishes."))
        return self.processing

    def add_file(self, path: str) -> bool:
        """Queues a file. Returns False if it was already queued."""
        if path in self.items:
            return False
        item = QueueItem(path=path, tree_id="")
        item.tree_id = self.tree.insert(
            "", tk.END, text=os.path.basename(path), values=(item.status.label, item.result_text)
        )
        self.items[path] = item
        self._path_by_tree_id[item.tree_id] = path
        self._refresh_counters()
        return True

    def add_files(self) -> None:
        if self._refuse_if_busy():
            return
        for path in filedialog.askopenfilenames(title=tr("Select Documents"), filetypes=file_types()):
            self.add_file(path)

    def _add_dropped(self, paths: list[str]) -> None:
        duplicates = 0
        for path in paths:
            if Path(path).suffix.lower() not in SUPPORTED_EXTENSIONS:
                messagebox.showwarning(
                    tr("Invalid File"), tr("Only PDF or image files are accepted: {path}", path=path)
                )
            elif not self.add_file(path):
                duplicates += 1
        if duplicates:
            self.status_var.set(tr("Skipped {count} duplicate file(s)", count=duplicates))

    def on_drop(self, event: tk.Event) -> None:
        if self._refuse_if_busy():
            return
        self._add_dropped(list(self.tk.splitlist(event.data)))

    def on_paste(self, _event: tk.Event | None = None) -> None:
        if self._refuse_if_busy():
            return
        try:
            clipboard = ImageGrab.grabclipboard()
        except NotImplementedError:
            # Linux: Pillow reads the clipboard through wl-paste (Wayland) or xclip (X11).
            messagebox.showerror(
                tr("Paste Error"),
                tr("Pasting images needs wl-clipboard (Wayland) or xclip (X11). Install one and try again."),
            )
            return
        except Exception as e:
            messagebox.showerror(tr("Paste Error"), tr("Failed to read clipboard: {error}", error=e))
            return
        if isinstance(clipboard, list):  # files copied in the file manager
            self._add_dropped([str(p) for p in clipboard])
            return
        if not isinstance(clipboard, Image.Image):
            self.status_var.set(tr("No image found on clipboard"))
            return
        with tempfile.NamedTemporaryFile(prefix="cepxico_paste_", suffix=".png", delete=False) as tf:
            clipboard.save(tf, "PNG")
        self._temp_files.append(tf.name)
        self.add_file(tf.name)
        self.status_var.set(tr("Image pasted from clipboard"))

    def remove_selected(self) -> None:
        if self._refuse_if_busy():
            return
        for tree_id in self.tree.selection():
            path = self._path_by_tree_id.pop(tree_id, None)
            if path:
                del self.items[path]
                self.tree.delete(tree_id)
        self._refresh_counters()
        self._set_details(tr("Select a file to view details."))

    def clear_files(self) -> None:
        if self._refuse_if_busy():
            return
        self.tree.delete(*self.tree.get_children())
        self.items.clear()
        self._path_by_tree_id.clear()
        self.processed_count = 0
        self._refresh_counters()
        self._set_details(tr("Select a file to view details."))

    def _open(self, path: Path | str, title: str) -> None:
        try:
            open_path(path)
        except OSError as e:
            messagebox.showerror(title, tr("Couldn't open {path}: {error}", path=path, error=e))

    def open_cep_folder(self) -> None:
        self.cep_dir.mkdir(parents=True, exist_ok=True)
        self._open(self.cep_dir, tr("Open CEP Folder"))

    def open_history(self) -> None:
        HistoryDialog(self, history=self.history, on_open=lambda path: self._open(path, tr("History")))

    def open_settings(self) -> None:
        if self._refuse_if_busy():
            return
        SettingsDialog(self, settings=self.settings, on_save=self.apply_settings)

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
            self._rebuild_ui()
        self.status_var.set(tr("Settings saved"))
        return None

    def switch_language(self, code: str) -> None:
        """The header's language button: saves the choice and redraws the window."""
        problem = self.apply_settings(replace(self.settings, language=code))
        if problem:
            messagebox.showerror(tr("Settings"), problem)

    # ------------------------------------------------------------------ typing in fields

    def _selected_item(self) -> QueueItem | None:
        selection = self.tree.selection()
        return self.items.get(self._path_by_tree_id.get(selection[0], "")) if selection else None

    def edit_selected(self) -> None:
        if self._refuse_if_busy():
            return
        item = self._selected_item()
        if not item:
            messagebox.showinfo(tr("Edit Fields"), tr("Select a file first."))
            return
        if not can_edit(item):
            messagebox.showinfo(
                tr("Edit Fields"),
                tr("Fields can be edited for files that failed, weren't found at Banxico or need review."),
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
            self._set_status(path, ItemStatus.PENDING, tr("Edited, ready to check"))
        if check_now:
            self._start_batch([item])
        return {}

    # ------------------------------------------------------------------ display

    def _set_details(self, content: str) -> None:
        self.details_text.configure(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)
        self.details_text.insert(tk.END, content)
        self.details_text.configure(state=tk.DISABLED)

    def _show_selected_details(self) -> None:
        item = self._selected_item()
        if not item:
            self._set_details(tr("Select a file to view details."))
            return

        result = item.result
        payment = item.corrected or (result.payment if result else None)

        def show(value: object) -> str:
            return str(value) if value else tr("N/A")

        cep = result.cep if result else None
        pago_a_banco = bool(payment and payment.pago_a_banco)
        account_label = tr("Ordering account") if pago_a_banco else tr("Account")
        lines = [
            f"{tr('Path')}: {item.path}",
            f"{tr('Status')}: {item.status.label}",
            f"{tr('Result')}: {item.result_text}",
            "",
            f"{tr('Date')}: {show(payment and payment.payment_date)}",
            f"{tr('Clave de rastreo')}: {show(payment and payment.tracking_key)}",
            f"{account_label}: {show(payment and payment.beneficiary_account)}",
            f"{tr('Amount')}: {show(payment and payment.amount)}",
        ]
        if pago_a_banco:
            lines.append(tr("Pago a banco: paid to the receiving bank itself"))
        if payment and payment.spid:
            lines += ["", tr("Dollar transfer (SPID), checked at Banxico's CEP-SPID ({url})", url=SPID_URL)]
        lines += [
            "",
            # Bank as identified in Banxico's catalog, and how it was identified.
            f"{tr('Sending bank')}: {show(result and result.sender)}",
            f"{tr('Receiving bank')}: {show(result and result.receiver)}",
        ]
        if cep and cep.payment_status:
            lines.append(f"{tr('Status at Banxico')}: {cep.payment_status}")
        if cep and cep.record:
            # Banxico's own record of the transfer, read from the CEP's XML.
            r = cep.record

            def party(p: Party) -> str:
                return f"{show(p.name)} ({p.bank}, {show(p.account)})"

            lines += [
                "",
                f"Banxico: {r.operation_date} {r.time}",
                f"{tr('Sender')}: {party(r.sender)}",
                f"{tr('Beneficiary')}: {party(r.beneficiary)}",
                f"{tr('Concept')}: {show(r.concept)}",
            ]
        if cep and cep.saved_path:  # name only: Open CEP Folder shows where it is
            lines += ["", f"CEP: {cep.saved_path.name}"]
        if payment and payment.edited_fields:
            typed = ", ".join(field_label(name) for name in payment.edited_fields)
            lines += ["", f"{tr('Typed by user')}: {typed}"]
        if can_edit(item):
            lines += ["", tr("Double-click the file (or Edit Fields) to correct or fill in fields.")]
        self._set_details("\n".join(lines))

    def _set_status(self, path: str, status: ItemStatus, text: str) -> None:
        item = self.items.get(path)
        if not item:
            return
        item.status, item.result_text = status, text
        self.tree.item(item.tree_id, values=(status.label, text), tags=(status.tag,))
        if item.tree_id in self.tree.selection():
            self._show_selected_details()
        self._refresh_counters()

    def _count(self, status: ItemStatus) -> int:
        return sum(1 for item in self.items.values() if item.status is status)

    def _refresh_counters(self) -> None:
        total = len(self.items)
        # Files with a result, whether from this batch or an earlier one (confirmed files
        # a batch skips count as done).
        done = sum(1 for item in self.items.values() if item.status in FINISHED_STATUSES)
        self.progress.configure(maximum=max(total, 1), value=done)
        self.progress_label_var.set(f"{done} / {total}")
        self.stat_vars["loaded"].set(str(total))
        self.stat_vars["processed"].set(str(self.processed_count))
        self.stat_vars["success"].set(str(self._count(ItemStatus.SUCCESS)))
        self.stat_vars["review"].set(str(self._count(ItemStatus.REVIEW)))
        self.stat_vars["notfound"].set(str(self._count(ItemStatus.NOT_FOUND)))
        self.stat_vars["failed"].set(str(self._count(ItemStatus.FAILED)))
        self.stat_vars["pending"].set(str(self._count(ItemStatus.PENDING)))

    # ------------------------------------------------------------------ processing

    def process_files(self) -> None:
        if self._refuse_if_busy():
            return
        if not self.items:
            messagebox.showwarning(tr("No Files"), tr("No files to process."))
            return
        to_check = [item for item in self.items.values() if not is_confirmed(item)]
        if not to_check:
            messagebox.showinfo(
                tr("Nothing to Check"),
                tr(
                    "Every file is already confirmed at Banxico.\n\n"
                    "To check a file again, remove it and add it back."
                ),
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
        self.status_var.set(tr("Processing files..."))
        self.process_button.configure(state=tk.DISABLED)
        self.cancel_button.configure(state=tk.NORMAL)
        for item in to_check:
            item.result = None
            self._set_status(item.path, ItemStatus.PENDING, tr("Queued"))

        paths = [item.path for item in to_check]
        payments = {item.path: item.corrected for item in to_check if item.corrected}
        threading.Thread(target=self._worker, args=(paths, payments), daemon=True).start()

    def cancel_processing(self) -> None:
        if self.processing:
            self._cancel.set()
            self.status_var.set(tr("Cancel requested. Stopping after the files in progress..."))
            self.cancel_button.configure(state=tk.DISABLED)

    def _worker(self, paths: list[str], payments: dict[str, PaymentData]) -> None:
        """Runs in a background thread. It never touches Tk directly: UI updates go
        through self._ui_queue and are applied on the Tk thread by _drain_ui_queue()."""
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
        """Runs on a worker thread: shows Banxico's security image on the Tk thread and
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
        if self._code_dialog is not None and self._code_dialog.winfo_exists():
            self._code_dialog.destroy()
        self._code_dialog = None

    def _post_to_ui(self, func: Callable[..., object], *args: object) -> None:
        """Thread-safe: schedules func(*args) on the Tk thread."""
        self._ui_queue.put((func, args))

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                func, args = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            func(*args)
        self.after(UI_POLL_MS, self._drain_ui_queue)

    def _on_file_done(self, path: str, result: FileResult) -> None:
        item = self.items.get(path)
        if item:
            item.result = result
        self.processed_count += 1
        message = result.message
        if result.payment and result.payment.edited_fields:
            message += f"  [{tr('edited')}]"  # checked with fields the user typed in
        self._set_status(path, OUTCOME_STATUS[result.outcome], message)
        self.status_var.set(
            tr(
                "Processed {done}/{total}: {name}",
                done=self.processed_count,
                total=self._batch_size,
                name=os.path.basename(path),
            )
        )

    def _mark_cancelled(self, paths: list[str]) -> None:
        for path in paths:
            item = self.items.get(path)
            if item and item.status is ItemStatus.PENDING:
                self._set_status(path, ItemStatus.CANCELLED, tr("Skipped by user"))

    def _on_batch_done(self) -> None:
        self.processing = False
        self.process_button.configure(state=tk.NORMAL)
        self.cancel_button.configure(state=tk.DISABLED)
        cancelled = self._cancel.is_set()
        self.status_var.set(tr("Processing cancelled by user") if cancelled else tr("Processing complete"))
        self._refresh_counters()
        messagebox.showinfo(tr("Processing Summary"), self._summary(cancelled))

    def _summary(self, cancelled: bool) -> str:
        def files_with(status: ItemStatus) -> list[QueueItem]:
            return [item for item in self.items.values() if item.status is status]

        def listed(items: list[QueueItem]) -> list[str]:
            return [f"- {os.path.basename(i.path)}: {i.result_text}" for i in items]

        found, not_found = files_with(ItemStatus.SUCCESS), files_with(ItemStatus.NOT_FOUND)
        review = files_with(ItemStatus.REVIEW)
        failed, skipped = files_with(ItemStatus.FAILED), files_with(ItemStatus.CANCELLED)

        lines = [
            tr("Processing Cancelled") if cancelled else tr("Processing Complete"),
            "",
            tr("Total files loaded: {count}", count=len(self.items)),
            tr("Processed: {count}", count=self.processed_count),
        ]
        if self._skipped_confirmed:
            lines.append(tr("Already confirmed, not checked again: {count}", count=self._skipped_confirmed))
        lines.append(tr("CEP found and saved: {count}", count=len(found)))
        if skipped:
            lines.append(tr("Cancelled: {count}", count=len(skipped)))
        if found:
            lines.append(tr("CEPs saved to: {folder}", folder=self.cep_dir))
        if review:
            lines += [
                "",
                tr(
                    "NEEDS REVIEW ({count}) - a real payment, but not a clean confirmation:",
                    count=len(review),
                ),
            ]
            lines += listed(review)
        if not_found:
            lines += [
                "",
                tr(
                    "NOT FOUND at Banxico ({count}) - check the extracted data; the receipt may be fake:",
                    count=len(not_found),
                ),
            ]
            lines += listed(not_found)
        if failed:
            lines += ["", tr("Errors ({count}):", count=len(failed))]
            lines += listed(failed)
        return "\n".join(lines)

    # ------------------------------------------------------------------ shutdown

    def _on_close(self) -> None:
        for path in self._temp_files:
            with contextlib.suppress(OSError):
                os.remove(path)
        self.destroy()
