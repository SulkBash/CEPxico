"""Settings dialog: which files to save for each CEP, the own-accounts check, and the language."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from cepxico.banxico import CEPFiles
from cepxico.config import app_data_dir, open_path
from cepxico.gui import theme
from cepxico.i18n import LANGUAGES, tr
from cepxico.settings import Settings, parse_accounts

WRAP = 360  # pixels: width of error messages


def file_choices() -> dict[CEPFiles, str]:
    return {
        CEPFiles.PDF: "PDF",
        CEPFiles.XML: "XML",
        CEPFiles.ZIP: tr("PDF and XML (ZIP)"),
    }


def language_choices() -> dict[str, str]:
    """Setting value -> label; "" follows the system. Language names stay in their own language."""
    return {"": tr("System"), **LANGUAGES}


# Called with the new settings; returns a problem to show, or None once saved.
SaveHandler = Callable[[Settings], str | None]


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget, *, settings: Settings, on_save: SaveHandler):
        super().__init__(parent)
        self.setWindowTitle(tr("Settings"))
        self._on_save = on_save
        column = QVBoxLayout(self)

        files = self._group(column, tr("CEP files"))
        self._file_group = QButtonGroup(self)
        self.cep_file_buttons: dict[CEPFiles, QRadioButton] = {}
        for value, text in file_choices().items():
            choice = QRadioButton(text)
            choice.setChecked(value is settings.cep_files)
            self._file_group.addButton(choice)
            self.cep_file_buttons[value] = choice
            files.addWidget(choice)
        self.cep_file_buttons[CEPFiles.XML].setToolTip(
            tr("Banxico's signed record of the transfer; accounting software can import it.")
        )

        accounts = self._group(column, tr("Your accounts"))
        self.check_accounts = QCheckBox(tr("Only accept payments to these accounts"))
        self.check_accounts.setChecked(settings.check_own_accounts)
        self.check_accounts.toggled.connect(lambda _on: self._update_enabled())
        self.check_accounts.setToolTip(tr("Receipts paid to any other account are marked Review."))
        accounts.addWidget(self.check_accounts)
        self.accounts = QPlainTextEdit("\n".join(settings.own_accounts))
        self.accounts.setPlaceholderText(tr("One per line: CLABE, card or phone"))
        self.accounts.setFont(theme.mono())
        self.accounts.setFixedHeight(self.accounts.fontMetrics().lineSpacing() * 4 + 12)
        accounts.addWidget(self.accounts)

        language = self._group(column, tr("Language"))
        row = QHBoxLayout()
        self._language_group = QButtonGroup(self)
        self.language_buttons: dict[str, QRadioButton] = {}
        for value, text in language_choices().items():
            choice = QRadioButton(text)
            choice.setChecked(value == settings.language)
            self._language_group.addButton(choice)
            self.language_buttons[value] = choice
            row.addWidget(choice)
        row.addStretch(1)
        language.addLayout(row)

        data = self._group(column, tr("Data folder"))
        path_row = QHBoxLayout()
        path = QLineEdit(str(app_data_dir()))  # read-only, but can be selected and copied
        path.setReadOnly(True)
        path.setToolTip(tr("Settings, history and cepxico.log"))
        path.setCursorPosition(0)  # show where it starts, not its end
        path.setMinimumWidth(path.fontMetrics().horizontalAdvance(path.text()) + 16)
        path_row.addWidget(path, 1)
        open_folder = QPushButton(tr("Open"))
        open_folder.setAutoDefault(False)
        open_folder.clicked.connect(self.open_data_folder)
        path_row.addWidget(open_folder)
        data.addLayout(path_row)

        self.problem = theme.error_label()
        self.problem.setMaximumWidth(WRAP + 24)
        column.addWidget(self.problem)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).clicked.connect(self.save)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)

        self._update_enabled()
        theme.present(self, parent)

    @staticmethod
    def _group(column: QVBoxLayout, title: str) -> QVBoxLayout:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        column.addWidget(group)
        return layout

    def open_data_folder(self) -> None:
        try:
            app_data_dir().mkdir(parents=True, exist_ok=True)
            open_path(app_data_dir())
        except OSError as e:
            self.problem.setText(tr("Couldn't open {path}: {error}", path=app_data_dir(), error=e))

    def _update_enabled(self) -> None:
        self.accounts.setEnabled(self.check_accounts.isChecked())

    def settings_entered(self) -> tuple[Settings | None, str | None]:
        """The settings in the dialog, or a problem to show."""
        accounts, problems = parse_accounts(self.accounts.toPlainText())
        if problems:
            return None, tr("Fix these accounts:") + "\n" + "\n".join(problems)
        if self.check_accounts.isChecked() and not accounts:
            return None, tr("Add an account or uncheck the box.")
        cep_files = next(value for value, choice in self.cep_file_buttons.items() if choice.isChecked())
        language = next((value for value, choice in self.language_buttons.items() if choice.isChecked()), "")
        return Settings(
            cep_files=cep_files,
            check_own_accounts=self.check_accounts.isChecked(),
            own_accounts=accounts,
            language=language,
        ), None

    def save(self) -> None:
        settings, problem = self.settings_entered()
        if settings is not None:
            problem = self._on_save(settings)
        if problem:
            self.problem.setText(problem)
        else:
            self.accept()
