"""Colors, fonts and ttk styles for the desktop app, on Windows, macOS and Linux."""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

APP_BG = "#F4F6FA"
CARD_BG = "#FFFFFF"
TEXT = "#121826"
TEXT_MUTED = "#6B7280"
ACCENT = "#1E5EFF"

# Each system's own UI and monospace fonts. Windows has a semibold face; elsewhere bold
# is a weight of the regular family.
if sys.platform == "win32":
    FONT, FONT_BOLD, FONT_MONO = "Segoe UI", "Segoe UI Semibold", "Consolas"
elif sys.platform == "darwin":
    FONT, FONT_BOLD, FONT_MONO = "Helvetica Neue", "", "Menlo"
else:
    FONT, FONT_BOLD, FONT_MONO = "DejaVu Sans", "", "DejaVu Sans Mono"

# macOS's native toolkit draws tk.Button its own way, ignoring colors; ttk buttons in
# the "clam" theme look the same everywhere.
TTK_BUTTONS = sys.platform == "darwin"


def font(size: int, bold: bool = False) -> tuple[str, int] | tuple[str, int, str]:
    if not bold:
        return (FONT, size)
    return (FONT_BOLD, size) if FONT_BOLD else (FONT, size, "bold")


def mono(size: int) -> tuple[str, int]:
    return (FONT_MONO, size)


# Treeview row colors per status tag.
STATUS_COLORS = {
    "status_pending": "#5f6368",
    "status_processing": "#e67e22",
    "status_success": "#1e8e3e",
    "status_notfound": "#B45309",
    "status_review": "#1D4ED8",
    "status_failed": "#c5221f",
    "status_cancelled": "#8e44ad",
}

# tk.Button colors per variant (tk.Button renders reliably across themes, unlike ttk).
BUTTON_VARIANTS = {
    "neutral": {
        "bg": "#E8EEF8",
        "fg": "#1F2937",
        "activebackground": "#D9E4F5",
        "activeforeground": "#111827",
    },
    "danger": {
        "bg": "#FCE8EA",
        "fg": "#A61B1B",
        "activebackground": "#F7D5D9",
        "activeforeground": "#8D1414",
    },
    "primary": {"bg": ACCENT, "fg": "#FFFFFF", "activebackground": "#1A50DA", "activeforeground": "#FFFFFF"},
}
BUTTON_COMMON = {
    "font": font(10, bold=True),
    "padx": 14,
    "pady": 8,
    "bd": 1,
    "relief": tk.RAISED,
    "cursor": "hand2",
    "disabledforeground": "#8A94A8",
}


def apply(root: tk.Misc) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure("App.TFrame", background=APP_BG)
    style.configure("Card.TFrame", background=CARD_BG)
    style.configure("HeaderTitle.TLabel", background=APP_BG, foreground=TEXT, font=font(20, bold=True))
    style.configure("HeaderSubtitle.TLabel", background=APP_BG, foreground="#5B6475", font=font(10))
    style.configure("CardTitle.TLabel", background=CARD_BG, foreground=TEXT, font=font(11, bold=True))
    style.configure("CardValue.TLabel", background=CARD_BG, foreground=TEXT, font=font(18, bold=True))
    style.configure("CardHint.TLabel", background=CARD_BG, foreground=TEXT_MUTED, font=font(9))
    style.configure("Card.TCheckbutton", background=CARD_BG, foreground=TEXT, font=font(9))
    style.map("Card.TCheckbutton", background=[("active", CARD_BG)])
    style.configure("Card.TRadiobutton", background=CARD_BG, foreground=TEXT, font=font(9))
    style.map("Card.TRadiobutton", background=[("active", CARD_BG)])

    style.configure(
        "Modern.Treeview",
        background=CARD_BG,
        fieldbackground=CARD_BG,
        foreground="#111827",
        rowheight=30,
        font=font(10),
        borderwidth=0,
    )
    style.configure(
        "Modern.Treeview.Heading",
        background="#EEF2F8",
        foreground="#1F2937",
        font=font(10, bold=True),
        relief="flat",
    )
    style.map("Modern.Treeview", background=[("selected", "#DCE8FF")], foreground=[("selected", "#111827")])

    style.configure(
        "Modern.Horizontal.TProgressbar",
        troughcolor="#E7ECF6",
        background=ACCENT,
        bordercolor="#E7ECF6",
        lightcolor=ACCENT,
        darkcolor=ACCENT,
    )
    style.configure(
        "StatusBar.TLabel", background="#E9EEF8", foreground="#202939", font=font(9), padding=(8, 6)
    )
    for variant, colors in BUTTON_VARIANTS.items():
        name = f"{variant.capitalize()}.TButton"
        style.configure(
            name,
            background=colors["bg"],
            foreground=colors["fg"],
            font=BUTTON_COMMON["font"],
            padding=(BUTTON_COMMON["padx"], BUTTON_COMMON["pady"] - 2),
        )
        style.map(
            name,
            background=[("disabled", colors["bg"]), ("active", colors["activebackground"])],
            foreground=[
                ("disabled", BUTTON_COMMON["disabledforeground"]),
                ("active", colors["activeforeground"]),
            ],
        )


def make_button(
    parent: tk.Misc, text: str, command, variant: str = "neutral", **kwargs
) -> tk.Button | ttk.Button:
    """A button in the app's colors. Both kinds take `state` in configure()."""
    if TTK_BUTTONS:
        return ttk.Button(
            parent,
            text=text,
            command=command,
            style=f"{variant.capitalize()}.TButton",
            cursor="hand2",
            **kwargs,
        )
    return tk.Button(
        parent, text=text, command=command, **BUTTON_VARIANTS[variant], **BUTTON_COMMON, **kwargs
    )
