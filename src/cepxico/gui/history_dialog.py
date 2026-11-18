"""History window: every receipt checked on this computer, searchable, exportable as CSV."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cepxico.gui import messages, theme
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


class HistoryDialog(QDialog):
    def __init__(self, parent: QWidget, *, history: History, on_open: Callable[[Path], None]):
        super().__init__(parent)
        self.setWindowTitle(tr("History"))
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint)
        self._history = history
        self._on_open = on_open
        self._checks: list[Check] = []
        self.shown: list[Check] = []  # rows in the table, in order

        column = QVBoxLayout(self)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search file, clave, amount, name or bank"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self.refresh())
        search_row.addWidget(self.search, 1)
        self.count_label = QLabel()
        search_row.addWidget(self.count_label)
        column.addLayout(search_row)

        # The result goes in the first column, which shows an icon.
        columns = {
            tr("Result"): 110,
            tr("Checked"): 120,
            tr("File"): 160,
            tr("Clave de rastreo"): 180,
            tr("Amount"): 90,
            tr("Sender"): 150,
            tr("Beneficiary"): 150,
            tr("Details"): 240,
        }
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(columns))
        self.tree.setHeaderLabels(list(columns))
        for i, width in enumerate(columns.values()):
            self.tree.header().resizeSection(i, width)
        self.tree.headerItem().setTextAlignment(
            4, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.itemActivated.connect(lambda _item, _column: self.open_cep())
        column.addWidget(self.tree, 1)

        buttons = QDialogButtonBox()
        role = QDialogButtonBox.ButtonRole
        buttons.addButton(tr("Open CEP"), role.ActionRole).clicked.connect(self.open_cep)
        buttons.addButton(tr("Forget"), role.ActionRole).clicked.connect(self.forget)
        buttons.addButton(tr("Export CSV..."), role.ActionRole).clicked.connect(self.export)
        buttons.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(self.reject)
        for button in buttons.buttons():  # Enter in the search box shouldn't press any of them
            button.setAutoDefault(False)
        column.addWidget(buttons)

        self.reload()
        theme.present(self, parent, QSize(1040, 560))
        self.search.setFocus()

    def reload(self) -> None:
        try:
            self._checks = self._history.checks()
        except Exception as e:  # a damaged or locked history file mustn't break the window
            logger.exception("Couldn't read the history")
            messages.error(self, tr("History"), tr("Couldn't read the history: {error}", error=e))
            self._checks = []
        self.refresh()

    def refresh(self) -> None:
        query = self.search.text().strip()
        self.shown = [c for c in self._checks if matches(c, query)] if query else list(self._checks)
        self.tree.clear()
        for check in self.shown:
            row = QTreeWidgetItem(
                [
                    outcome_label(check.outcome),
                    check.checked_at_text,
                    check.file_name,
                    check.tracking_key,
                    f"{check.amount}  " if check.amount else "",  # clear of the next column
                    check.sender_name or check.sender_bank,
                    check.beneficiary_name or check.receiver_bank,
                    check.message,
                ]
            )
            row.setIcon(0, theme.status_icon(OUTCOME_TAGS.get(check.outcome, "status_pending")))
            row.setTextAlignment(4, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.setToolTip(7, check.message)
            self.tree.addTopLevelItem(row)
        self.count_label.setText(tr("{shown} of {total}", shown=len(self.shown), total=len(self._checks)))

    def selected(self) -> Check | None:
        row = self.tree.currentItem()
        return (
            self.shown[self.tree.indexOfTopLevelItem(row)] if row is not None and row.isSelected() else None
        )

    def open_cep(self) -> None:
        check = self.selected()
        if not check:
            messages.info(self, tr("Open CEP"), tr("Select a row first."))
        elif not check.cep_file or not Path(check.cep_file).is_file():
            messages.info(self, tr("Open CEP"), tr("This check's CEP isn't on this computer."))
        else:
            self._on_open(Path(check.cep_file))

    def forget(self) -> None:
        check = self.selected()
        if not check:
            messages.info(self, tr("Forget"), tr("Select a row first."))
            return
        sure = messages.ask(
            self,
            tr("Forget"),
            tr(
                "Forget the check of {file} on {date}? Its transfer will no longer count as used.",
                file=check.file_name,
                date=check.checked_at_text,
            ),
        )
        if not sure:
            return
        try:
            self._history.forget(check)
        except Exception as e:  # a locked or damaged history file
            logger.exception("Couldn't forget a check")
            messages.error(self, tr("Forget"), tr("Couldn't change the history: {error}", error=e))
            return
        self.reload()

    def export(self) -> None:
        path = messages.save_file(
            self, tr("Export CSV..."), f"cepxico_{date.today():%Y-%m-%d}.csv", [("CSV", "*.csv")]
        )
        if not path:
            return
        try:
            write_csv(path, self.shown)
        except OSError as e:
            messages.error(self, tr("Export CSV..."), tr("Couldn't write the file: {error}", error=e))
            return
        messages.info(
            self, tr("Export CSV..."), tr("Wrote {count} checks to {file}", count=len(self.shown), file=path)
        )
