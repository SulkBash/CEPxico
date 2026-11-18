"""Dialog for typing in receipt fields the app read wrong or couldn't read."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from cepxico.gui import theme
from cepxico.i18n import tr
from cepxico.models import FIELD_NAMES, field_label


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


class FieldsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        *,
        filename: str,
        initial: Mapping[str, str],
        on_save: SaveHandler,
        on_open_receipt: Callable[[], None],
    ):
        super().__init__(parent)
        self.setWindowTitle(f"{tr('Edit Fields')} - {filename}")
        self._initial = dict(initial)
        self._on_save = on_save
        self.fields: dict[str, QLineEdit] = {}
        self.notes: dict[str, QLabel] = {}  # under each field: its hint, or its problem
        self.labels: dict[str, QLabel] = {}

        column = QVBoxLayout(self)
        column.addWidget(
            theme.wrapped(tr("Fix anything read wrong and fill in what's missing, copying from the receipt."))
        )
        column.addSpacing(6)
        grid = QGridLayout()
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)
        first_empty = None
        for i, name in enumerate(FIELD_NAMES):
            row = 2 * i
            self.labels[name] = QLabel(field_label(name).capitalize() + ":")
            grid.addWidget(self.labels[name], row, 0)
            entry = QLineEdit(initial.get(name, ""))
            entry.setMinimumWidth(300)
            self.labels[name].setBuddy(entry)
            grid.addWidget(entry, row, 1)
            self.fields[name] = entry
            if first_empty is None and not entry.text():
                first_empty = entry
            note = QLabel()
            grid.addWidget(note, row + 1, 1)
            self.notes[name] = note
            grid.setRowMinimumHeight(row + 1, note.sizeHint().height() + 4)
        column.addLayout(grid)

        self.pago_a_banco = QCheckBox(
            tr("Pago a banco: paid to the receiving bank itself, not to one of its customers")
        )
        self.pago_a_banco.setChecked(initial.get("pago_a_banco") == "1")
        self.pago_a_banco.toggled.connect(lambda _on: self._update_pago_a_banco())
        column.addWidget(self.pago_a_banco)
        self.spid = QCheckBox(
            tr(
                "Dollar transfer (SPID): checked at Banxico's CEP-SPID, which asks you to type "
                "a security image"
            )
        )
        self.spid.setChecked(initial.get("spid") == "1")
        column.addWidget(self.spid)
        self._update_pago_a_banco()

        column.addSpacing(8)
        buttons = QDialogButtonBox()
        check = buttons.addButton(tr("Save and Check"), QDialogButtonBox.ButtonRole.AcceptRole)
        save = buttons.addButton(tr("Save"), QDialogButtonBox.ButtonRole.ActionRole)
        cancel = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        receipt = buttons.addButton(tr("Open Receipt"), QDialogButtonBox.ButtonRole.ResetRole)
        check.clicked.connect(lambda: self.save(check_now=True))
        save.clicked.connect(lambda: self.save(check_now=False))
        cancel.clicked.connect(self.reject)
        receipt.clicked.connect(on_open_receipt)
        check.setDefault(True)  # Enter
        column.addWidget(buttons)

        theme.present(self, parent)
        (first_empty or check).setFocus()

    def changed_values(self) -> dict[str, str]:
        """Fields whose text differs from what the dialog opened with."""
        changed = {
            name: entry.text()
            for name, entry in self.fields.items()
            if entry.text().strip() != self._initial.get(name, "").strip()
        }
        for name, box in (("pago_a_banco", self.pago_a_banco), ("spid", self.spid)):
            if box.isChecked() != (self._initial.get(name) == "1"):
                changed[name] = "1" if box.isChecked() else "0"
        return changed

    def _update_pago_a_banco(self) -> None:
        self.labels["beneficiary_account"].setText(account_label(self.pago_a_banco.isChecked()) + ":")
        for name in FIELD_NAMES:
            self._show_note(name, None)

    def _show_note(self, name: str, error: str | None) -> None:
        note = self.notes[name]
        note.setText(error or hints(self.pago_a_banco.isChecked()).get(name, ""))
        if error:
            note.setStyleSheet(f"color: {theme.ERROR_COLOR}")
        else:
            note.setStyleSheet("")
            note.setForegroundRole(QPalette.ColorRole.PlaceholderText)

    def save(self, *, check_now: bool) -> None:
        errors = self._on_save(self.changed_values(), check_now)
        for name in self.notes:
            self._show_note(name, errors.get(name))
        if not errors:
            self.accept()
