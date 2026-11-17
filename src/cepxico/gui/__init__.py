"""Desktop app entry points."""

from __future__ import annotations

from pathlib import Path

from cepxico.config import DEFAULT_CEP_DIR


def run(cep_dir: Path = DEFAULT_CEP_DIR) -> None:
    from cepxico.gui.app import CEPApp  # imported lazily: Tk isn't needed for the CLI

    CEPApp(cep_dir=cep_dir).mainloop()


def main() -> None:
    """Entry point for the `cepxico-gui` launcher (no console window)."""
    from cepxico.cli import configure_logging

    configure_logging(verbose=False)
    run()
