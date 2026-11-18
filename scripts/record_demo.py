"""Makes the README's pictures: demo GIFs recorded from the real desktop app, and the logo.

    python scripts/record_demo.py            # docs/demo-check.gif, docs/demo-edit.gif, docs/logo.png
    python scripts/record_demo.py --show     # also keeps the window on screen while recording

Everything shown is made up: the receipts are drawn here with invented names, accounts
and claves de rastreo, and Banxico is replaced by a stand-in that "finds" every transfer
except the one meant to look fake. Nothing is sent to Banxico. The app itself (reading
the receipts with OCR, identifying banks, comparing the CEP, the history that catches a
receipt used twice) is the real code. Uses a temporary data folder, so the real settings
and history are left alone. Windows fonts (Segoe UI) give the best look; others fall
back to Pillow's default font.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA = ROOT / "tests" / "data"
FONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"

FPS = 12
CANVAS_WIDTH = 1040  # final GIF width in pixels
WINDOW_SIZE = (1000, 600)  # logical size of the app's window while recording
PAD = 28  # around the window, in GIF pixels
BACKGROUND = (226, 232, 240)
DATE = "17/11/2026"

# --- Sample receipts (all invented) ---------------------------------------------------


def clabe(first17: str) -> str:
    weights = (3, 7, 1)
    total = sum((int(d) * weights[i % 3]) % 10 for i, d in enumerate(first17))
    return first17 + str((10 - total % 10) % 10)


MY_COMPANY = "MI TIENDITA SA DE CV"
RECEIPTS = {
    # file name: (sender bank, receiver CLABE, amount, clave de rastreo, payer, concept)
    "pago_ramirez.png": (
        "BANORTE",
        clabe("01218000118359725"),
        "12,450.00",
        "MBAN01002611170042871633",
        "JUAN RAMIREZ LOPEZ",
        "FACTURA 1021",
    ),
    "factura_F-1022.pdf": (
        "BBVA MEXICO",
        clabe("01418065432109876"),
        "3,980.50",
        "BNET01002611170034521987",
        "COMERCIAL DEL NORTE SA DE CV",
        "F-1022",
    ),
    "foto_transferencia.jpg": (
        "SANTANDER",
        clabe("01218000118359725"),
        "860.00",
        "2026111740014TRANSF0000187",
        "ANA SOFIA TORRES",
        "PEDIDO 588",
    ),
    "comprobante_dudoso.png": (
        "BANAMEX",
        clabe("01218000118359725"),
        "25,000.00",
        "085904417211170019283746",
        "CARLOS MENDOZA",
        "ANTICIPO",
    ),
}
REUSED = ("pago_ramirez.png", "pago_ramirez (reenviado).png")  # the same transfer, sent again
FAKE_CLAVE = "085904417211170019283746"  # Banxico "has no such transfer"
MASKED = (
    "pago_bancanet.pdf",
    "BANAMEX",
    clabe("01218000118359725"),
    "48,750.00",
    "085901234567891117220155",
    "DISTRIBUIDORA HIDALGO SA DE CV",
    "PEDIDO 612",
)


def font(size: int, bold: bool = False):
    from PIL import ImageFont

    path = FONTS / ("segoeuib.ttf" if bold else "segoeui.ttf")
    return ImageFont.truetype(str(path), size) if path.is_file() else ImageFont.load_default(size=size)


def receipt_image(sender, account, amount, clave, payer, concept, account_shown=None):
    from PIL import Image, ImageDraw

    rows = [
        ("Fecha de aplicación:", DATE),
        ("Hora:", "11:42:08"),
        ("Banco emisor:", sender),
        ("Ordenante:", payer),
        ("Banco receptor:", "BBVA MEXICO" if account.startswith("012") else "SANTANDER"),
        ("Beneficiario:", MY_COMPANY),
        ("Cuenta beneficiaria:", account_shown or account),
        ("Importe:", f"${amount} MXN"),
        ("Concepto:", concept),
        ("Clave de rastreo:", clave),
    ]
    img = Image.new("RGB", (1000, 250 + 62 * len(rows)), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, img.width, 120), fill=(30, 58, 95))
    draw.text((40, 26), "Comprobante de transferencia", fill="white", font=font(40, bold=True))
    draw.text((40, 78), "Transferencia SPEI", fill=(190, 205, 225), font=font(24))
    draw.text((40, 150), "Operación exitosa", fill=(35, 160, 90), font=font(30, bold=True))
    for i, (label, value) in enumerate(rows):
        y = 215 + 62 * i
        draw.text((40, y), label, fill=(90, 100, 115), font=font(28))
        draw.text((400, y), value, fill="black", font=font(28, bold=True))
    return img


def receipt_pdf(path: Path, sender, account, amount, clave, payer, concept, account_shown=None):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(0, 0, page.rect.width, 70), color=None, fill=(0.12, 0.23, 0.37))
    page.insert_text(
        (40, 42), "Comprobante de transferencia SPEI", fontsize=18, fontname="hebo", color=(1, 1, 1)
    )
    rows = [
        ("Fecha de aplicación:", DATE),
        ("Banco emisor:", sender),
        ("Ordenante:", payer),
        ("Banco receptor:", "BBVA MEXICO" if account.startswith("012") else "SANTANDER"),
        ("Beneficiario:", MY_COMPANY),
        ("Cuenta beneficiaria:", account_shown or account),
        ("Importe:", f"${amount} MXN"),
        ("Concepto:", concept),
        ("Clave de rastreo:", clave),
    ]
    for i, (label, value) in enumerate(rows):
        y = 110 + 24 * i
        page.insert_text((40, y), label, fontsize=11, fontname="helv", color=(0.35, 0.4, 0.45))
        page.insert_text((200, y), value, fontsize=11, fontname="hebo")
    doc.save(path)


def make_receipts(folder: Path) -> tuple[list[Path], Path]:
    from PIL import Image

    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, data in RECEIPTS.items():
        path = folder / name
        if name.endswith(".pdf"):
            receipt_pdf(path, *data)
        else:
            img = receipt_image(*data)
            if name.endswith(".jpg"):  # a phone photo: tilted, on a desk
                img = img.rotate(-4, expand=True, fillcolor=(205, 200, 190), resample=Image.BICUBIC)
                img.save(path, "JPEG", quality=88)
            else:
                img.save(path)
        paths.append(path)
    reused = folder / REUSED[1]
    reused.write_bytes((folder / REUSED[0]).read_bytes() + b"\0")  # another file, same transfer
    paths.append(reused)

    masked = folder / MASKED[0]
    receipt_pdf(masked, *MASKED[1:], account_shown="***************756")
    return paths, masked


# --- Stand-in for Banxico ---------------------------------------------------------------


class DemoBanxico:
    """Answers like Banxico's CEP service would for the sample receipts."""

    def __init__(self, output_dir: Path):
        from cepxico.banks import BankCatalog

        rows = json.loads((DATA / "instituciones_2026-11-10.json").read_text(encoding="utf-8"))
        self.catalog = BankCatalog.from_rows(rows["instituciones"])
        self.output_dir = Path(output_dir)

    def get_catalog(self, _fecha):
        return self.catalog

    def download_cep(self, *, fecha, clave_rastreo, sender, receiver, account, amount, **_):
        import pymupdf

        from cepxico.banxico import CEPRecord, CEPResult, CEPStatus, Party

        time.sleep(random.uniform(0.8, 1.6))  # Banxico takes a moment
        if clave_rastreo == FAKE_CLAVE:
            return CEPResult(CEPStatus.NOT_FOUND, "Operación no encontrada")
        payer = next((d[4] for d in [*RECEIPTS.values(), MASKED[1:]] if d[3] == clave_rastreo), "ORDENANTE")
        record = CEPRecord(
            operation_date=fecha,
            time="11:42:08",
            tracking_key=clave_rastreo,
            amount=f"{float(str(amount).replace(',', '')):.2f}",
            concept="PAGO",
            sender=Party(sender.name, payer, "072180000000000013", ""),
            beneficiary=Party(receiver.name, MY_COMPANY, account, ""),
            certificate="",
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = self.output_dir / f"CEP_{fecha}_{clave_rastreo}.pdf"
        doc = pymupdf.open()
        doc.new_page().insert_text((50, 80), "Sample CEP (demo)")
        doc.save(pdf_path)
        return CEPResult(CEPStatus.FOUND, "CEP downloaded", pdf_path=pdf_path, record=record)

    def close(self):
        pass


# --- Recording ----------------------------------------------------------------------------


def to_pil(pixmap, alpha: bool = False):
    from PIL import Image
    from PySide6.QtGui import QImage

    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    data = bytes(image.constBits())
    return Image.frombuffer(
        "RGBA", (image.width(), image.height()), data, "raw", "RGBA", image.bytesPerLine(), 1
    ).convert("RGBA" if alpha else "RGB")


def ease(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


class Recorder:
    """Captures the window (plus any open dialog) FPS times a second and draws a pointer."""

    def __init__(self, window):
        from PySide6.QtCore import QTimer

        self.window = window
        self.frames: list = []
        self.times: list[float] = []
        self._background = None  # canvas with the window's shadow, drawn once
        self.cursor = (WINDOW_SIZE[0] + 40.0, WINDOW_SIZE[1] * 0.75)  # window coordinates
        self._move: tuple | None = None
        self.click_at: float | None = None
        self.dragging: str | None = None  # label of the files being dragged
        self.timer = QTimer(interval=1000 // FPS, timeout=self.capture)

    def move(self, x: float, y: float, seconds: float = 0.7) -> None:
        self._move = (self.cursor, (x, y), time.monotonic(), seconds)

    def click(self) -> None:
        self.click_at = time.monotonic()

    def _cursor_now(self):
        if self._move:
            start, end, began, seconds = self._move
            t = ease((time.monotonic() - began) / seconds)
            self.cursor = (start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t)
            if t >= 1:
                self._move = None
        return self.cursor

    def capture(self) -> None:
        import warnings

        from PIL import Image, ImageDraw
        from PySide6.QtWidgets import QApplication, QDialog

        dialogs = [w for w in QApplication.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]
        active = dialogs[0] if dialogs else self.window
        if QApplication.activeWindow() is not active:
            # Hidden windows are never active, and Windows draws inactive menus greyed out.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                QApplication.setActiveWindow(active)

        shot = to_pil(self.window.grab())
        scale = shot.width / self.window.width()
        bar = int(32 * scale)
        framed = Image.new("RGB", (shot.width, shot.height + bar), "white")
        framed.paste(title_bar(shot.width, bar, self.window.windowTitle()), (0, 0))
        framed.paste(shot, (0, bar))
        for widget in dialogs:
            dialog = to_pil(widget.grab())
            box = Image.new("RGB", (dialog.width, dialog.height + bar), "white")
            box.paste(title_bar(dialog.width, bar, widget.windowTitle()), (0, 0))
            box.paste(dialog, (0, bar))
            x = (framed.width - box.width) // 2
            y = (framed.height - box.height) // 2
            shadow(framed, (x, y, x + box.width, y + box.height), int(12 * scale))
            framed.paste(box, (x, y))
            ImageDraw.Draw(framed).rectangle(
                (x, y, x + box.width - 1, y + box.height - 1), outline=(170, 175, 185)
            )

        # Fit into the canvas, then draw the pointer at canvas scale (crisp).
        inner = CANVAS_WIDTH - 2 * PAD
        fit = inner / framed.width
        framed = framed.resize((inner, round(framed.height * fit)), Image.LANCZOS)
        if self._background is None:
            self._background = Image.new("RGB", (CANVAS_WIDTH, framed.height + 2 * PAD), BACKGROUND)
            shadow(self._background, (PAD, PAD, PAD + framed.width, PAD + framed.height), 10)
        canvas = self._background.copy()
        canvas.paste(framed, (PAD, PAD))
        cx, cy = self._cursor_now()
        k = scale * fit  # window logical px -> canvas px
        point = (PAD + cx * k, PAD + (cy + 32) * k)
        if self.click_at is not None:
            age = time.monotonic() - self.click_at
            if age < 0.45:
                r = 6 + 34 * age
                alpha = int(200 * (1 - age / 0.45))
                ring = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                ImageDraw.Draw(ring).ellipse(
                    (point[0] - r, point[1] - r, point[0] + r, point[1] + r),
                    outline=(59, 125, 237, alpha),
                    width=4,
                )
                canvas.paste(ring, (0, 0), ring)
        if self.dragging:
            draw_chip(canvas, point, self.dragging)
        draw_pointer(canvas, point)
        self.frames.append(canvas)
        self.times.append(time.monotonic())


def title_bar(width: int, height: int, title: str):
    """A plain window title bar: the app's name and the usual buttons, nothing more."""
    from PIL import Image, ImageDraw

    from cepxico.gui import theme

    bar = Image.new("RGB", (width, height), (243, 243, 243))
    draw = ImageDraw.Draw(bar)
    size = height // 2
    icon = to_pil(theme.app_icon().pixmap(size, size), alpha=True).resize((size, size), Image.LANCZOS)
    bar.paste(icon, (height // 3, height // 4), icon)
    draw.text(
        (height // 3 + size + height // 3, height // 2),
        title,
        fill=(30, 30, 30),
        font=font(int(height * 0.36)),
        anchor="lm",
    )
    ink, line, r = (70, 70, 70), max(1, height // 32), height * 0.15
    for i in range(3):  # close, maximize, minimize, from the right
        cx, cy = width - height * 1.45 * (i + 0.5), height / 2
        if i == 0:
            draw.line((cx - r, cy - r, cx + r, cy + r), fill=ink, width=line)
            draw.line((cx - r, cy + r, cx + r, cy - r), fill=ink, width=line)
        elif i == 1:
            draw.rectangle((cx - r, cy - r, cx + r, cy + r), outline=ink, width=line)
        else:
            draw.line((cx - r, cy, cx + r, cy), fill=ink, width=line)
    draw.line((0, height - 1, width, height - 1), fill=(225, 225, 225))
    return bar


def shadow(canvas, box, radius: int) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    x0, y0, x1, y1 = box
    layer = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(layer).rectangle((x0, y0 + radius // 3, x1, y1 + radius // 3), fill=90)
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    canvas.paste((0, 0, 0), (0, 0), layer)


def draw_pointer(canvas, point) -> None:
    from PIL import ImageDraw

    x, y = point
    shape = [(0, 0), (0, 17), (4.5, 13), (7.5, 20), (10, 19), (7, 12.5), (12.5, 12.5)]
    ImageDraw.Draw(canvas).polygon([(x + a, y + b) for a, b in shape], fill="white", outline="black", width=1)


def draw_chip(canvas, point, label: str) -> None:
    from PIL import ImageDraw

    x, y = point[0] + 14, point[1] + 16
    draw = ImageDraw.Draw(canvas)
    text_font = font(14, bold=True)
    width = draw.textlength(label, font=text_font) + 38
    draw.rounded_rectangle((x, y, x + width, y + 30), radius=7, fill=(59, 125, 237))
    # a little page icon
    draw.rectangle((x + 9, y + 7, x + 21, y + 23), fill="white")
    draw.line((x + 12, y + 12, x + 18, y + 12), fill=(59, 125, 237), width=1)
    draw.line((x + 12, y + 16, x + 18, y + 16), fill=(59, 125, 237), width=1)
    draw.text((x + 28, y + 15), label, fill="white", font=text_font, anchor="lm")


# --- Scripted scenes ------------------------------------------------------------------------

Step = float | Callable[[], bool]  # seconds to wait, or a condition to wait for


def center_of(widget, window, rect=None):
    from PySide6.QtCore import QPoint

    rect = rect or widget.rect()
    p = widget.mapTo(window, rect.center() if hasattr(rect, "center") else QPoint())
    return p.x(), p.y()


def in_dialog(window, dialog, widget):
    """Where `widget` is in window coordinates, with the dialog drawn centered under a
    32 px title bar, as the recorder draws it."""
    p = widget.mapTo(dialog, widget.rect().center())
    x0 = (window.width() - dialog.width()) / 2
    y0 = (window.height() - dialog.height()) / 2 - 32
    return x0 + p.x(), y0 + 32 + p.y()


def row_center(window, index: int):
    tree = window.tree
    rect = tree.visualItemRect(tree.topLevelItem(index))
    p = tree.viewport().mapTo(window, rect.center())
    return 120.0, float(p.y())


def scene_check(window, rec: Recorder, receipts: list[Path]) -> Iterator[Step]:
    yield 0.8
    rec.dragging = f"{len(receipts)} receipts"
    rec.move(330, 260, 1.2)
    yield 1.3
    rec.dragging = None
    rec.click()
    window.on_drop([str(p) for p in receipts])
    yield 1.0
    x, y = center_of(window.process_button, window)
    rec.move(x, y, 0.8)
    yield 1.0
    rec.click()
    window.process_files()
    rec.move(700, 330, 1.0)
    yield lambda: not window.processing
    yield 0.8
    x, y = row_center(window, 0)
    rec.move(x, y, 0.8)
    yield 0.9
    rec.click()
    window.tree.setCurrentItem(window.tree.topLevelItem(0))
    yield 2.6
    x, y = row_center(window, len(receipts) - 1)
    rec.move(x, y, 0.7)
    yield 0.8
    rec.click()
    window.tree.setCurrentItem(window.tree.topLevelItem(len(receipts) - 1))
    yield 3.0


def scene_edit(window, rec: Recorder, masked: Path) -> Iterator[Step]:
    from PySide6.QtWidgets import QApplication, QPushButton

    from cepxico.gui.fields_dialog import FieldsDialog
    from cepxico.i18n import tr

    window.on_drop([str(masked)])
    rec.cursor = (420.0, 330.0)
    yield 0.6
    x, y = center_of(window.process_button, window)
    rec.move(x, y, 0.8)
    yield 0.9
    rec.click()
    window.process_files()
    yield lambda: not window.processing
    yield 0.6
    x, y = row_center(window, 0)
    rec.move(x, y, 0.8)
    yield 0.9
    rec.click()
    window.tree.setCurrentItem(window.tree.topLevelItem(0))
    yield 1.6
    rec.click()
    window.edit_selected()  # double-click
    yield 0.6
    dialog = next(w for w in QApplication.topLevelWidgets() if isinstance(w, FieldsDialog) and w.isVisible())
    entry = dialog.fields["beneficiary_account"]
    rec.move(*in_dialog(window, dialog, entry), 0.8)
    yield 0.9
    rec.click()
    entry.setFocus()
    yield 0.4
    for i in range(1, len(MASKED[2]) + 1):
        entry.setText(MASKED[2][:i])
        yield 0.07
    yield 0.5
    button = next(b for b in dialog.findChildren(QPushButton) if b.text() == tr("Save and Check"))
    rec.move(*in_dialog(window, dialog, button), 0.7)
    yield 0.8
    rec.click()
    dialog.save(check_now=True)
    yield lambda: not window.processing
    yield 3.0


def run(steps: Iterator[Step]) -> None:
    """Runs a scene's steps while Qt's event loop keeps the window (and recorder) going."""
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    state = {"until": 0.0, "cond": None}

    def tick():
        now = time.monotonic()
        cond = state["cond"]
        if cond is not None and not cond():
            return
        if cond is None and now < state["until"]:
            return
        try:
            step = next(steps)
        except StopIteration:
            loop.quit()
            return
        if callable(step):
            state["cond"], state["until"] = step, 0.0
        else:
            state["cond"], state["until"] = None, now + step

    driver = QTimer(interval=20, timeout=tick)
    driver.start()
    loop.exec()
    driver.stop()


def save_gif(frames, times: list[float], out: Path) -> None:
    from PIL import Image

    # One palette for every frame (from a few spread-out frames), no dithering: flat UI
    # colors stay flat and text stays crisp.
    picks = frames[:: max(1, len(frames) // 6)][:6]
    sample = Image.new("RGB", (frames[0].width, frames[0].height * len(picks)))
    for i, frame in enumerate(picks):
        sample.paste(frame, (0, frame.height * i))
    palette = sample.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    height = max(f.height for f in frames)
    quantized = []
    for frame in frames:
        if frame.height != height:
            padded = Image.new("RGB", (frame.width, height), BACKGROUND)
            padded.paste(frame, (0, 0))
            frame = padded
        quantized.append(frame.quantize(palette=palette, dither=Image.Dither.NONE))
    out.parent.mkdir(parents=True, exist_ok=True)
    # Each frame lasts until the next was captured, so the GIF plays at the real speed.
    durations = [round((b - a) * 1000) for a, b in zip(times, times[1:], strict=False)] + [1000 // FPS]
    quantized[0].save(
        out,
        save_all=True,
        append_images=quantized[1:],
        duration=durations,
        loop=0,
        optimize=False,
        disposal=1,
    )
    print(f"{out.relative_to(ROOT)}: {len(frames)} frames, {out.stat().st_size / 1e6:.1f} MB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show", action="store_true", help="keep the window on screen")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="cepxico-demo-"))
    os.environ["CEPXICO_HOME"] = str(work / "appdata")
    sys.path.insert(0, str(ROOT / "src"))

    from PySide6.QtCore import Qt

    from cepxico import pipeline
    from cepxico.gui import app as gui
    from cepxico.gui import theme
    from cepxico.history import History
    from cepxico.settings import Settings, save_settings

    save_settings(Settings(language="en"))
    pipeline.banxico_open = lambda now=None: True  # record at any hour
    pipeline.BanxicoCEPClient = lambda output_dir, catalogs=None: DemoBanxico(output_dir)
    random.seed(7)

    original_present = theme.present

    def present(dialog, parent, size=None):
        if not args.show:
            dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        original_present(dialog, parent, size)

    theme.present = present
    gui.messages.info = gui.messages.warning = lambda *a, **k: None

    os.chdir(work)  # receipts are added as Recibos/..., so no user folder shows in the window
    receipts, masked = make_receipts(Path("Recibos"))
    for name, scene in (("check", scene_check), ("edit", scene_edit)):
        theme.application().styleHints().setColorScheme(Qt.ColorScheme.Light)
        window = gui.CEPApp(work / f"CEPs-{name}", history=History(work / f"history-{name}.sqlite3"))
        if not args.show:
            window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.resize(*WINDOW_SIZE)
        window.show()
        rec = Recorder(window)
        rec.timer.start()
        steps = scene(window, rec, receipts if name == "check" else masked)
        run(steps)
        rec.timer.stop()
        window.close()
        save_gif(rec.frames, rec.times, DOCS / f"demo-{name}.gif")

    from cepxico.gui import icons

    icons.logo(256, theme.LOGO_INK, theme.STATUS_COLORS["status_success"]).save(DOCS / "logo.png")
    os.chdir(ROOT)
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
