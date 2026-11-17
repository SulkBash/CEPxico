# CEPxico

Checks that SPEI transfer receipts are real. It reads a receipt (PDF, screenshot or
pasted image), extracts the transfer data, and asks Banxico's
[CEP service](https://www.banxico.org.mx/cep/) for the official *Comprobante
Electrónico de Pago*. If Banxico returns a CEP, the transfer happened.

Each receipt ends up as one of:

| Result | Meaning |
|---|---|
| **Success** | CEP found, its data matches the receipt, and it's saved to `~/Downloads/CEPs/` (PDF, XML or ZIP: see [Settings](#settings)) |
| **Review** | A real payment, but not a clean confirmation: paid to an account that isn't yours, a CEP whose data doesn't match the receipt, or a payment Banxico has without a CEP (still settling, cancelled, returned). The message says which |
| **Not Found** | Banxico has no transfer with that data. Check the extracted fields; the receipt may be fake |
| **Failed** | Couldn't check: unreadable file, missing data, network error, Banxico closed or out of lookups… |

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
cepxico D:\Receipts                   # every PDF/PNG/JPG in a folder
cepxico *.pdf --jobs 2                # receipts checked at once (default 4, max 8)
python -m cepxico                     # same as `cepxico`
```

`cepxico-gui` opens the desktop app without a console window.

In the desktop app, **Process Files** checks every receipt not yet confirmed; receipts
whose CEP was already saved are left alone (remove and re-add one to check it again).
When a receipt fails or isn't found at Banxico, double-click it (or **Edit Fields**) to
correct or fill in any field from the receipt, for example an account the receipt only
shows as `***756`. Results checked with typed fields are marked `[edited]`. Tick
**Pago a banco** there for a payment made to the receiving bank itself rather than to
one of its customers; the account field then takes the account the money came from,
as Banxico asks.

### Settings

The **Settings** button (saved in `%APPDATA%\CEPxico\settings.json`, also used by the
command line):

- **Save each CEP as:** PDF (default), XML, or the PDF and XML in one ZIP. The XML
  is Banxico's digitally signed record of the transfer: it can be checked with
  Banxico's [CEP validator](https://www.banxico.org.mx/validador-cep-spei/) and
  imported by accounting software. If it can't be read, the PDF is saved instead. The
  ZIP is built from the two files already downloaded, so it costs no extra lookup at
  Banxico. `cepxico --save pdf|xml|zip` picks for one run.
- **Only accept payments to these accounts.** Off by default. A real transfer to
  someone else's account would otherwise show as Success; with this on, receipts paid
  to any other account are marked Review without asking Banxico. List the debit card
  or phone number too if customers pay to those.

### What every check includes

- The CEP's XML is always read and compared with the receipt (clave de rastreo,
  amount, account), and the details panel shows who sent and received the money
  according to Banxico.
- Banxico only answers from 09:30 to 23:00, Mexico City time. Outside those hours a
  receipt isn't reported as Not Found, since Banxico's answer says nothing about it.
- When Banxico says there have been too many lookups, the rest of the batch stops
  asking it and fails with "try again later".

## How it works

```
receipt ─► extraction ─► PaymentData ─► identify ─► sender/receiver ─► banxico ─► CEP PDF
          (text + regex)                (Banxico catalog for the date      (HTTP, no browser)
                                         + data/banks.toml)
```

| Module | Responsibility |
|---|---|
| `extraction/text.py` | Raw text from PDFs (PyMuPDF); OCR (RapidOCR) for scans and images |
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

Receipts are checked 4 at a time (`--jobs`, up to 8), since most of each check is
spent waiting on Banxico. Every lookup starts a new Banxico session: Banxico's download
step returns the CEP of the session's *last* lookup, so a reused session could save one
receipt's CEP under another's name. OCR runs one image at a time (it already uses every
CPU core).

Banxico also has a [batch service](https://www.banxico.org.mx/cep-scl/) (a text file of
up to 500 transfers, results by email). The app doesn't use it: it needs the data
typed out already, and answers hours later instead of while you watch.

### OCR

[RapidOCR](https://github.com/RapidAI/RapidOCR) runs PaddleOCR's PP-OCRv6 models on ONNX
Runtime; the models ship inside the package, so it works offline. Text boxes are
regrouped into lines so a label and a value in separate columns ("Clave de rastreo"
… "MBAN01…") end up on one line. PDF text goes through the same grouping, so PDFs and
images reach the parser in the same layout.

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
