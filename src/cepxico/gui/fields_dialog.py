"""Dialog for typing in receipt fields the app read wrong or couldn't read."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import ttk

from cepxico.gui import theme
from cepxico.models import FIELD_LABELS

ERROR_COLOR = theme.STATUS_COLORS["status_failed"]
HINTS = {
    "payment_date": "day/month/year",
    "sender_bank": "name Banxico uses, e.g. BANORTE",
    "receiver_bank": "not needed with a valid CLABE",
    "beneficiary_account": "CLABE, debit card or phone",
}

# Called with the changed fields ({field: typed text}) and whether to check at Banxico
# right away; returns {field: problem} for values that aren't valid ({} = saved).
SaveHandler = Callable[[dict[str, str], bool], Mapping[str, str]]


class FieldsDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        filename: str,
        initial: Mapping[str, str],
        on_save: SaveHandler,
        on_open_receipt: Callable[[], None],
    ):
        super().__init__(parent)
        self.title("Edit Fields")
        self.configure(bg=theme.CARD_BG)
        self.resizable(False, False)
        self.transient(parent)  # type: ignore[arg-type]
        self._initial = dict(initial)
        self._on_save = on_save
        self.vars = {name: tk.StringVar(value=initial.get(name, "")) for name in FIELD_LABELS}
        self.notes: dict[str, tk.Label] = {}  # under each field: its hint, or its problem

        body = ttk.Frame(self, style="Card.TFrame", padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=filename, style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky=tk.W
        )
        ttk.Label(
            body,
            text="Fix anything read wrong and fill in what's missing, copying from the receipt.",
            style="CardHint.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        first_empty = None
        for i, (name, label) in enumerate(FIELD_LABELS.items()):
            row = 2 + 2 * i
            ttk.Label(body, text=label.capitalize(), style="CardHint.TLabel").grid(
                row=row, column=0, sticky=tk.W, padx=(0, 12)
            )
            entry = ttk.Entry(body, textvariable=self.vars[name], width=42, font=(theme.FONT, 10))
            entry.grid(row=row, column=1, sticky=tk.EW, pady=(4, 0))
            if first_empty is None and not self.vars[name].get():
                first_empty = entry
            note = tk.Label(
                body, bg=theme.CARD_BG, font=(theme.FONT, 8), anchor=tk.W, justify=tk.LEFT, wraplength=330
            )
            note.grid(row=row + 1, column=1, sticky=tk.W)
            self.notes[name] = note
            self._show_note(name, None)

        buttons = tk.Frame(body, bg=theme.CARD_BG)
        buttons.grid(row=2 + 2 * len(FIELD_LABELS), column=0, columnspan=2, sticky=tk.EW, pady=(14, 0))
        theme.make_button(buttons, "Open Receipt", on_open_receipt).pack(side=tk.LEFT)
        theme.make_button(
            buttons, "Save and Check", lambda: self.save(check_now=True), variant="primary"
        ).pack(side=tk.RIGHT)
        theme.make_button(buttons, "Save", lambda: self.save(check_now=False)).pack(side=tk.RIGHT, padx=6)
        theme.make_button(buttons, "Cancel", self.destroy).pack(side=tk.RIGHT)

        self.bind("<Return>", lambda _e: self.save(check_now=True))
        self.bind("<Escape>", lambda _e: self.destroy())
        (first_empty or body).focus_set()
        self.grab_set()  # modal: the queue can't change while editing

    def changed_values(self) -> dict[str, str]:
        """Fields whose text differs from what the dialog opened with."""
        return {
            name: var.get()
            for name, var in self.vars.items()
            if var.get().strip() != self._initial.get(name, "").strip()
        }

    def _show_note(self, name: str, error: str | None) -> None:
        if error:
            self.notes[name].configure(text=error, fg=ERROR_COLOR)
        else:
            self.notes[name].configure(text=HINTS.get(name, ""), fg=theme.TEXT_MUTED)

    def save(self, *, check_now: bool) -> None:
        errors = self._on_save(self.changed_values(), check_now)
        for name in self.notes:
            self._show_note(name, errors.get(name))
        if not errors:
            self.destroy()
