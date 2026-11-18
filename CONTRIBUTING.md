# Contributing to CEPxico

Thanks for helping. This page covers setting up, the rules that keep real financial data
out of the repository, how the code fits together, and how releases are made.

## Set up

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
ruff check . ; ruff format .
```

Tests run offline and never contact Banxico. `tests/data/` holds snapshots of Banxico's
public bank catalog for 2019, 2024 and 2026, to test name changes over time. The desktop
app's tests use Qt's offscreen platform, so no window opens and no display is needed.
GitHub Actions runs them on Windows, macOS and Linux (`.github/workflows/tests.yml`).

### Never commit real receipts or CEPs

They contain account numbers and names. `.gitignore` excludes PDFs and images for this
reason (only `docs/`'s pictures, drawn from invented data, are allowed). Values copied into
tests (claves de rastreo, accounts, amounts) must be made up too.

### Translations

Every message users read goes through `tr("English text")`; add its Spanish to
`src/cepxico/translations.py`. `tests/test_i18n.py` fails on a message without a
translation, a translation whose `{placeholders}` differ, or a leftover translation.

### Supporting a new bank's receipts

Edit [`src/cepxico/data/banks.toml`](src/cepxico/data/banks.toml) and add a test; no code
changes needed. `tests/test_banks.py` checks the file against Banxico's catalog. See
[Banks](#banks) below.

## How it works

```
receipt ─► extraction ─► PaymentData ─► identify ─► sender/receiver ─► banxico ─► CEP PDF
          (text + regex)                (Banxico catalog for the date      (HTTP, no browser)
                                         + data/banks.toml)                       │
                                                                   history ◄──────┘
```

| Module | Responsibility |
|---|---|
| `extraction/text.py` | Raw text from PDFs (PyMuPDF); OCR (RapidOCR) for scans and images; straightening photos |
| `extraction/parser.py` | Pulls date, clave de rastreo, bank labels, account, amount and SPID out of text |
| `banks.py` | Banxico's catalog, the bundled bank reference data, name matching, CLABE validation |
| `identify.py` | Decides the sending and receiving bank, and records how |
| `banxico.py` | HTTP clients for Banxico's CEP services (SPEI, and SPID with a typed security code) |
| `history.py` | Every check in SQLite; receipts used twice; CSV export |
| `pipeline.py` | One receipt end to end, and batches of them concurrently; shared by CLI and GUI |
| `i18n.py`, `translations.py` | Spanish and English for everything users read |
| `config.py` | Data folder and opening files, per system |
| `cli.py` | Command line |
| `gui/` | Desktop app (Qt, in the system's own style): main window, dialogs, `icons.py` (icons drawn at run time) |

### Banks

Banxico's catalog (`instituciones.do`) is the source of truth for which banks exist and
what they're called; it's downloaded for each payment date, so renames are handled
automatically (`BBVA BANCOMER` before 2022, `BBVA MEXICO` after). Banks are identified by
their 3-digit CLABE code, which survives renames and re-licensing (`90638 NU MEXICO` →
`40638 NUBANK`).

`banks.toml` adds what the catalog lacks: legal names from Banxico's official participant
list, brands and former names, names that are ordinary words (never used when scanning a
whole receipt), and clues for recognising the sending bank. Its header documents every
field and source.

**Receiving bank:** the CLABE's first 3 digits, else the "Banco destino/receptor" field.
**Sending bank:** the "Banco emisor/origen" field, else a clave de rastreo prefix, else
bank-specific wording, else the first bank named on the receipt. The receiving bank is
never chosen as sender. The GUI's details panel shows which clue was used.

### Batches

Receipts are checked 4 at a time (`--jobs`, up to 8), since most of each check is spent
waiting on Banxico. Every lookup starts a new Banxico session: Banxico's download step
returns the CEP of the session's *last* lookup, so a reused session could save one
receipt's CEP under another's name. OCR runs one image at a time (it already uses every
CPU core).

Banxico also has a [batch service](https://www.banxico.org.mx/cep-scl/) (a text file of up
to 500 transfers, results by email). The app doesn't use it: it needs the data typed out
already, and answers hours later instead of while you watch.

### SPID requests

The SPID requests follow Banxico's own page (`js/cepspid-min.js`): dates as `yyyymmdd`,
`R` for clave de rastreo, `pagoABanco=true/false`, and a bank list of `claveSpid` /
`nombreCorto` objects (a snapshot is in `tests/data/`).

### OCR

[RapidOCR](https://github.com/RapidAI/RapidOCR) runs PaddleOCR's PP-OCRv6 models on ONNX
Runtime; the models ship inside the package, so it works offline. Text boxes are
regrouped into lines so a label and a value in separate columns ("Clave de rastreo" …
"MBAN01…") end up on one line. PDF text goes through the same grouping, so PDFs and
images reach the parser in the same layout.

Phone photos are handled in two steps:

- **Sideways:** phones save many photos turned and record the turn in the EXIF
  orientation tag; the image is turned upright before OCR.
- **At an angle:** on a receipt tilted a few degrees, a value in a far column sits a line
  above or below its label, and fields were missed. The tilt is measured from the slope
  of the text boxes and the boxes are straightened before grouping, up to 45°. On
  synthetic receipts tilted -7°, 5° and 10°, the clave de rastreo and account were lost
  without this and are read correctly with it (`tests/test_text.py`).

It replaced EasyOCR (v1), which needed PyTorch (about 2 GB). On synthetic receipts it was
about 2.7x faster per image, loaded in 2 s instead of 15 s, and misread fewer fields
(EasyOCR read `0` as `O` in claves de rastreo). To compare them on real receipts:

```bash
pip install -e ".[easyocr]"
python scripts/compare_ocr.py receipt1.png scan.pdf
```

`CEPXICO_OCR=easyocr` makes the app itself use EasyOCR.

## Build the app

```bash
pip install -e ".[build]"
pyinstaller packaging/cepxico.spec --noconfirm
```

Build on each system for that system; PyInstaller doesn't cross-compile. This makes
`dist/cepxico/` (about 340 MB, mostly OpenCV, ONNX Runtime and Qt) with `cepxico-gui`
(desktop app) and `cepxico` (command line), `.exe` on Windows. On macOS it also makes
`dist/CEPxico.app`. It runs without Python installed, on the same kind of system it was
built on (64-bit Windows, macOS on the same chip, Linux with a glibc at least as new).

The app isn't code-signed: Windows SmartScreen warns on first run ("More info" → "Run
anyway"), and macOS Gatekeeper needs right-click → Open the first time.

## Make a release

1. Set the version in `pyproject.toml` and `src/cepxico/__init__.py`. The build reads it
   from there into the Windows file details and the macOS app.
2. Publish a GitHub release with a `vX.Y.Z` tag. `.github/workflows/release.yml` builds
   the app on Windows, macOS and Linux and attaches the three downloads to it. (Run it by
   hand from the Actions tab for a test build without a release.)

## Demo pictures

The GIFs and logo in `docs/` come from `python scripts/record_demo.py`, which drives the
real desktop app with invented receipts and a stand-in for Banxico (nothing is sent to
it). Run it again after visible changes to the app.
