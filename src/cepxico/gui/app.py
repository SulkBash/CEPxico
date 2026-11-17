"""Tkinter desktop app: queue receipts, process them in the background, inspect results."""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import tempfile
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageGrab
from tkinterdnd2 import DND_FILES, TkinterDnD

from cepxico.extraction import SUPPORTED_EXTENSIONS
from cepxico.gui import theme
from cepxico.pipeline import FileResult, Outcome
from cepxico.pipeline import process_files as run_batch

logger = logging.getLogger(__name__)


class ItemStatus(Enum):
    PENDING = ("Pending", "status_pending")
    PROCESSING = ("Processing", "status_processing")
    SUCCESS = ("Success", "status_success")
    NOT_FOUND = ("Not Found", "status_notfound")
    FAILED = ("Failed", "status_failed")
    CANCELLED = ("Cancelled", "status_cancelled")

    def __init__(self, label: str, tag: str):
        self.label = label
        self.tag = tag


OUTCOME_STATUS = {
    Outcome.SUCCESS: ItemStatus.SUCCESS,
    Outcome.NOT_FOUND: ItemStatus.NOT_FOUND,
    Outcome.FAILED: ItemStatus.FAILED,
}

UI_POLL_MS = 50  # how often the Tk thread applies updates posted by the worker
BUSY_TITLE = "Processing"
BUSY_MESSAGE = "Please wait until current processing finishes."
NO_SELECTION_TEXT = "Select a file to view details."
FILE_TYPES = [
    ("Documents & Images", " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))),
    ("All Files", "*.*"),
]


@dataclass
class QueueItem:
    path: str
    tree_id: str
    status: ItemStatus = ItemStatus.PENDING
    result_text: str = "Ready"
    result: FileResult | None = None


class CEPApp(TkinterDnD.Tk):
    def __init__(self, cep_dir: Path):
        super().__init__()
        self.cep_dir = Path(cep_dir)
        self.items: dict[str, QueueItem] = {}  # insertion-ordered queue, keyed by file path
        self._path_by_tree_id: dict[str, str] = {}
        self._temp_files: list[str] = []  # pasted clipboard images, deleted on exit
        self.processing = False
        self.processed_count = 0
        self._cancel = threading.Event()
        self._ui_queue: queue.Queue[tuple[Callable[..., object], tuple[object, ...]]] = queue.Queue()

        self.title("Banxico CEP Processor")
        self.geometry("1180x780")
        self.minsize(1080, 700)
        self.configure(bg=theme.APP_BG)
        theme.apply(self)

        self.stat_vars = {
            name: tk.StringVar(value="0")
            for name in ("loaded", "processed", "success", "notfound", "failed", "pending")
        }
        self.status_var = tk.StringVar(value="Ready")
        self.progress_label_var = tk.StringVar(value="0 / 0")

        self._build_ui()
        self.bind("<Control-v>", self.on_paste)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(UI_POLL_MS, self._drain_ui_queue)

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=16, style="App.TFrame")
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

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent, style="App.TFrame")
        header.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(header, text="Banxico CEP Processor", style="HeaderTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            header,
            text="Drop SPEI receipts, monitor every file in real time, and download CEPs with clear "
            "diagnostics.",
            style="HeaderSubtitle.TLabel",
        ).pack(anchor=tk.W, pady=(2, 0))

    def _build_stats(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent, style="App.TFrame")
        row.pack(fill=tk.X, pady=(0, 12))
        cards = [
            ("Loaded", "loaded"),
            ("Processed", "processed"),
            ("CEP Found", "success"),
            ("Not Found at Banxico", "notfound"),
            ("Failed", "failed"),
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
        theme.make_button(bar, "Add Files", self.add_files).pack(side=tk.LEFT, padx=5)
        theme.make_button(bar, "Remove Selected", self.remove_selected).pack(side=tk.LEFT, padx=5)
        theme.make_button(bar, "Clear All", self.clear_files, variant="danger").pack(side=tk.LEFT, padx=5)
        theme.make_button(bar, "Open CEP Folder", self.open_cep_folder).pack(side=tk.LEFT, padx=5)
        self.process_button = theme.make_button(bar, "Process Files", self.process_files, variant="primary")
        self.process_button.pack(side=tk.RIGHT, padx=5)
        self.cancel_button = theme.make_button(bar, "Cancel", self.cancel_processing, state=tk.DISABLED)
        self.cancel_button.pack(side=tk.RIGHT, padx=5)

    def _build_queue_panel(self, workspace: ttk.Panedwindow) -> None:
        panel = ttk.Frame(workspace, style="Card.TFrame", padding=12)
        workspace.add(panel, weight=3)
        ttk.Label(panel, text="Receipt Queue", style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            panel,
            text="Drag and drop files, paste a screenshot (Ctrl+V), or use Add Files.",
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
        tree.heading("#0", text="File")
        tree.heading("status", text="Status")
        tree.heading("result", text="Result")
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
        self.tree = tree

    def _build_side_panel(self, workspace: ttk.Panedwindow) -> None:
        panel = ttk.Frame(workspace, style="Card.TFrame", padding=12)
        workspace.add(panel, weight=2)
        ttk.Label(panel, text="File Details", style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            panel, text="Select any row to inspect extracted fields and status.", style="CardHint.TLabel"
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
            font=(theme.FONT_MONO, 10),
        )
        self.details_text.pack(fill=tk.BOTH, expand=True)
        self._set_details(NO_SELECTION_TEXT)

        ttk.Label(panel, text="Batch Progress", style="CardTitle.TLabel").pack(anchor=tk.W, pady=(12, 2))
        ttk.Label(panel, text="Tracks processed files in the active queue.", style="CardHint.TLabel").pack(
            anchor=tk.W, pady=(0, 6)
        )
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
        ttk.Label(pending_row, text="Pending Files", style="CardHint.TLabel").pack(side=tk.LEFT)
        ttk.Label(pending_row, textvariable=self.stat_vars["pending"], style="CardTitle.TLabel").pack(
            side=tk.RIGHT
        )

    # ------------------------------------------------------------------ queue management

    def _refuse_if_busy(self) -> bool:
        if self.processing:
            messagebox.showwarning(BUSY_TITLE, BUSY_MESSAGE)
        return self.processing

    def add_file(self, path: str) -> bool:
        """Queues a file. Returns False if it was already queued."""
        if path in self.items:
            return False
        tree_id = self.tree.insert(
            "", tk.END, text=os.path.basename(path), values=(ItemStatus.PENDING.label, "Ready")
        )
        self.items[path] = QueueItem(path=path, tree_id=tree_id)
        self._path_by_tree_id[tree_id] = path
        self._refresh_counters()
        return True

    def add_files(self) -> None:
        if self._refuse_if_busy():
            return
        for path in filedialog.askopenfilenames(title="Select Documents", filetypes=FILE_TYPES):
            self.add_file(path)

    def on_drop(self, event: tk.Event) -> None:
        if self._refuse_if_busy():
            return
        duplicates = 0
        for path in self.tk.splitlist(event.data):
            if Path(path).suffix.lower() not in SUPPORTED_EXTENSIONS:
                messagebox.showwarning("Invalid File", f"Only PDF or image files are accepted: {path}")
            elif not self.add_file(path):
                duplicates += 1
        if duplicates:
            self.status_var.set(f"Skipped {duplicates} duplicate file(s)")

    def on_paste(self, _event: tk.Event | None = None) -> None:
        if self._refuse_if_busy():
            return
        try:
            image = ImageGrab.grabclipboard()
        except Exception as e:
            messagebox.showerror("Paste Error", f"Failed to read clipboard: {e}")
            return
        if not isinstance(image, Image.Image):
            self.status_var.set("No image found on clipboard")
            return
        with tempfile.NamedTemporaryFile(prefix="cepxico_paste_", suffix=".png", delete=False) as tf:
            image.save(tf, "PNG")
        self._temp_files.append(tf.name)
        self.add_file(tf.name)
        self.status_var.set("Image pasted from clipboard")

    def remove_selected(self) -> None:
        if self._refuse_if_busy():
            return
        for tree_id in self.tree.selection():
            path = self._path_by_tree_id.pop(tree_id, None)
            if path:
                del self.items[path]
                self.tree.delete(tree_id)
        self._refresh_counters()
        self._set_details(NO_SELECTION_TEXT)

    def clear_files(self) -> None:
        if self._refuse_if_busy():
            return
        self.tree.delete(*self.tree.get_children())
        self.items.clear()
        self._path_by_tree_id.clear()
        self.processed_count = 0
        self._refresh_counters()
        self._set_details(NO_SELECTION_TEXT)

    def open_cep_folder(self) -> None:
        self.cep_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(self.cep_dir)  # noqa: S606 - Windows-only app

    # ------------------------------------------------------------------ display

    def _set_details(self, content: str) -> None:
        self.details_text.configure(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)
        self.details_text.insert(tk.END, content)
        self.details_text.configure(state=tk.DISABLED)

    def _show_selected_details(self) -> None:
        selection = self.tree.selection()
        item = self.items.get(self._path_by_tree_id.get(selection[0], "")) if selection else None
        if not item:
            self._set_details(NO_SELECTION_TEXT)
            return

        result = item.result
        payment = result.payment if result else None

        def show(value: object) -> str:
            return str(value) if value else "N/A"

        lines = [
            f"Path: {item.path}",
            f"Status: {item.status.label}",
            f"Result: {item.result_text}",
            "",
            f"Fecha: {show(payment and payment.payment_date)}",
            f"Rastreo: {show(payment and payment.tracking_key)}",
            f"Cuenta: {show(payment and payment.beneficiary_account)}",
            f"Monto: {show(payment and payment.amount)}",
            "",
            # Bank as identified in Banxico's catalog, and how it was identified.
            f"Emisor: {show(result and result.sender)}",
            f"Receptor: {show(result and result.receiver)}",
            f"CEP file: {show(result and result.cep and result.cep.pdf_path)}",
        ]
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
        done = min(self.processed_count, total)
        self.progress.configure(maximum=max(total, 1), value=done)
        self.progress_label_var.set(f"{done} / {total}")
        self.stat_vars["loaded"].set(str(total))
        self.stat_vars["processed"].set(str(self.processed_count))
        self.stat_vars["success"].set(str(self._count(ItemStatus.SUCCESS)))
        self.stat_vars["notfound"].set(str(self._count(ItemStatus.NOT_FOUND)))
        self.stat_vars["failed"].set(str(self._count(ItemStatus.FAILED)))
        self.stat_vars["pending"].set(str(self._count(ItemStatus.PENDING)))

    # ------------------------------------------------------------------ processing

    def process_files(self) -> None:
        if self._refuse_if_busy():
            return
        if not self.items:
            messagebox.showwarning("No Files", "No files to process.")
            return

        self.processing = True
        self._cancel.clear()
        self.processed_count = 0
        self.status_var.set("Processing files...")
        self.process_button.configure(state=tk.DISABLED)
        self.cancel_button.configure(state=tk.NORMAL)
        for item in self.items.values():
            item.result = None
            self._set_status(item.path, ItemStatus.PENDING, "Queued")

        threading.Thread(target=self._worker, args=(list(self.items),), daemon=True).start()

    def cancel_processing(self) -> None:
        if self.processing:
            self._cancel.set()
            self.status_var.set("Cancel requested. Stopping after the files in progress...")
            self.cancel_button.configure(state=tk.DISABLED)

    def _worker(self, paths: list[str]) -> None:
        """Runs in a background thread. It never touches Tk directly: UI updates go
        through self._ui_queue and are applied on the Tk thread by _drain_ui_queue()."""
        post = self._post_to_ui

        def on_step(path: str, step: str) -> None:
            post(self._set_status, path, ItemStatus.PROCESSING, step)

        def on_done(path: str, result: FileResult) -> None:
            post(self._on_file_done, path, result)

        try:
            results = run_batch(paths, self.cep_dir, on_step=on_step, on_done=on_done, cancel=self._cancel)
            skipped = [path for path, result in zip(paths, results, strict=True) if result is None]
            if skipped:
                post(self._mark_cancelled, skipped)
        except Exception:
            logger.exception("Batch processing failed")
        finally:
            post(self._on_batch_done)

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
        self._set_status(path, OUTCOME_STATUS[result.outcome], result.message)
        self.status_var.set(f"Processed {self.processed_count}/{len(self.items)}: {os.path.basename(path)}")

    def _mark_cancelled(self, paths: list[str]) -> None:
        for path in paths:
            item = self.items.get(path)
            if item and item.status is ItemStatus.PENDING:
                self._set_status(path, ItemStatus.CANCELLED, "Skipped by user")

    def _on_batch_done(self) -> None:
        self.processing = False
        self.process_button.configure(state=tk.NORMAL)
        self.cancel_button.configure(state=tk.DISABLED)
        cancelled = self._cancel.is_set()
        self.status_var.set("Processing cancelled by user" if cancelled else "Processing complete")
        self._refresh_counters()
        messagebox.showinfo("Processing Summary", self._summary(cancelled))

    def _summary(self, cancelled: bool) -> str:
        def files_with(status: ItemStatus) -> list[QueueItem]:
            return [item for item in self.items.values() if item.status is status]

        found, not_found = files_with(ItemStatus.SUCCESS), files_with(ItemStatus.NOT_FOUND)
        failed, skipped = files_with(ItemStatus.FAILED), files_with(ItemStatus.CANCELLED)

        lines = [
            "Processing Cancelled" if cancelled else "Processing Complete",
            "",
            f"Total files loaded: {len(self.items)}",
            f"Processed: {self.processed_count}",
            f"CEP found and saved: {len(found)}",
        ]
        if skipped:
            lines.append(f"Cancelled: {len(skipped)}")
        if found:
            lines.append(f"CEPs saved to: {self.cep_dir}")
        if not_found:
            lines += [
                "",
                f"NOT FOUND at Banxico ({len(not_found)}) - "
                "check the extracted data; the receipt may be fake:",
            ]
            lines += [f"- {os.path.basename(i.path)}: {i.result_text}" for i in not_found]
        if failed:
            lines += ["", f"Errors ({len(failed)}):"]
            lines += [f"- {os.path.basename(i.path)}: {i.result_text}" for i in failed]
        return "\n".join(lines)

    # ------------------------------------------------------------------ shutdown

    def _on_close(self) -> None:
        for path in self._temp_files:
            with contextlib.suppress(OSError):
                os.remove(path)
        self.destroy()
