from pathlib import Path

import pytest

from cepxico.banxico import CEPResult, CEPStatus
from cepxico.gui import app as gui
from cepxico.gui.app import ItemStatus, QueueItem, is_confirmed
from cepxico.models import PaymentData
from cepxico.pipeline import FileResult, Outcome


def result(path: str, outcome: Outcome, pdf_path: Path | None = None) -> FileResult:
    status = CEPStatus.FOUND if outcome is Outcome.SUCCESS else CEPStatus.NOT_FOUND
    cep = CEPResult(status, "", pdf_path=pdf_path)
    return FileResult(Path(path), outcome, "", cep=cep)


def test_confirmed_needs_success_and_the_cep_file(tmp_path):
    cep = tmp_path / "CEP.pdf"
    cep.write_bytes(b"%PDF")
    found = result("a.pdf", Outcome.SUCCESS, cep)

    assert is_confirmed(QueueItem("a.pdf", "1", ItemStatus.SUCCESS, result=found))
    assert not is_confirmed(QueueItem("a.pdf", "1", ItemStatus.PENDING))
    not_found = result("a.pdf", Outcome.NOT_FOUND)
    assert not is_confirmed(QueueItem("a.pdf", "1", ItemStatus.NOT_FOUND, result=not_found))
    failed = FileResult(Path("a.pdf"), Outcome.FAILED, "")
    assert not is_confirmed(QueueItem("a.pdf", "1", ItemStatus.FAILED, result=failed))

    cep.unlink()  # CEP deleted from the folder: check again to download it anew
    assert not is_confirmed(QueueItem("a.pdf", "1", ItemStatus.SUCCESS, result=found))


@pytest.fixture(scope="module")
def window(tmp_path_factory):
    # One window for the module: creating and destroying many Tk roots in one process
    # makes Tcl fail to initialise now and then on Windows.
    try:
        window = gui.CEPApp(tmp_path_factory.mktemp("ceps"))
    except Exception as e:  # no display, or tkdnd missing
        pytest.skip(f"Tk unavailable: {e}")
    window.withdraw()
    yield window
    window.destroy()


@pytest.fixture
def app(window, monkeypatch):
    shown = []
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda title, _msg: shown.append(title))
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda title, _msg: shown.append(title))
    # Tests start batches without running them, so a previous test may have left one "running".
    window.processing = False
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
    assert app.progress_label_var.get() == "1 / 4"  # the confirmed file counts as done
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
    assert gui.can_edit(QueueItem("a", "1", ItemStatus.FAILED))
    assert gui.can_edit(QueueItem("a", "1", ItemStatus.NOT_FOUND))
    assert not gui.can_edit(QueueItem("a", "1", ItemStatus.SUCCESS))
    assert not gui.can_edit(QueueItem("a", "1", ItemStatus.PENDING))
    edited = PaymentData("a", edited_fields=("amount",))
    assert gui.can_edit(QueueItem("a", "1", ItemStatus.PENDING, corrected=edited))  # saved, not checked yet


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
    dialog.vars["beneficiary_account"].set(CLABE)
    dialog.vars["amount"].set("x")

    dialog.save(check_now=True)

    assert calls == [({"beneficiary_account": CLABE, "amount": "x"}, True)]
    assert dialog.notes["amount"].cget("text") == "'x' isn't a valid amount"
    assert dialog.winfo_exists()  # stays open to fix it

    dialog.vars["amount"].set("48750.00")  # back to what was read: no longer a change
    dialog.save(check_now=False)

    assert calls[-1] == ({"beneficiary_account": CLABE}, False)
    assert not dialog.winfo_exists()
