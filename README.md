# CEPxico

Checks that SPEI transfer receipts are real. It reads a receipt (PDF, screenshot or
pasted image), extracts the transfer data, and asks Banxico's
[CEP service](https://www.banxico.org.mx/cep/) for the official *Comprobante
Electrónico de Pago*. If Banxico returns a CEP, the transfer happened.

Each receipt ends up as one of:

| Result | Meaning |
|---|---|
| **Success** | CEP found and saved to `~/Downloads/CEPs/` |
| **Not Found** | Banxico has no transfer with that data. Check the extracted fields; the receipt may be fake |
| **Failed** | Couldn't check: unreadable file, missing data, network error, captcha… |

## Install

Requires Python 3.11+ on Windows.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

OCR for screenshots and scanned PDFs is included (RapidOCR, about 50 MB). No Python
needed for end users: see [Build the Windows app](#build-the-windows-app).

## Use

```powershell
cepxico                               # desktop app (drag & drop, Ctrl+V to paste screenshots)
cepxico receipt1.pdf receipt2.png     # command line; exit code 0 only if every CEP was found
cepxico *.pdf --out D:\CEPs -v        # custom output folder, debug logging
cepxico *.pdf --jobs 2                # receipts checked at once (default 4, max 8)
python -m cepxico                     # same as `cepxico`
```

`cepxico-gui` opens the desktop app without a console window.

## How it works

```
receipt ─► extraction ─► PaymentData ─► identify ─► sender/receiver ─► banxico ─► CEP PDF
          (text + regex)                (Banxico catalog for the date      (HTTP, no browser)
                                         + data/banks.toml)
```

| Module | Responsibility |
|---|---|
| `extraction/text.py` | Raw text from PDFs; OCR (RapidOCR) for scans and images |
| `extraction/parser.py` | Pulls date, clave de rastreo, bank labels, account and amount out of text |
| `banks.py` | Banxico's catalog, the bundled bank reference data, name matching, CLABE validation |
| `identify.py` | Decides the sending and receiving bank, and records how |
| `banxico.py` | HTTP client for Banxico's CEP service |
| `pipeline.py` | One receipt end to end, and batches of them concurrently; shared by CLI and GUI |
| `cli.py`, `gui/` | User interfaces |

### Banks

Banxico's catalog (`instituciones.do`) is the source of truth for which banks exist and
what they're called; it's downloaded for each payment date, so renames are handled
automatically (`BBVA BANCOMER` before 2022, `BBVA MEXICO` after). Banks are identified
by their 3-digit CLABE code, which survives renames and re-licensing
(`90638 NU MEXICO` → `40638 NUBANK`).

[`src/cepxico/data/banks.toml`](src/cepxico/data/banks.toml) adds what the catalog
lacks: legal names from Banxico's official participant list, brands and former names,
names that are ordinary words (never used when scanning a whole receipt), and clues
for recognising the sending bank. Its header documents every field and source.

**Receiving bank:** the CLABE's first 3 digits, else the "Banco destino/receptor" field.
**Sending bank:** the "Banco emisor/origen" field, else a clave de rastreo prefix, else
bank-specific wording, else the first bank named on the receipt. The receiving bank is
never chosen as sender. The GUI's details panel shows which clue was used.

To support a new bank's receipt wording, edit `banks.toml` and add a test; no code
changes needed. `tests/test_banks.py` checks the file against Banxico's catalog.

### Batches

Receipts are checked 4 at a time, since most of each check is spent waiting on
Banxico. Each worker has its own Banxico session: Banxico's download step returns the
CEP of the session's *last* lookup, so a shared session could save one receipt's CEP
under another's name. OCR runs one image at a time (it already uses every CPU core).

### OCR

[RapidOCR](https://github.com/RapidAI/RapidOCR) runs PaddleOCR's PP-OCRv6 models on ONNX
Runtime; the models ship inside the package, so it works offline. Text boxes are
regrouped into lines so a label and a value in separate columns ("Clave de rastreo"
… "MBAN01…") end up on one line, as in a PDF.

It replaced EasyOCR (v1), which needed PyTorch (about 2 GB). On synthetic receipts it
was about 2.7x faster per image, loaded in 2 s instead of 15 s, and misread fewer fields
(EasyOCR read `0` as `O` in claves de rastreo). To compare them on real receipts:

```powershell
pip install -e ".[easyocr]"
python scripts/compare_ocr.py receipt1.png scan.pdf
```

`CEPXICO_OCR=easyocr` makes the app itself use EasyOCR.

## Build the Windows app

```powershell
pip install -e ".[build]"
pyinstaller packaging/cepxico.spec --noconfirm
```

This makes `dist/cepxico/` (about 320 MB, mostly OpenCV and ONNX Runtime) with
`cepxico-gui.exe` (desktop app) and `cepxico.exe` (command line). Zip the folder to
share it; it runs on 64-bit Windows without Python installed.

## Develop

```powershell
pip install -e ".[dev]"
pytest
ruff check . ; ruff format .
```

Tests run offline. `tests/data/` holds snapshots of Banxico's public bank catalog
for 2019, 2024 and 2026, to test name changes over time.
Never commit real receipts or CEPs: they contain account numbers. `.gitignore`
excludes PDFs and images for this reason.

### Known gaps

- Sample receipts in the tests are synthetic. The sender label wordings
  ("Banco emisor", "Banco de origen", …) and the inherited clues in `banks.toml`
  (`BNET` prefix, "Comprobante de Operación") still need confirming on real receipts.
- Photos taken at an angle: on a receipt rotated by a few degrees, labels and values
  in far-apart columns no longer line up, and fields can be missed. Screenshots and
  scans are unaffected.
