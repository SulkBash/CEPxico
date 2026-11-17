"""Dialog for typing in receipt fields the app read wrong or couldn't read."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import ttk

from cepxico.gui import theme
from cepxico.i18n import tr
from cepxico.models import FIELD_NAMES, field_label

ERROR_COLOR = theme.STATUS_COLORS["status_failed"]


def hints(pago_a_banco: bool) -> dict[str, str]:
    """What goes in each field, shown under it."""
    if pago_a_banco:
        return {
            "payment_date": tr("day/month/year"),
            "sender_bank": tr("name Banxico uses, e.g. BANORTE"),
            "receiver_bank": tr("the bank that was paid"),
            "beneficiary_account": tr("the account the payment came from (CLABE, card or phone)"),
        }
    return {
        "payment_date": tr("day/month/year"),
        "sender_bank": tr("name Banxico uses, e.g. BANORTE"),
        "receiver_bank": tr("not needed with a valid CLABE"),
        "beneficiary_account": tr("CLABE, debit card or phone"),
    }


def account_label(pago_a_banco: bool) -> str:
    return tr("Ordering account") if pago_a_banco else tr("Beneficiary account")


# Called with the changed fields ({field: typed text}, plus "pago_a_banco"/"spid": "1"/"0"
# if those boxes changed) and whether to check at Banxico right away; returns
# {field: problem} for values that aren't valid ({} = saved).
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
        self.title(tr("Edit Fields"))
        self.configure(bg=theme.CARD_BG)
        self.resizable(False, False)
        self.transient(parent)  # type: ignore[arg-type]
        self._initial = dict(initial)
        self._on_save = on_save
        self.vars = {name: tk.StringVar(value=initial.get(name, "")) for name in FIELD_NAMES}
        self.pago_a_banco = tk.BooleanVar(value=initial.get("pago_a_banco") == "1")
        self.spid = tk.BooleanVar(value=initial.get("spid") == "1")
        self.notes: dict[str, tk.Label] = {}  # under each field: its hint, or its problem
        self.labels: dict[str, ttk.Label] = {}

        body = ttk.Frame(self, style="Card.TFrame", padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=filename, style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky=tk.W
        )
        ttk.Label(
            body,
            text=tr("Fix anything read wrong and fill in what's missing, copying from the receipt."),
            style="CardHint.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        first_empty = None
        for i, name in enumerate(FIELD_NAMES):
            row = 2 + 2 * i
            self.labels[name] = ttk.Label(body, text=field_label(name).capitalize(), style="CardHint.TLabel")
            self.labels[name].grid(row=row, column=0, sticky=tk.W, padx=(0, 12))
            entry = ttk.Entry(body, textvariable=self.vars[name], width=42, font=theme.font(10))
            entry.grid(row=row, column=1, sticky=tk.EW, pady=(4, 0))
            if first_empty is None and not self.vars[name].get():
                first_empty = entry
            note = tk.Label(
                body, bg=theme.CARD_BG, font=theme.font(8), anchor=tk.W, justify=tk.LEFT, wraplength=330
            )
            note.grid(row=row + 1, column=1, sticky=tk.W)
            self.notes[name] = note
            self._show_note(name, None)

        last_row = 2 + 2 * len(FIELD_NAMES)
        ttk.Checkbutton(
            body,
            text=tr("Pago a banco: paid to the receiving bank itself, not to one of its customers"),
            variable=self.pago_a_banco,
            command=self._update_pago_a_banco,
            style="Card.TCheckbutton",
        ).grid(row=last_row, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        ttk.Checkbutton(
            body,
            text=tr(
                "Dollar transfer (SPID): checked at Banxico's CEP-SPID, which asks you to type "
                "a security image"
            ),
            variable=self.spid,
            style="Card.TCheckbutton",
        ).grid(row=last_row + 1, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))
        self._update_pago_a_banco()

        buttons = tk.Frame(body, bg=theme.CARD_BG)
        buttons.grid(row=last_row + 2, column=0, columnspan=2, sticky=tk.EW, pady=(14, 0))
        theme.make_button(buttons, tr("Open Receipt"), on_open_receipt).pack(side=tk.LEFT)
        theme.make_button(
            buttons, tr("Save and Check"), lambda: self.save(check_now=True), variant="primary"
        ).pack(side=tk.RIGHT)
        theme.make_button(buttons, tr("Save"), lambda: self.save(check_now=False)).pack(side=tk.RIGHT, padx=6)
        theme.make_button(buttons, tr("Cancel"), self.destroy).pack(side=tk.RIGHT)

        self.bind("<Return>", lambda _e: self.save(check_now=True))
        self.bind("<Escape>", lambda _e: self.destroy())
        (first_empty or body).focus_set()
        self.grab_set()  # modal: the queue can't change while editing

    def changed_values(self) -> dict[str, str]:
        """Fields whose text differs from what the dialog opened with."""
        changed = {
            name: var.get()
            for name, var in self.vars.items()
            if var.get().strip() != self._initial.get(name, "").strip()
        }
        for name, var in (("pago_a_banco", self.pago_a_banco), ("spid", self.spid)):
            if var.get() != (self._initial.get(name) == "1"):
                changed[name] = "1" if var.get() else "0"
        return changed

    def _update_pago_a_banco(self) -> None:
        self.labels["beneficiary_account"].configure(text=account_label(self.pago_a_banco.get()))
        for name in ("receiver_bank", "beneficiary_account"):
            self._show_note(name, None)

    def _show_note(self, name: str, error: str | None) -> None:
        if error:
            self.notes[name].configure(text=error, fg=ERROR_COLOR)
        else:
            text = hints(self.pago_a_banco.get()).get(name, "")
            self.notes[name].configure(text=text, fg=theme.TEXT_MUTED)

    def save(self, *, check_now: bool) -> None:
        errors = self._on_save(self.changed_values(), check_now)
        for name in self.notes:
            self._show_note(name, errors.get(name))
        if not errors:
            self.destroy()
