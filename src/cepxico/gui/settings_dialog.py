"""Settings dialog: which files to save for each CEP, the own-accounts check, and the language."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from cepxico.banxico import CEPFiles
from cepxico.config import app_data_dir, open_path
from cepxico.gui import theme
from cepxico.i18n import LANGUAGES, tr
from cepxico.settings import Settings, parse_accounts

ERROR_COLOR = theme.STATUS_COLORS["status_failed"]


def file_choices() -> dict[CEPFiles, str]:
    return {
        CEPFiles.PDF: "PDF",
        CEPFiles.XML: "XML",
        CEPFiles.ZIP: tr("PDF and XML in one ZIP file"),
    }


def language_choices() -> dict[str, str]:
    """Setting value -> label; "" follows the system. Language names stay in their own language."""
    return {"": tr("Same as the system"), **LANGUAGES}


# Called with the new settings; returns a problem to show, or None once saved.
SaveHandler = Callable[[Settings], str | None]


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, *, settings: Settings, on_save: SaveHandler):
        super().__init__(parent)
        self.title(tr("Settings"))
        self.configure(bg=theme.CARD_BG)
        self.resizable(False, False)
        self.transient(parent)  # type: ignore[arg-type]
        self._on_save = on_save

        self.cep_files = tk.StringVar(value=settings.cep_files.value)
        self.check_accounts = tk.BooleanVar(value=settings.check_own_accounts)
        self.language = tk.StringVar(value=settings.language)

        body = ttk.Frame(self, style="Card.TFrame", padding=16)
        body.pack(fill=tk.BOTH, expand=True)

        ttk.Label(body, text=tr("Save each CEP as"), style="CardTitle.TLabel").pack(anchor=tk.W)
        for value, text in file_choices().items():
            ttk.Radiobutton(
                body, text=text, value=value.value, variable=self.cep_files, style="Card.TRadiobutton"
            ).pack(anchor=tk.W, pady=(4, 0))
        self._hint(
            body,
            tr(
                "The XML is Banxico's digitally signed record of the transfer. It can be checked at "
                "banxico.org.mx/validador-cep-spei and imported by accounting software. The app always "
                "reads it to confirm the CEP matches the receipt; this only keeps a copy. If Banxico's "
                "XML can't be read, the PDF is saved instead."
            ),
        )

        ttk.Label(body, text=tr("Your accounts"), style="CardTitle.TLabel").pack(anchor=tk.W, pady=(14, 0))
        ttk.Checkbutton(
            body,
            text=tr("Only accept payments to these accounts"),
            variable=self.check_accounts,
            command=self._update_enabled,
            style="Card.TCheckbutton",
        ).pack(anchor=tk.W, pady=(4, 0))
        self._hint(
            body,
            tr(
                "A real transfer to someone else's account would otherwise pass as confirmed. Receipts "
                "paid elsewhere are marked Review without asking Banxico. One account per line: CLABE, "
                "and also the debit card or phone number if customers pay to those."
            ),
        )
        self.accounts = tk.Text(body, width=48, height=6, font=theme.mono(10), relief=tk.SOLID, borderwidth=1)
        self.accounts.insert("1.0", "\n".join(settings.own_accounts))
        self.accounts.pack(fill=tk.X, pady=(6, 0))

        ttk.Label(body, text=tr("Language"), style="CardTitle.TLabel").pack(anchor=tk.W, pady=(14, 0))
        languages = ttk.Frame(body, style="Card.TFrame")
        languages.pack(anchor=tk.W, pady=(4, 0))
        for value, text in language_choices().items():
            ttk.Radiobutton(
                languages, text=text, value=value, variable=self.language, style="Card.TRadiobutton"
            ).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(body, text=tr("Data folder"), style="CardTitle.TLabel").pack(anchor=tk.W, pady=(14, 0))
        self._hint(body, tr("Settings, history and the log file (cepxico.log, to attach to bug reports)."))
        folder = tk.Frame(body, bg=theme.CARD_BG)
        folder.pack(fill=tk.X, padx=(22, 0), pady=(4, 0))
        tk.Label(
            folder, text=str(app_data_dir()), bg=theme.CARD_BG, fg=theme.TEXT, font=theme.mono(9), anchor=tk.W
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        theme.make_button(folder, tr("Open"), self.open_data_folder).pack(side=tk.RIGHT)

        self.problem = tk.Label(
            body, bg=theme.CARD_BG, fg=ERROR_COLOR, font=theme.font(8), justify=tk.LEFT, wraplength=420
        )
        self.problem.pack(anchor=tk.W, pady=(4, 0))

        buttons = tk.Frame(body, bg=theme.CARD_BG)
        buttons.pack(fill=tk.X, pady=(10, 0))
        theme.make_button(buttons, tr("Save"), self.save, variant="primary").pack(side=tk.RIGHT)
        theme.make_button(buttons, tr("Cancel"), self.destroy).pack(side=tk.RIGHT, padx=6)

        self.bind("<Escape>", lambda _e: self.destroy())
        self._update_enabled()
        self.grab_set()

    @staticmethod
    def _hint(parent: tk.Misc, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            bg=theme.CARD_BG,
            fg=theme.TEXT_MUTED,
            font=theme.font(8),
            justify=tk.LEFT,
            wraplength=420,
        ).pack(anchor=tk.W, padx=(22, 0))

    def open_data_folder(self) -> None:
        try:
            app_data_dir().mkdir(parents=True, exist_ok=True)
            open_path(app_data_dir())
        except OSError as e:
            self.problem.configure(text=tr("Couldn't open {path}: {error}", path=app_data_dir(), error=e))

    def _update_enabled(self) -> None:
        self.accounts.configure(state=tk.NORMAL if self.check_accounts.get() else tk.DISABLED)

    def settings_entered(self) -> tuple[Settings | None, str | None]:
        """The settings in the dialog, or a problem to show."""
        accounts, problems = parse_accounts(self.accounts.get("1.0", tk.END))
        if problems:
            return None, tr("Fix these accounts:") + "\n" + "\n".join(problems)
        if self.check_accounts.get() and not accounts:
            return None, tr("Add at least one account, or turn the check off.")
        return Settings(
            cep_files=CEPFiles(self.cep_files.get()),
            check_own_accounts=self.check_accounts.get(),
            own_accounts=accounts,
            language=self.language.get(),
        ), None

    def save(self) -> None:
        settings, problem = self.settings_entered()
        if settings is not None:
            problem = self._on_save(settings)
        if problem:
            self.problem.configure(text=problem)
        elif self.winfo_exists():  # saving a new language rebuilds the main window
            self.destroy()
