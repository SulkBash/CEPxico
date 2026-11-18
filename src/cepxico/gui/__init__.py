"""Desktop app entry points."""

from __future__ import annotations

from pathlib import Path

from cepxico.config import DEFAULT_CEP_DIR


def run(cep_dir: Path = DEFAULT_CEP_DIR) -> None:
    # Imported lazily: Qt isn't needed for the command line.
    from cepxico.gui import theme
    from cepxico.gui.app import CEPApp

    app = theme.application()
    window = CEPApp(cep_dir=cep_dir)
    window.show()
    app.exec()


def main() -> None:
    """Entry point for the `cepxico-gui` launcher (no console window)."""
    from cepxico.cli import configure_logging

    configure_logging(verbose=False)
    run()
