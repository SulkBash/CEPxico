from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from cepxico.banxico import CEPFiles, CEPResult, CEPStatus
from cepxico.gui import app as gui
from cepxico.gui.app import ItemStatus, QueueItem, is_confirmed
from cepxico.models import PaymentData
from cepxico.pipeline import FileResult, Outcome
from cepxico.settings import Settings


def result(path: str, outcome: Outcome, pdf_path: Path | None = None) -> FileResult:
    status = CEPStatus.FOUND if outcome is Outcome.SUCCESS else CEPStatus.NOT_FOUND
    cep = CEPResult(status, "", pdf_path=pdf_path)
    return FileResult(Path(path), outcome, "", cep=cep)


def test_confirmed_needs_success_and_the_cep_file(tmp_path):
    cep = tmp_path / "CEP.pdf"
    cep.write_bytes(b"%PDF")
    found = result("a.pdf", Outcome.SUCCESS, cep)

    assert is_confirmed(QueueItem("a.pdf", status=ItemStatus.SUCCESS, result=found))
    assert not is_confirmed(QueueItem("a.pdf", status=ItemStatus.PENDING))
    not_found = result("a.pdf", Outcome.NOT_FOUND)
    assert not is_confirmed(QueueItem("a.pdf", status=ItemStatus.NOT_FOUND, result=not_found))
    failed = FileResult(Path("a.pdf"), Outcome.FAILED, "")
    assert not is_confirmed(QueueItem("a.pdf", status=ItemStatus.FAILED, result=failed))

    cep.unlink()  # CEP deleted from the folder: check again to download it anew
    assert not is_confirmed(QueueItem("a.pdf", status=ItemStatus.SUCCESS, result=found))


@pytest.fixture
def app(window, monkeypatch):
    shown = []
    monkeypatch.setattr(gui.messages, "info", lambda _parent, title, _msg: shown.append(title))
    monkeypatch.setattr(gui.messages, "warning", lambda _parent, title, _msg: shown.append(title))
    # Tests start batches without running them, so a previous test may have left one "running".
    window.processing = False
    window.settings = Settings()  # whatever the real user's settings file says
    window.clear_files()
    shown.clear()
    window.shown = shown
    return window


def run_batch_inline(app, monkeypatch, payments: list | None = None) -> list[list[str]]:
    """Captures the paths each batch sends to the worker (and, into `payments`, the
    corrected data), without starting a thread."""
    batches: list[list[str]] = []

    class Inline:
        def __init__(self, target, args, daemon):
            batches.append(args[0])
            if payments is not None:
                payments.append(args[1])

        def start(self):
            pass

    monkeypatch.setattr(gui.threading, "Thread", Inline)
    return batches


def test_process_files_skips_confirmed_receipts(app, tmp_path, monkeypatch):
    cep = tmp_path / "CEP.pdf"
    cep.write_bytes(b"%PDF")
    for path in ("ok.pdf", "missing.pdf", "failed.pdf", "new.pdf"):
        app.add_file(path)
    app._on_file_done("ok.pdf", result("ok.pdf", Outcome.SUCCESS, cep))
    app._on_file_done("missing.pdf", result("missing.pdf", Outcome.NOT_FOUND))
    app._on_file_done("failed.pdf", FileResult(Path("failed.pdf"), Outcome.FAILED, "network"))
    batches = run_batch_inline(app, monkeypatch)

    app.process_files()

    assert batches == [["missing.pdf", "failed.pdf", "new.pdf"]]
    assert app.items["ok.pdf"].status is ItemStatus.SUCCESS  # left as it was
    assert app.items["ok.pdf"].result is not None
    assert all(app.items[p].status is ItemStatus.PENDING for p in batches[0])
    assert app._skipped_confirmed == 1
    assert app.progress_label.text() == "1 / 4"  # the confirmed file counts as done
    assert "Already confirmed, not checked again: 1" in app._summary(cancelled=False)


def test_process_files_with_everything_confirmed_does_nothing(app, tmp_path, monkeypatch):
    cep = tmp_path / "CEP.pdf"
    cep.write_bytes(b"%PDF")
    app.add_file("ok.pdf")
    app._on_file_done("ok.pdf", result("ok.pdf", Outcome.SUCCESS, cep))
    batches = run_batch_inline(app, monkeypatch)

    app.process_files()

    assert batches == []
    assert not app.processing
    assert app.shown == ["Nothing to Check"]


# --- Typing in fields ------------------------------------------------------------

CLABE = "653180000000001237"


def failed_banamex(app, path="banamex.pdf"):
    """A receipt that showed only the end of the account, so it failed."""
    app.add_file(path)
    read = PaymentData(path, payment_date="12-11-2026", tracking_key="085901234567890123", amount="48750.00")
    app._on_file_done(path, FileResult(Path(path), Outcome.FAILED, "Missing cuenta beneficiaria", read))
    return read


def test_only_failed_or_not_found_files_can_be_edited():
    assert gui.can_edit(QueueItem("a", status=ItemStatus.FAILED))
    assert gui.can_edit(QueueItem("a", status=ItemStatus.NOT_FOUND))
    assert not gui.can_edit(QueueItem("a", status=ItemStatus.SUCCESS))
    assert not gui.can_edit(QueueItem("a", status=ItemStatus.PENDING))
    edited = PaymentData("a", edited_fields=("amount",))
    assert gui.can_edit(QueueItem("a", status=ItemStatus.PENDING, corrected=edited))  # saved, not checked yet


def test_saved_corrections_are_checked_without_rereading(app, monkeypatch):
    read = failed_banamex(app)
    payments: list = []
    batches = run_batch_inline(app, monkeypatch, payments)

    errors = app.save_corrections("banamex.pdf", {"beneficiary_account": CLABE}, check_now=False)

    assert errors == {}
    item = app.items["banamex.pdf"]
    assert item.status is ItemStatus.PENDING and item.result_text == "Edited, ready to check"
    assert item.corrected.beneficiary_account == CLABE
    assert item.corrected.amount == read.amount  # the rest is kept
    assert batches == []  # Save alone doesn't check

    app.process_files()

    assert batches == [["banamex.pdf"]]
    assert payments == [{"banamex.pdf": item.corrected}]


def test_save_and_check_checks_only_that_file(app, monkeypatch):
    failed_banamex(app, "a.pdf")
    failed_banamex(app, "b.pdf")
    batches = run_batch_inline(app, monkeypatch)

    app.save_corrections("a.pdf", {"beneficiary_account": CLABE}, check_now=True)

    assert batches == [["a.pdf"]]
    assert app.items["b.pdf"].status is ItemStatus.FAILED


def test_invalid_values_change_nothing(app, monkeypatch):
    failed_banamex(app)
    batches = run_batch_inline(app, monkeypatch)

    errors = app.save_corrections("banamex.pdf", {"beneficiary_account": "***756"}, check_now=True)

    assert set(errors) == {"beneficiary_account"}
    assert app.items["banamex.pdf"].corrected is None
    assert app.items["banamex.pdf"].status is ItemStatus.FAILED
    assert batches == []


def test_result_of_edited_receipt_is_marked(app, tmp_path):
    app.add_file("a.pdf")
    typed = PaymentData("a.pdf", edited_fields=("beneficiary_account",))
    app._on_file_done("a.pdf", FileResult(Path("a.pdf"), Outcome.NOT_FOUND, "No CEP at Banxico", typed))
    assert app.items["a.pdf"].result_text == "No CEP at Banxico  [edited]"
    assert app.items["a.pdf"].row.text(2) == "No CEP at Banxico  [edited]"


def test_dialog_sends_only_changed_fields_and_shows_problems(app):
    from cepxico.gui.fields_dialog import FieldsDialog

    calls = []

    def on_save(values, check_now):
        calls.append((values, check_now))
        return {"amount": "'x' isn't a valid amount"} if values.get("amount") == "x" else {}

    initial = {"payment_date": "12-11-2026", "amount": "48750.00", "receiver_bank": "KUSPIT"}
    dialog = FieldsDialog(
        app, filename="r.pdf", initial=initial, on_save=on_save, on_open_receipt=lambda: None
    )
    dialog.fields["beneficiary_account"].setText(CLABE)
    dialog.fields["amount"].setText("x")

    dialog.save(check_now=True)

    assert calls == [({"beneficiary_account": CLABE, "amount": "x"}, True)]
    assert dialog.notes["amount"].text() == "'x' isn't a valid amount"
    assert dialog.isVisible()  # stays open to fix it

    dialog.fields["amount"].setText("48750.00")  # back to what was read: no longer a change
    dialog.save(check_now=False)

    assert calls[-1] == ({"beneficiary_account": CLABE}, False)
    assert not dialog.isVisible()


# --- Settings and review -------------------------------------------------------------


def test_review_results_can_be_edited_and_are_counted(app, tmp_path):
    app.add_file("a.pdf")
    app._on_file_done("a.pdf", FileResult(Path("a.pdf"), Outcome.REVIEW, "Paid to account …1234"))
    item = app.items["a.pdf"]
    assert item.status is ItemStatus.REVIEW and gui.can_edit(item)
    assert app.counts["review"] == 1
    assert "NEEDS REVIEW (1)" in app._summary(cancelled=False)


def test_settings_dialog(app):
    from cepxico.gui.settings_dialog import SettingsDialog
    from cepxico.settings import load_settings

    saved = []
    dialog = SettingsDialog(
        app, settings=Settings(), on_save=lambda s: saved.append(s) or app.apply_settings(s)
    )
    dialog.check_accounts.setChecked(True)
    assert dialog.accounts.isEnabled()
    dialog.accounts.setPlainText("123\n")
    dialog.save()
    assert saved == [] and "123:" in dialog.problem.text()  # stays open to fix it
    assert dialog.isVisible()

    dialog.accounts.setPlainText(CLABE)
    dialog.cep_file_buttons[CEPFiles.ZIP].setChecked(True)
    dialog.save()

    expected = Settings(cep_files=CEPFiles.ZIP, check_own_accounts=True, own_accounts=(CLABE,))
    assert saved == [expected] and app.settings == expected and load_settings() == expected
    assert not dialog.isVisible()
    app.settings = Settings()


def test_settings_dialog_needs_an_account_when_the_check_is_on(app):
    from cepxico.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(app, settings=Settings(), on_save=lambda s: None)
    assert not dialog.accounts.isEnabled()
    dialog.check_accounts.setChecked(True)
    settings, problem = dialog.settings_entered()
    assert settings is None and "at least one account" in problem
    dialog.reject()


def test_dialog_sends_pago_a_banco_when_ticked(app):
    from cepxico.gui.fields_dialog import FieldsDialog

    calls = []
    dialog = FieldsDialog(
        app,
        filename="r.pdf",
        initial={"pago_a_banco": ""},
        on_save=lambda values, check_now: calls.append(values) or {},
        on_open_receipt=lambda: None,
    )
    dialog.pago_a_banco.setChecked(True)
    assert dialog.labels["beneficiary_account"].text() == "Ordering account:"
    dialog.save(check_now=False)
    assert calls == [{"pago_a_banco": "1"}]


def test_zipped_cep_counts_as_confirmed(tmp_path):
    archive = tmp_path / "CEP.zip"
    archive.write_bytes(b"PK")
    cep = CEPResult(CEPStatus.FOUND, "", zip_path=archive)
    found = FileResult(Path("a.pdf"), Outcome.SUCCESS, "", cep=cep)
    assert is_confirmed(QueueItem("a.pdf", status=ItemStatus.SUCCESS, result=found))


# --- Language, history, clipboard, drag & drop ---------------------------------------


def yes_button_text() -> str:
    from PySide6.QtWidgets import QDialogButtonBox

    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Yes)  # kept: its button goes with it
    return box.buttons()[0].text()


def test_switching_language_redraws_the_window_and_keeps_the_queue(app):
    from cepxico import i18n

    app.add_file("a.pdf")
    app._on_file_done("a.pdf", FileResult(Path("a.pdf"), Outcome.REVIEW, "Paid to account …1234"))

    app.switch_language("es")

    assert i18n.get_language() == "es" and app.settings.language == "es"
    assert app.windowTitle() == "CEPxico - Verificador de comprobantes SPEI"
    item = app.items["a.pdf"]
    assert item.row.text(1) == "Revisar"  # status in the new language
    assert item.row.text(0) == "a.pdf"
    assert app.tree.topLevelItemCount() == 1
    assert app.counts["review"] == 1
    assert app.process_button.text() == "Procesar archivos"
    assert yes_button_text() == "&Sí"  # Qt's own words too, as in message boxes

    app.switch_language("en")
    assert app.process_button.text() == "Process Files"
    assert yes_button_text() == "&Yes"
    app.settings = Settings()


def test_history_window_searches_and_exports(app, tmp_path, monkeypatch):
    import csv

    from cepxico.gui import history_dialog
    from cepxico.history import Check, History

    history = History(tmp_path / "h.sqlite3")
    for name, outcome, key in [("juan.pdf", "success", "MBAN01"), ("pedro.pdf", "review", "BNET02")]:
        history.add(Check("2026-11-17T10:00:00-06:00", name, f"C:/{name}", "", outcome, "", tracking_key=key))
    opened = []
    dialog = history_dialog.HistoryDialog(app, history=history, on_open=opened.append)

    assert [c.file_name for c in dialog.shown] == ["pedro.pdf", "juan.pdf"]  # newest first
    dialog.search.setText("mban")
    assert [c.file_name for c in dialog.shown] == ["juan.pdf"]
    assert dialog.tree.topLevelItemCount() == 1

    out = tmp_path / "export.csv"
    monkeypatch.setattr(history_dialog.messages, "save_file", lambda *a, **k: str(out))
    dialog.export()
    assert [r["File"] for r in csv.DictReader(out.open(encoding="utf-8-sig"))] == ["juan.pdf"]
    dialog.reject()


def test_history_window_forgets_a_check(app, tmp_path, monkeypatch):
    from cepxico.gui import history_dialog
    from cepxico.history import Check, History

    history = History(tmp_path / "h.sqlite3")
    history.add(Check("2026-11-17T10:00:00-06:00", "juan.pdf", "C:/juan.pdf", "", "success", ""))
    dialog = history_dialog.HistoryDialog(app, history=history, on_open=lambda _p: None)
    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
    monkeypatch.setattr(history_dialog.messages, "ask", lambda *a, **k: True)

    dialog.forget()

    assert history.checks() == [] and dialog.shown == []
    dialog.reject()


def test_pasting_copied_files_queues_them(app, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QGuiApplication

    files = [tmp_path / "a.pdf", tmp_path / "b.png"]
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(f)) for f in files])
    QGuiApplication.clipboard().setMimeData(data)

    app.on_paste()

    assert [Path(p) for p in app.items] == files


def test_pasting_a_screenshot_queues_it_as_a_png(app):
    from PySide6.QtGui import QColor, QGuiApplication, QImage

    picture = QImage(40, 20, QImage.Format.Format_RGB32)
    picture.fill(QColor("white"))
    QGuiApplication.clipboard().setImage(picture)

    app.on_paste()

    (path,) = app.items
    assert path.endswith(".png") and Path(path).is_file() and path in app._temp_files


def test_dropped_files_are_queued(app, tmp_path):
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(tmp_path / "r.pdf"))])
    event = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    app.dropEvent(event)
    assert [Path(p) for p in app.items] == [tmp_path / "r.pdf"]


def test_dialog_sends_spid_when_ticked(app):
    from cepxico.gui.fields_dialog import FieldsDialog

    calls = []
    dialog = FieldsDialog(
        app,
        filename="r.pdf",
        initial={"spid": "1"},
        on_save=lambda values, check_now: calls.append(values) or {},
        on_open_receipt=lambda: None,
    )
    dialog.spid.setChecked(False)
    dialog.save(check_now=False)
    assert calls == [{"spid": "0"}]


def test_settings_show_the_data_folder(app, monkeypatch):
    from cepxico.config import app_data_dir
    from cepxico.gui import settings_dialog

    opened = []
    monkeypatch.setattr(settings_dialog, "open_path", opened.append)
    dialog = settings_dialog.SettingsDialog(app, settings=Settings(), on_save=lambda s: None)
    dialog.open_data_folder()
    assert opened == [app_data_dir()]
    dialog.reject()


# --- Look and feel ----------------------------------------------------------------------


def test_commands_are_offered_only_when_they_apply(app):
    assert not any(a.isEnabled() for a in (app.edit_action, app.remove_action, app.clear_action))
    failed_banamex(app)
    app.items["banamex.pdf"].row.setSelected(True)
    assert all(a.isEnabled() for a in (app.edit_action, app.remove_action, app.clear_action))


def test_empty_queue_says_how_to_add_files(app):
    assert app.tree.topLevelItemCount() == 0 and "Drag and drop files" in app.tree.placeholder


def details(app) -> dict[str, str]:
    """The details pane's rows, {name: value}, groups included."""
    from PySide6.QtWidgets import QTreeWidgetItemIterator

    rows = {}
    it = QTreeWidgetItemIterator(app.details)
    while it.value():
        rows[it.value().text(0)] = it.value().text(1)
        it += 1
    return rows


def test_details_show_the_receipt_and_copy_values(app):
    from PySide6.QtGui import QGuiApplication

    failed_banamex(app)
    app.items["banamex.pdf"].row.setSelected(True)
    rows = details(app)
    assert rows["Status"] == "Failed" and rows["Result"] == "Missing cuenta beneficiaria"
    assert rows["Clave de rastreo"] == "085901234567890123" and rows["Amount"] == "$48,750.00"
    assert rows["Account"] == "N/A" and "Receipt" in rows and "Banks" in rows

    clave = app.details.findItems("Clave de rastreo", Qt.MatchFlag.MatchRecursive)[0]
    app.details.setCurrentItem(clave)
    app.details.copy_value()
    assert QGuiApplication.clipboard().text() == "085901234567890123"

    app.tree.clearSelection()
    assert app.details.topLevelItemCount() == 0  # shows "Select a file to view details."


@pytest.mark.parametrize(
    ("amount", "spid", "shown"),
    [
        ("12500.5", False, "$12,500.50"),
        ("980", True, "US$980.00"),
        ("abc", False, "abc"),
        (None, False, None),
    ],
)
def test_amounts_are_shown_as_money(amount, spid, shown):
    assert gui.money(amount, spid) == shown
