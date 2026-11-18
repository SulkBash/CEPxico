# CEPxico

Checks that SPEI transfer receipts are real. It reads a receipt (PDF, screenshot,
phone photo or pasted image), extracts the transfer data, and asks Banxico's
[CEP service](https://www.banxico.org.mx/cep/) for the official *Comprobante
Electrónico de Pago*. If Banxico returns a CEP, the transfer happened.

Runs on Windows, macOS and Linux, in Spanish or English.

Each receipt ends up as one of:

| Result | Meaning |
|---|---|
| **Confirmed** | CEP found, its data matches the receipt, and it's saved to `~/Downloads/CEPs/` (PDF, XML or ZIP: see [Settings](#settings)) |
| **Review** | A real payment, but not a clean confirmation: paid to an account that isn't yours, a CEP whose data doesn't match the receipt, a payment Banxico has without a CEP (still settling, cancelled, returned), or a transfer already confirmed for another receipt ([receipts used twice](#receipts-used-twice)). The message says which |
| **Not Found** | Banxico has no transfer with that data. Check the extracted fields; the receipt may be fake |
| **Error** | Couldn't check: unreadable file, missing data, network error, Banxico closed or out of lookups, a [dollar transfer (SPID)](#dollar-transfers-spid) whose security code nobody typed… |

## Install

Requires Python 3.11+.

**Windows**

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

**macOS and Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

The desktop app is built with Qt (PySide6), which pip installs. On Linux it also needs
`libxcb-cursor0`, which some distributions leave out: `sudo apt install libxcb-cursor0`.
On Windows, a venv made from Anaconda's Python can't load PySide6 6.10 or newer ("DLL
load failed": Anaconda's older Visual C++ runtime loads first); there,
`pip install "PySide6-Essentials<6.10"`.

OCR for screenshots and scanned PDFs is included (RapidOCR, about 50 MB). No Python
needed for end users: see [Build the app](#build-the-app).

## Use

```bash
cepxico                               # desktop app (drag & drop, Ctrl+V / Cmd+V to paste screenshots)
cepxico receipt1.pdf receipt2.png     # command line; exit code 0 only if every CEP was found
cepxico *.pdf --out D:\CEPs -v        # custom output folder, debug logging
cepxico D:\Receipts                   # every PDF/PNG/JPG/WEBP in a folder
cepxico *.pdf --jobs 2                # receipts checked at once (default 4, max 8)
cepxico *.pdf --csv results.csv       # also write this run's results to a CSV file
cepxico --export-history all.csv      # every check ever made, as CSV
cepxico *.pdf --lang en               # messages in English for this run
python -m cepxico                     # same as `cepxico`
```

`cepxico-gui` opens the desktop app without a console window.

In the desktop app, **Check** (F5) checks every receipt not yet confirmed; receipts
whose CEP was already saved are left alone (remove and re-add one to check it again).
When a receipt fails or isn't found at Banxico, double-click it (or **Edit Fields**) to
correct or fill in any field from the receipt, for example an account the receipt only
shows as `***756`. Results checked with typed fields are marked `[edited]`. Tick
**Paid to the bank itself (pago a banco)** there for a payment made to the receiving bank itself rather than to
one of its customers; the account field then takes the account the money came from,
as Banxico asks.

Files copied in the file manager can be pasted too, like dropped files.

Every action is also in the menu bar, and right-clicking a receipt opens it or its CEP.
Shortcuts: Ctrl+O add files, F5 process, Esc cancel, F2 edit fields, Del remove,
Ctrl+A select all, Ctrl+H history, Ctrl+, settings (Cmd instead of Ctrl on a Mac).
In the details pane, Ctrl+C (or right-click) copies the selected value, such as the
clave de rastreo. The app follows the system's light or dark theme.

### Settings

**Settings**, saved in `settings.json` in the app's data folder and also
used by the command line:

| System | Data folder (settings, history, log) |
|---|---|
| Windows | `%APPDATA%\CEPxico` |
| macOS | `~/Library/Application Support/CEPxico` |
| Linux | `~/.config/cepxico` (or `$XDG_CONFIG_HOME/cepxico`) |

`CEPXICO_HOME` overrides the folder, for example for a portable install. Settings shows
the folder, with a button to open it.

- **CEP files:** PDF (default), XML, or the PDF and XML in one ZIP. The XML
  is Banxico's digitally signed record of the transfer: it can be checked with
  Banxico's [CEP validator](https://www.banxico.org.mx/validador-cep-spei/) and
  imported by accounting software. If it can't be read, the PDF is saved instead. The
  ZIP is built from the two files already downloaded, so it costs no extra lookup at
  Banxico. `cepxico --save pdf|xml|zip` picks for one run.
- **Only accept payments to these accounts.** Off by default. A real transfer to
  someone else's account would otherwise show as Confirmed; with this on, receipts paid
  to any other account are marked Review without asking Banxico. List the debit card
  or phone number too if customers pay to those.
- **Language:** Español, English, or the system's language (the default; Spanish when
  the system's language is neither). Tools → Language switches directly. Results
  already shown keep the language they were checked in.

### What every check includes

- The CEP's XML is always read and compared with the receipt (clave de rastreo,
  amount, account), and the details panel shows who sent and received the money
  according to Banxico.
- Banxico only answers from 09:30 to 23:00, Mexico City time. Outside those hours a
  receipt isn't reported as Not Found, since Banxico's answer says nothing about it.
- When Banxico says there have been too many lookups, the rest of the batch stops
  asking it and fails with "try again later".
- The check is recorded in the [history](#history), and a transfer already confirmed
  for another receipt is caught.

### Receipts used twice

A real receipt can be shown more than once: two customers forwarding the same
screenshot, or one customer sending last week's receipt again. Banxico confirms the
transfer every time, because it did happen. CEPxico remembers which receipt file each
confirmed transfer was first confirmed for. The same transfer (clave de rastreo, date
and sending bank) on any other file is marked **Review**: "Already used:
confirmed on 10/11/2026 for juan.png". When the transfer was
already confirmed in an earlier check, Banxico isn't asked again.

"The same receipt" means the same file: same path and same content. Checking a
receipt again from where it is stays Confirmed. A copy under another name or in another
folder counts as another receipt, because that's exactly what a forwarded receipt
looks like. Two receipts of one transfer checked in the same batch can't both pass.

`cepxico --no-history` turns this off for one run (and doesn't record it).

### History

Every check is kept in `history.sqlite3` in the data folder: when, which file, the
result and its message, the transfer's data, sender and beneficiary names from the CEP,
and where the CEP was saved. The **History** button lists it, newest first, with a
search box (file, clave de rastreo, amount, name, bank) and **Export CSV...** for what's
shown. **Open CEP** (or double-click) opens a row's saved CEP. **Forget** deletes a
check, for example when a receipt was wrongly taken as [used twice](#receipts-used-twice)
(a moved folder): once the first check is forgotten, its transfer no longer counts as
used.

The CSV is UTF-8 with a byte order mark, so Excel shows accents correctly, and accounts
and claves are written as text (`="012180001234567893"`), so Excel keeps every digit.
The history holds account numbers and names, like the CEPs themselves; it never leaves
the computer.

### Dollar transfers (SPID)

SPID transfers (US dollars between Mexican banks) have their own Banxico service,
[CEP-SPID](https://www.banxico.org.mx/cep-spid/). Unlike the SPEI one, it always asks
for the characters in a security image, so a person types them for every dollar
receipt. CEPxico never reads the image itself.

- **Desktop app:** when a dollar receipt's turn comes, a window shows Banxico's image
  (enlarged), the receipt's amount and clave de rastreo. Type the characters and press
  **Check**; the app does the rest as for any receipt (download the CEP, compare it,
  save it). **Another image** asks Banxico for a new one; **Skip this receipt** leaves it
  Failed ("no security code was typed"). Cancelling the batch closes the window.
- **Command line:** the image opens in the system's image viewer and the code is typed
  in the terminal (`?` for another image, Enter to skip). Only when a person is at the
  terminal: in a script or scheduled task, dollar receipts are reported Failed with a
  link instead of waiting for an answer.
- If Banxico doesn't accept a code, a new image is shown, up to 3 times per receipt.
- One image at a time, even with several receipts checked at once; the image is fetched
  right when it's shown, and serves only that one lookup.

A receipt counts as SPID when it shows the dollar currency (USD, US$, DLS, dólares), or
names SPID without naming SPEI. Some banks print "Comprobante Electrónico de Pagos SPEI /
SPID" on every receipt, so the word alone isn't enough. SPID receipts are never sent to
the SPEI service, which would answer "not found" and make a real dollar transfer look
fake. If a receipt is taken for the wrong one, tick or untick **Dollar transfer (SPID)**
in Edit Fields. With **Only accept payments to these accounts** on, list your dollar
account too.

The SPID requests follow Banxico's own page (`js/cepspid-min.js`): dates as `yyyymmdd`,
`R` for clave de rastreo, `pagoABanco=true/false`, and a bank list of `claveSpid` /
`nombreCorto` objects (a snapshot is in `tests/data/`). CEPs are saved as
`CEP_SPID_<date>_<clave>`.

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

Phone photos are handled in two steps:

- **Sideways:** phones save many photos turned and record the turn in the EXIF
  orientation tag; the image is turned upright before OCR.
- **At an angle:** on a receipt tilted a few degrees, a value in a far column sits a
  line above or below its label, and fields were missed. The tilt is measured from the
  slope of the text boxes and the boxes are straightened before grouping, up to 45°.
  On synthetic receipts tilted -7°, 5° and 10°, the clave de rastreo and account were
  lost without this and are read correctly with it (`tests/test_text.py`).

It replaced EasyOCR (v1), which needed PyTorch (about 2 GB). On synthetic receipts it
was about 2.7x faster per image, loaded in 2 s instead of 15 s, and misread fewer fields
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
`dist/CEPxico.app`. Zip the folder (or the `.app`) to share it; it runs without Python
installed, on the same kind of system it was built on (64-bit Windows, macOS on the
same chip, Linux with a glibc at least as new).

The app isn't code-signed: Windows SmartScreen warns on first run ("More info" → "Run
anyway"), and macOS Gatekeeper needs right-click → Open the first time.

## Develop

```bash
pip install -e ".[dev]"
pytest
ruff check . ; ruff format .
```

Tests run offline. `tests/data/` holds snapshots of Banxico's public bank catalog
for 2019, 2024 and 2026, to test name changes over time. The desktop app's tests use
Qt's offscreen platform, so no window opens and no display is needed. GitHub Actions
runs them on Windows, macOS and Linux (`.github/workflows/tests.yml`).
Never commit real receipts or CEPs: they contain account numbers. `.gitignore`
excludes PDFs and images for this reason. Values copied into tests (claves, accounts,
amounts) must be made up too.

### Bug reports

Attach `cepxico.log` from the data folder (Settings → Data folder → Open). Account
numbers, cards, phones and claves de rastreo are cut to their last 4 characters in it,
but file names and amounts aren't, so look it over before posting it publicly.

Every message users read goes through `tr("English text")`; add its Spanish to
`src/cepxico/translations.py`. `tests/test_i18n.py` fails on a message without a
translation, a translation whose `{placeholders}` differ, or a leftover translation.

### Known gaps

- Dollar transfers (SPID) haven't been checked against Banxico with a real receipt yet.
  The requests copy Banxico's page and the bank list was read from it, but its answers
  (CEP found, not found, wrong code) and its CEP XML are assumed to match the SPEI
  service's. If its XML differs, the CEP is still saved but not compared with the
  receipt. Banxico's 09:30–23:00 hours are also assumed for SPID.
- macOS and Linux are covered by the automated tests, but the desktop app hasn't been
  tried by hand there yet: look over the window, fonts, drag & drop and paste on each.
- A copy of a receipt under another name counts as another receipt (by design, see
  [receipts used twice](#receipts-used-twice)). Moving a folder of already-checked
  receipts and checking them again therefore marks them Review; **Forget** in History
  clears the old checks.

## License

[GNU Affero General Public License v3.0 or later](LICENSE) (AGPL-3.0-or-later).

Anyone may use, study, change and share CEPxico, including commercially. Whoever shares
a changed version, or offers one to others over a network (a website, an API, a bot),
must make its source available under the same license. Using the app to check your own
receipts carries no obligation. PyMuPDF, which reads the PDFs, is itself AGPL-3.0, so
the built app is AGPL as a whole either way.
