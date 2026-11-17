"""History window: every receipt checked on this computer, searchable, exportable as CSV."""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from cepxico.gui import theme
from cepxico.history import Check, History, outcome_label, write_csv
from cepxico.i18n import tr

logger = logging.getLogger(__name__)

OUTCOME_TAGS = {
    "success": "status_success",
    "review": "status_review",
    "not_found": "status_notfound",
    "failed": "status_failed",
}


def matches(check: Check, query: str) -> bool:
    """Whether a check matches every word of a search (file, clave, amount, names, banks...)."""
    haystack = " ".join(
        [
            check.file_name,
            check.tracking_key,
            check.amount,
            check.account,
            check.sender_name,
            check.beneficiary_name,
            check.sender_bank,
            check.receiver_bank,
            check.payment_date,
            check.message,
            outcome_label(check.outcome),
        ]
    ).lower()
    return all(word in haystack for word in query.lower().split())


class HistoryDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, *, history: History, on_open: Callable[[Path], None]):
        super().__init__(parent)
        self.title(tr("History"))
        self.configure(bg=theme.CARD_BG)
        self.geometry("1100x560")
        self.transient(parent)  # type: ignore[arg-type]
        self._history = history
        self._on_open = on_open
        self._checks: list[Check] = []
        self.shown: list[Check] = []  # rows in the table, in order
        self.search = tk.StringVar()

        body = ttk.Frame(self, style="Card.TFrame", padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=tr("Every receipt checked on this computer"), style="CardTitle.TLabel").pack(
            anchor=tk.W
        )
        ttk.Label(
            body,
            text=tr(
                "Kept to catch receipts used twice and for your records. "
                "Search by file, clave de rastreo, amount, name or bank."
            ),
            style="CardHint.TLabel",
        ).pack(anchor=tk.W, pady=(0, 8))

        search_row = ttk.Frame(body, style="Card.TFrame")
        search_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(search_row, text=tr("Search"), style="CardHint.TLabel").pack(side=tk.LEFT, padx=(0, 8))
        entry = ttk.Entry(search_row, textvariable=self.search, font=theme.font(10))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.count_label = ttk.Label(search_row, style="CardHint.TLabel")
        self.count_label.pack(side=tk.RIGHT, padx=(8, 0))

        # Packed before the table so a short window shrinks the table, not the buttons.
        buttons = tk.Frame(body, bg=theme.CARD_BG)
        buttons.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        frame = ttk.Frame(body, style="Card.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        columns = {
            "checked": (tr("Checked"), 120),
            "file": (tr("File"), 180),
            "result": (tr("Result"), 90),
            "clave": (tr("Clave de rastreo"), 200),
            "amount": (tr("Amount"), 90),
            "sender": (tr("Sender"), 160),
            "beneficiary": (tr("Beneficiary"), 160),
            "details": (tr("Details"), 300),
        }
        self.tree = ttk.Treeview(
            frame,
            columns=list(columns),
            show="headings",
            yscrollcommand=scrollbar.set,
            selectmode="browse",
            style="Modern.Treeview",
        )
        for key, (title, width) in columns.items():
            self.tree.heading(key, text=title)
            self.tree.column(
                key, width=width, anchor=tk.E if key == "amount" else tk.W, stretch=key == "details"
            )
        for tag, color in theme.STATUS_COLORS.items():
            self.tree.tag_configure(tag, foreground=color)
        self.tree.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.tree.yview)
        self.tree.bind("<Double-1>", lambda _e: self.open_cep())

        theme.make_button(buttons, tr("Open CEP"), self.open_cep).pack(side=tk.LEFT)
        theme.make_button(buttons, tr("Forget"), self.forget, variant="danger").pack(side=tk.LEFT, padx=6)
        theme.make_button(buttons, tr("Close"), self.destroy).pack(side=tk.RIGHT)
        theme.make_button(buttons, tr("Export CSV..."), self.export, variant="primary").pack(
            side=tk.RIGHT, padx=6
        )

        self.search.trace_add("write", lambda *_: self.refresh())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.reload()
        entry.focus_set()

    def reload(self) -> None:
        try:
            self._checks = self._history.checks()
        except Exception as e:  # a damaged or locked history file mustn't break the window
            logger.exception("Couldn't read the history")
            messagebox.showerror(
                tr("History"), tr("Couldn't read the history: {error}", error=e), parent=self
            )
            self._checks = []
        self.refresh()

    def refresh(self) -> None:
        query = self.search.get().strip()
        self.shown = [c for c in self._checks if matches(c, query)] if query else list(self._checks)
        self.tree.delete(*self.tree.get_children())
        for i, check in enumerate(self.shown):
            self.tree.insert(
                "",
                tk.END,
                iid=str(i),
                values=(
                    check.checked_at_text,
                    check.file_name,
                    outcome_label(check.outcome),
                    check.tracking_key,
                    check.amount,
                    check.sender_name or check.sender_bank,
                    check.beneficiary_name or check.receiver_bank,
                    check.message,
                ),
                tags=(OUTCOME_TAGS.get(check.outcome, ""),),
            )
        self.count_label.configure(
            text=tr("{shown} of {total}", shown=len(self.shown), total=len(self._checks))
        )

    def selected(self) -> Check | None:
        selection = self.tree.selection()
        return self.shown[int(selection[0])] if selection else None

    def open_cep(self) -> None:
        check = self.selected()
        if not check:
            messagebox.showinfo(tr("Open CEP"), tr("Select a row first."), parent=self)
        elif not check.cep_file or not Path(check.cep_file).is_file():
            messagebox.showinfo(
                tr("Open CEP"), tr("No CEP file for this check on this computer."), parent=self
            )
        else:
            self._on_open(Path(check.cep_file))

    def forget(self) -> None:
        check = self.selected()
        if not check:
            messagebox.showinfo(tr("Forget"), tr("Select a row first."), parent=self)
            return
        sure = messagebox.askyesno(
            tr("Forget"),
            tr(
                "Forget the check of {file} on {date}? If Banxico confirmed it, its transfer no "
                "longer counts as used, so another receipt for it can pass.",
                file=check.file_name,
                date=check.checked_at_text,
            ),
            parent=self,
        )
        if not sure:
            return
        try:
            self._history.forget(check)
        except Exception as e:  # a locked or damaged history file
            logger.exception("Couldn't forget a check")
            messagebox.showerror(
                tr("Forget"), tr("Couldn't change the history: {error}", error=e), parent=self
            )
            return
        self.reload()

    def export(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title=tr("Export CSV..."),
            defaultextension=".csv",
            initialfile=f"cepxico_{date.today():%Y-%m-%d}.csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        try:
            write_csv(path, self.shown)
        except OSError as e:
            messagebox.showerror(
                tr("Export CSV..."), tr("Couldn't write the file: {error}", error=e), parent=self
            )
            return
        messagebox.showinfo(
            tr("Export CSV..."),
            tr("Wrote {count} checks to {file}", count=len(self.shown), file=path),
            parent=self,
        )
