"""Colors, fonts and ttk styles for the desktop app."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

APP_BG = "#F4F6FA"
CARD_BG = "#FFFFFF"
TEXT = "#121826"
TEXT_MUTED = "#6B7280"
ACCENT = "#1E5EFF"

FONT = "Segoe UI"
FONT_BOLD = "Segoe UI Semibold"
FONT_MONO = "Consolas"

# Treeview row colors per status tag.
STATUS_COLORS = {
    "status_pending": "#5f6368",
    "status_processing": "#e67e22",
    "status_success": "#1e8e3e",
    "status_notfound": "#B45309",
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
    "font": (FONT_BOLD, 10),
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
    style.configure("HeaderTitle.TLabel", background=APP_BG, foreground=TEXT, font=(FONT_BOLD, 20))
    style.configure("HeaderSubtitle.TLabel", background=APP_BG, foreground="#5B6475", font=(FONT, 10))
    style.configure("CardTitle.TLabel", background=CARD_BG, foreground=TEXT, font=(FONT_BOLD, 11))
    style.configure("CardValue.TLabel", background=CARD_BG, foreground=TEXT, font=(FONT_BOLD, 18))
    style.configure("CardHint.TLabel", background=CARD_BG, foreground=TEXT_MUTED, font=(FONT, 9))

    style.configure(
        "Modern.Treeview",
        background=CARD_BG,
        fieldbackground=CARD_BG,
        foreground="#111827",
        rowheight=30,
        font=(FONT, 10),
        borderwidth=0,
    )
    style.configure(
        "Modern.Treeview.Heading",
        background="#EEF2F8",
        foreground="#1F2937",
        font=(FONT_BOLD, 10),
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
        "StatusBar.TLabel", background="#E9EEF8", foreground="#202939", font=(FONT, 9), padding=(8, 6)
    )


def make_button(parent: tk.Misc, text: str, command, variant: str = "neutral", **kwargs) -> tk.Button:
    return tk.Button(
        parent, text=text, command=command, **BUTTON_VARIANTS[variant], **BUTTON_COMMON, **kwargs
    )
