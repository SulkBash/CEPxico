"""Text extraction: OCR line grouping, engine selection, and a real RapidOCR run."""

import io

import pytest

from cepxico.extraction import text
from cepxico.extraction.parser import parse_payment
from cepxico.extraction.text import ExtractionError, extract_text, get_ocr_engine, lines_from_boxes


def box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


class TestLinesFromBoxes:
    def test_label_and_value_columns_become_one_line(self):
        boxes = [box(400, 102, 800, 128), box(20, 100, 300, 130), box(20, 160, 200, 190)]
        texts = ["MBAN01002611050012345678", "Clave de rastreo", "Importe"]
        assert lines_from_boxes(boxes, texts) == ["Clave de rastreo MBAN01002611050012345678", "Importe"]

    def test_slightly_skewed_boxes_stay_on_their_line(self):
        boxes = [box(20, 100, 300, 130), box(400, 108, 600, 136), box(20, 140, 300, 170)]
        assert lines_from_boxes(boxes, ["a", "b", "c"]) == ["a b", "c"]

    def test_empty(self):
        assert lines_from_boxes([], []) == []


def missing(module: str):
    def factory():
        raise ImportError(f"No module named '{module}'", name=module)

    return factory


class TestEngineSelection:
    @pytest.fixture(autouse=True)
    def fresh_cache(self):
        get_ocr_engine.cache_clear()
        yield
        get_ocr_engine.cache_clear()

    def test_unknown_engine(self):
        with pytest.raises(ExtractionError, match="Unknown OCR engine 'tesseract'"):
            get_ocr_engine("tesseract")

    def test_falls_back_to_next_installed_engine(self, monkeypatch):
        monkeypatch.setitem(text._ENGINE_FACTORIES, "rapidocr", missing("rapidocr"))
        monkeypatch.setitem(text._ENGINE_FACTORIES, "easyocr", lambda: "easy")
        monkeypatch.delenv(text.OCR_ENGINE_ENV, raising=False)
        assert get_ocr_engine() == "easy"

    def test_env_var_forces_an_engine(self, monkeypatch):
        monkeypatch.setitem(text._ENGINE_FACTORIES, "rapidocr", lambda: "rapid")
        monkeypatch.setitem(text._ENGINE_FACTORIES, "easyocr", lambda: "easy")
        monkeypatch.setenv(text.OCR_ENGINE_ENV, "EasyOCR")
        assert get_ocr_engine() == "easy"

    def test_forced_engine_missing_does_not_fall_back(self, monkeypatch):
        monkeypatch.setitem(text._ENGINE_FACTORIES, "easyocr", missing("easyocr"))
        with pytest.raises(ExtractionError, match="'easyocr' is not installed"):
            get_ocr_engine("easyocr")

    def test_broken_dependency_is_reported_not_skipped(self, monkeypatch):
        monkeypatch.setitem(text._ENGINE_FACTORIES, "rapidocr", missing("cv2"))
        monkeypatch.setitem(text._ENGINE_FACTORIES, "easyocr", lambda: "easy")
        with pytest.raises(ExtractionError, match="'rapidocr' failed to load: No module named 'cv2'"):
            get_ocr_engine()

    def test_nothing_installed(self, monkeypatch):
        for name in text.OCR_ENGINES:
            monkeypatch.setitem(text._ENGINE_FACTORIES, name, missing(name))
        monkeypatch.delenv(text.OCR_ENGINE_ENV, raising=False)
        with pytest.raises(ExtractionError, match="no OCR engine is installed"):
            get_ocr_engine()


def render_receipt(lines: list[str]) -> bytes:
    """A synthetic screenshot-like receipt: labels left, values right."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=28)
    img = Image.new("RGB", (1100, 60 + 60 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    for i, (label, value) in enumerate(lines):
        draw.text((30, 30 + 60 * i), label, fill="black", font=font)
        draw.text((520, 30 + 60 * i), value, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_rapidocr_reads_a_two_column_receipt(tmp_path, monkeypatch):
    pytest.importorskip("rapidocr")
    monkeypatch.delenv(text.OCR_ENGINE_ENV, raising=False)
    get_ocr_engine.cache_clear()
    image = tmp_path / "comprobante año.png"  # non-ASCII path on purpose
    image.write_bytes(
        render_receipt(
            [
                ("Fecha de aplicación:", "05/11/2026"),
                ("Clave de Rastreo:", "MBAN01002611050012345678"),
                ("Banco receptor:", "BBVA MEXICO"),
                ("Cuenta Beneficiaria:", "012180001234567893"),
                ("Importe:", "$1,234.50 MXN"),
            ]
        )
    )

    p = parse_payment(extract_text(image))

    assert p.payment_date == "05-11-2026"
    assert p.tracking_key == "MBAN01002611050012345678"
    assert p.receiver_bank == "BBVA MEXICO"
    assert p.beneficiary_account == "012180001234567893"
    assert p.amount == "1234.50"


# --- PDF text ------------------------------------------------------------------

PDF_FIELDS = [
    ("Fecha de aplicación:", "05/11/2026"),
    ("Clave de Rastreo:", "MBAN01002611050012345678"),
    ("Banco receptor:", "BBVA MEXICO"),
    ("Cuenta Beneficiaria:", "012180001234567893"),
    ("Importe:", "$1,234.50 MXN"),
]


def make_pdf(
    path, *, leading=18.0, value_size=10.0, value_dy=0.0, per_glyph=False, stream_values_first=False
):
    """A text PDF receipt: labels at x=50, values at x=230 (bold).

    per_glyph: every glyph drawn on its own with no space characters, as some
    generators do. stream_values_first: values drawn before labels, so the content
    stream order differs from the reading order."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()

    def draw(x, y, s, size, font):
        if not per_glyph:
            page.insert_text((x, y), s, fontsize=size, fontname=font)
            return
        for ch in s:
            if ch != " ":
                page.insert_text((x, y), ch, fontsize=size, fontname=font)
            x += pymupdf.get_text_length(ch, font, size)

    labels = [(50, 90 + i * leading, label, 10, "helv") for i, (label, _) in enumerate(PDF_FIELDS)]
    values = [
        (230, 90 + i * leading + value_dy, value, value_size, "hebo")
        for i, (_, value) in enumerate(PDF_FIELDS)
    ]
    if stream_values_first:
        ops = values + labels
    else:
        ops = [op for pair in zip(labels, values, strict=True) for op in pair]
    for op in ops:
        draw(*op)
    doc.save(path)


@pytest.mark.parametrize(
    "layout",
    [
        {},
        {"stream_values_first": True},
        # Lines closer than the font's full height, with a bigger, lower value: full-height
        # word boxes overlap here and used to merge every line into one.
        {"leading": 9.5, "value_size": 12, "value_dy": 2},
    ],
    ids=["plain", "stream-out-of-order", "tight-lines"],
)
def test_pdf_label_and_value_columns_become_lines(tmp_path, layout):
    pdf = tmp_path / "comprobante.pdf"
    make_pdf(pdf, **layout)

    lines = extract_text(pdf).splitlines()

    assert lines == [f"{label} {value}" for label, value in PDF_FIELDS]


def test_pdf_glyphs_drawn_one_by_one_keep_word_spaces(tmp_path):
    pdf = tmp_path / "comprobante.pdf"
    make_pdf(pdf, per_glyph=True)

    p = parse_payment(extract_text(pdf))

    assert p.receiver_bank == "BBVA MEXICO"  # pdfplumber read "BBVAMEXICO"
    assert p.tracking_key == "MBAN01002611050012345678"
    assert p.amount == "1234.50"


# --- Photos taken at an angle or sideways ------------------------------------------


def rotated(boxes, degrees):
    """Boxes as they'd come from a photo turned `degrees` clockwise."""
    import math

    cos, sin = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [[[x * cos - y * sin, x * sin + y * cos] for x, y in b] for b in boxes]


RECEIPT_BOXES = [
    box(30, 100, 330, 130),
    box(700, 100, 1060, 130),
    box(30, 150, 200, 180),
    box(700, 150, 900, 180),
    box(30, 200, 360, 230),
    box(700, 200, 1000, 230),
]
RECEIPT_TEXTS = [
    "Clave de rastreo",
    "MBAN01002611050012345678",
    "Importe",
    "$1,234.50",
    "Cuenta Beneficiaria",
    "012180001234567893",
]
RECEIPT_LINES = [
    "Clave de rastreo MBAN01002611050012345678",
    "Importe $1,234.50",
    "Cuenta Beneficiaria 012180001234567893",
]


@pytest.mark.parametrize("degrees", [-12, -6, -3, 3, 6, 12])
def test_tilted_photo_keeps_labels_and_values_on_one_line(degrees):
    tilted = rotated(RECEIPT_BOXES, degrees)
    assert text.skew_degrees(tilted) == pytest.approx(degrees)
    assert lines_from_boxes(tilted, RECEIPT_TEXTS) == RECEIPT_LINES


def test_tilted_photo_would_mix_up_lines_without_straightening(monkeypatch):
    """Guards the test above: at 6 degrees, plain grouping really does go wrong."""
    monkeypatch.setattr(text, "MIN_SKEW_DEGREES", 90)
    assert lines_from_boxes(rotated(RECEIPT_BOXES, 6), RECEIPT_TEXTS) != RECEIPT_LINES


def test_straight_text_is_left_alone():
    assert text.skew_degrees(RECEIPT_BOXES) == 0
    assert lines_from_boxes(RECEIPT_BOXES, RECEIPT_TEXTS) == RECEIPT_LINES


def test_short_boxes_dont_decide_the_tilt():
    # Short boxes (a "$", a digit) have unreliable slopes; only long text runs count.
    noisy = [[[0, 0], [10, 8], [10, 20], [0, 12]]] * 5  # 39 degrees, but barely wider than tall
    assert text.skew_degrees(noisy + RECEIPT_BOXES) == 0


def jpeg_with_orientation(size, orientation: int) -> bytes:
    from PIL import Image

    image = Image.new("RGB", size, "white")
    exif = image.getexif()
    exif[0x0112] = orientation
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif)
    return out.getvalue()


def test_sideways_phone_photo_is_turned_upright():
    from PIL import Image

    sideways = jpeg_with_orientation((40, 20), 6)  # stored landscape, shot portrait
    with Image.open(io.BytesIO(text.upright_image(sideways))) as upright:
        assert upright.size == (20, 40)


def test_upright_or_unreadable_images_are_passed_through():
    upright = jpeg_with_orientation((40, 20), 1)
    assert text.upright_image(upright) is upright
    assert text.upright_image(b"not an image") == b"not an image"


RECEIPT_FIELDS = [
    ("Fecha de aplicación:", "05/11/2026"),
    ("Clave de Rastreo:", "MBAN01002611050012345678"),
    ("Banco receptor:", "BBVA MEXICO"),
    ("Cuenta Beneficiaria:", "012180001234567893"),
    ("Importe:", "$1,234.50 MXN"),
]


def assert_receipt_fields(p):
    assert p.payment_date == "05-11-2026"
    assert p.tracking_key == "MBAN01002611050012345678"
    assert p.receiver_bank == "BBVA MEXICO"
    assert p.beneficiary_account == "012180001234567893"
    assert p.amount == "1234.50"


@pytest.mark.parametrize("degrees", [-7, 5])
def test_rapidocr_reads_a_receipt_photographed_at_an_angle(tmp_path, monkeypatch, degrees):
    pytest.importorskip("rapidocr")
    from PIL import Image

    monkeypatch.delenv(text.OCR_ENGINE_ENV, raising=False)
    get_ocr_engine.cache_clear()
    with Image.open(io.BytesIO(render_receipt(RECEIPT_FIELDS))) as image:
        # PIL turns counterclockwise for positive angles.
        image.rotate(-degrees, expand=True, fillcolor="white", resample=Image.BICUBIC).save(
            tmp_path / "r.png"
        )

    assert_receipt_fields(parse_payment(extract_text(tmp_path / "r.png")))


def test_rapidocr_reads_a_sideways_phone_photo(tmp_path, monkeypatch):
    pytest.importorskip("rapidocr")
    from PIL import Image

    monkeypatch.delenv(text.OCR_ENGINE_ENV, raising=False)
    get_ocr_engine.cache_clear()
    with Image.open(io.BytesIO(render_receipt(RECEIPT_FIELDS))) as image:
        sideways = image.rotate(90, expand=True)  # stored turned; EXIF 6 says turn it back
        exif = sideways.getexif()
        exif[0x0112] = 6
        sideways.save(tmp_path / "r.jpg", "JPEG", exif=exif, quality=95)

    assert_receipt_fields(parse_payment(extract_text(tmp_path / "r.jpg")))


def test_rapidocr_reads_a_webp_receipt(tmp_path, monkeypatch):
    pytest.importorskip("rapidocr")
    from PIL import Image

    monkeypatch.delenv(text.OCR_ENGINE_ENV, raising=False)
    get_ocr_engine.cache_clear()
    with Image.open(io.BytesIO(render_receipt(RECEIPT_FIELDS))) as image:
        image.save(tmp_path / "r.webp", "WEBP", quality=90)

    assert_receipt_fields(parse_payment(extract_text(tmp_path / "r.webp")))
