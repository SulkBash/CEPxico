"""Message boxes and file pickers, in one place so tests can answer them."""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget


def info(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def warning(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def error(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.critical(parent, title, text)


def ask(parent: QWidget | None, title: str, text: str) -> bool:
    answer = QMessageBox.question(parent, title, text)
    return answer == QMessageBox.StandardButton.Yes


def open_files(parent: QWidget | None, title: str, filters: list[tuple[str, str]]) -> list[str]:
    """Files the person picks; `filters` are (description, "*.pdf *.png") pairs."""
    paths, _filter = QFileDialog.getOpenFileNames(
        parent, title, "", ";;".join(f"{d} ({p})" for d, p in filters)
    )
    return paths


def save_file(parent: QWidget | None, title: str, suggested: str, filters: list[tuple[str, str]]) -> str:
    """Where to save, or "" if the person cancels."""
    path, _filter = QFileDialog.getSaveFileName(
        parent, title, suggested, ";;".join(f"{d} ({p})" for d, p in filters)
    )
    return path
