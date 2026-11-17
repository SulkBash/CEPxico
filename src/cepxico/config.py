"""Application-wide settings and the few things that differ between Windows, macOS and Linux."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DEFAULT_CEP_DIR = Path.home() / "Downloads" / "CEPs"

# Overrides where settings and history are kept (tests, or a portable install).
DATA_DIR_ENV = "CEPXICO_HOME"


def app_data_dir() -> Path:
    """Where the app keeps its settings and history:
    Windows %APPDATA%\\CEPxico, macOS ~/Library/Application Support/CEPxico,
    Linux $XDG_CONFIG_HOME/cepxico (~/.config/cepxico)."""
    if override := os.environ.get(DATA_DIR_ENV):
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return Path(base) / "CEPxico" if base else Path.home() / ".cepxico"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CEPxico"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "cepxico"


def open_path(path: Path | str) -> None:
    """Opens a file or folder with the system's default app. Raises OSError."""
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError as e:
        raise OSError(f"'{opener}' isn't available to open files") from e
