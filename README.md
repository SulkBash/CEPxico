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

Requires Python 3.10+ on Windows.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .            # core
pip install -e ".[ocr]"     # + OCR for scans and screenshots (large: installs PyTorch)
```

## Use

```powershell
cepxico                               # desktop app (drag & drop, Ctrl+V to paste screenshots)
cepxico receipt1.pdf receipt2.png     # command line; exit code 0 only if every CEP was found
cepxico *.pdf --out D:\CEPs -v        # custom output folder, debug logging
python -m cepxico                     # same as `cepxico`
```

`cepxico-gui` opens the desktop app without a console window.

## How it works

```
receipt ──► extraction.text ──► extraction.parser ──► PaymentData ──► banxico ──► CEP PDF
           (pdfplumber / OCR)   (regex per field)                   (HTTP, no browser)
```

| Module | Responsibility |
|---|---|
| `extraction/text.py` | Raw text from PDFs; OCR fallback for scans and images |
| `extraction/parser.py` | Pulls date, clave de rastreo, banks, account and amount out of text |
| `banks.py` | CLABE validation; matching receipt bank names to Banxico's catalog |
| `banxico.py` | HTTP client for Banxico's CEP service |
| `pipeline.py` | One receipt end to end; shared by CLI and GUI |
| `cli.py`, `gui/` | User interfaces |

The receiving bank is taken from the CLABE's first 3 digits when the account is a
valid 18-digit CLABE. Bank names are resolved against Banxico's live catalog for the
payment date.

## Develop

```powershell
pip install -e ".[dev]"
pytest
ruff check . ; ruff format .
```

Tests run offline. `tests/data/` holds a snapshot of Banxico's public bank catalog.
Never commit real receipts or CEPs: they contain account numbers. `.gitignore`
excludes PDFs and images for this reason.

### Known issues

- The sending bank is the first bank name found anywhere on the receipt, so it can
  pick up the receiving bank instead (see the `xfail` test in `tests/test_parser.py`).
