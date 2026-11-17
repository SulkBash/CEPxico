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
receipt ─► extraction ─► PaymentData ─► identify ─► sender/receiver ─► banxico ─► CEP PDF
          (text + regex)                (Banxico catalog for the date      (HTTP, no browser)
                                         + data/banks.toml)
```

| Module | Responsibility |
|---|---|
| `extraction/text.py` | Raw text from PDFs; OCR fallback for scans and images |
| `extraction/parser.py` | Pulls date, clave de rastreo, bank labels, account and amount out of text |
| `banks.py` | Banxico's catalog, the bundled bank reference data, name matching, CLABE validation |
| `identify.py` | Decides the sending and receiving bank, and records how |
| `banxico.py` | HTTP client for Banxico's CEP service |
| `pipeline.py` | One receipt end to end; shared by CLI and GUI |
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
