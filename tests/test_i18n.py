"""Spanish and English: every message translated, and the language switch."""

import ast
import string
from pathlib import Path

import pytest

from cepxico import i18n
from cepxico.i18n import set_language, system_language, tr
from cepxico.models import PaymentData, field_label
from cepxico.pipeline import Outcome, process_file
from cepxico.translations import ES

SOURCE = Path(__file__).parent.parent / "src" / "cepxico"


def tr_messages() -> dict[str, str]:
    """Every message passed to tr() in the source: {message: "file:line"}."""
    found = {}
    for path in sorted(SOURCE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr":
                arg = node.args[0] if node.args else None
                where = f"{path.name}:{node.lineno}"
                assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
                    f"{where}: tr() needs a literal message, or it can't be checked for a translation"
                )
                found.setdefault(arg.value, where)
    return found


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_message_has_a_spanish_translation():
    missing = {message: where for message, where in tr_messages().items() if message not in ES}
    assert not missing, f"Add to translations.py: {missing}"


def test_translations_use_the_same_placeholders():
    wrong = {m: s for m, s in ES.items() if placeholders(m) != placeholders(s)}
    assert not wrong


def test_no_leftover_translations():
    assert not set(ES) - set(tr_messages()), "translations.py has messages the code no longer uses"


def test_switching_language():
    assert tr("Files: {count}", count=3) == "Files: 3"
    set_language("es")
    assert tr("Files: {count}", count=3) == "Archivos: 3"
    assert field_label("beneficiary_account") == "cuenta beneficiaria"
    assert PaymentData("r.pdf", pago_a_banco=True).label("beneficiary_account") == "cuenta ordenante"


def test_results_come_in_the_language_set(tmp_path):
    set_language("es")
    result = process_file(tmp_path / "missing.pdf", client=None)  # type: ignore[arg-type]
    assert result.outcome is Outcome.FAILED and result.message == "Archivo no encontrado"


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"LANG": "es_MX.UTF-8"}, "es"),
        ({"LANG": "en_US.UTF-8"}, "en"),
        ({"LANGUAGE": "en", "LANG": "es_MX.UTF-8"}, "en"),
        ({"LANG": "fr_FR.UTF-8"}, None),  # not offered: falls through to the locale, then Spanish
    ],
)
def test_system_language_on_macos_and_linux(monkeypatch, env, expected):
    monkeypatch.setattr(i18n.sys, "platform", "linux")
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: (None, None))
    assert system_language() == (expected or i18n.DEFAULT_LANGUAGE)


def test_unset_language_follows_the_system(monkeypatch):
    monkeypatch.setattr(i18n, "system_language", lambda: "es")
    set_language("")
    assert i18n.get_language() == "es"
