# CEPxico guide

Everything the [README](../README.md) leaves out: what each result means, the desktop app
and the command line in detail, settings, history, and dollar transfers.

- [Results](#results)
- [Desktop app](#desktop-app)
- [Command line](#command-line)
- [Settings](#settings)
- [What every check includes](#what-every-check-includes)
- [Receipts used twice](#receipts-used-twice)
- [History](#history)
- [Dollar transfers (SPID)](#dollar-transfers-spid)
- [Known gaps](#known-gaps)
- [Reporting a bug](#reporting-a-bug)

## Results

| Result | Meaning |
|---|---|
| **Confirmed** | CEP found, its data matches the receipt, and it's saved to `~/Downloads/CEPs/` (PDF, XML or ZIP: see [Settings](#settings)) |
| **Review** | A real payment, but not a clean confirmation: paid to an account that isn't yours, a CEP whose data doesn't match the receipt, a payment Banxico has without a CEP (still settling, cancelled, returned), or a transfer already confirmed for another receipt ([receipts used twice](#receipts-used-twice)). The message says which |
| **Not Found** | Banxico has no transfer with that data. Check the extracted fields; the receipt may be fake |
| **Error** | Couldn't check: unreadable file, missing data, network error, Banxico closed or out of lookups, a [dollar transfer (SPID)](#dollar-transfers-spid) whose security code nobody typed… |

## Desktop app

Drop receipts on the window, paste a screenshot (Ctrl+V / Cmd+V) or copied files, or use
**Add Files**. **Check** (F5) checks every receipt not yet confirmed; receipts whose CEP
was already saved are left alone (remove and re-add one to check it again).

When a receipt fails or isn't found at Banxico, double-click it (or **Edit Fields**) to
correct or fill in any field from the receipt, for example an account the receipt only
shows as `***756`. Results checked with typed fields are marked `[edited]`. Tick
**Paid to the bank itself (pago a banco)** there for a payment made to the receiving bank
itself rather than to one of its customers; the account field then takes the account the
money came from, as Banxico asks.

Every action is also in the menu bar, and right-clicking a receipt opens it or its CEP.
In the details pane, Ctrl+C (or right-click) copies the selected value, such as the clave
de rastreo. The app follows the system's light or dark theme.

| Shortcut | Action |
|---|---|
| Ctrl+O | Add files |
| Ctrl+V | Paste a screenshot or copied files |
| F5 | Check |
| Esc | Cancel |
| F2 | Edit fields |
| Del | Remove |
| Ctrl+A | Select all |
| Ctrl+H | History |
| Ctrl+, | Settings |

Cmd instead of Ctrl on a Mac.

## Command line

```bash
cepxico receipt1.pdf receipt2.png     # exit code 0 only if every CEP was found
cepxico D:\Receipts                   # every PDF/PNG/JPG/WEBP in a folder
cepxico *.pdf --out D:\CEPs -v        # custom output folder, debug logging
cepxico *.pdf --jobs 2                # receipts checked at once (default 4, max 8)
cepxico *.pdf --csv results.csv       # also write this run's results to a CSV file
cepxico *.pdf --save zip              # CEP as pdf, xml or zip for this run
cepxico *.pdf --lang en               # messages in English for this run
cepxico *.pdf --no-history            # don't record this run or check for reused receipts
cepxico --export-history all.csv      # every check ever made, as CSV
cepxico                               # with no files: opens the desktop app
```

`cepxico-gui` opens the desktop app without a console window. `python -m cepxico` is the
same as `cepxico`.

## Settings

**Settings** are saved in `settings.json` in the app's data folder and also used by the
command line:

| System | Data folder (settings, history, log) |
|---|---|
| Windows | `%APPDATA%\CEPxico` |
| macOS | `~/Library/Application Support/CEPxico` |
| Linux | `~/.config/cepxico` (or `$XDG_CONFIG_HOME/cepxico`) |

`CEPXICO_HOME` overrides the folder, for example for a portable install. Settings shows
the folder, with a button to open it.

- **CEP files:** PDF (default), XML, or the PDF and XML in one ZIP. The XML is Banxico's
  digitally signed record of the transfer: it can be checked with Banxico's
  [CEP validator](https://www.banxico.org.mx/validador-cep-spei/) and imported by
  accounting software. If it can't be read, the PDF is saved instead. The ZIP is built
  from the two files already downloaded, so it costs no extra lookup at Banxico.
- **Only accept payments to these accounts.** Off by default. A real transfer to someone
  else's account would otherwise show as Confirmed; with this on, receipts paid to any
  other account are marked Review without asking Banxico. List the debit card or phone
  number too if customers pay to those.
- **Language:** Español, English, or the system's language (the default; Spanish when the
  system's language is neither). Tools → Language switches directly. Results already
  shown keep the language they were checked in.

## What every check includes

- The CEP's XML is always read and compared with the receipt (clave de rastreo, amount,
  account), and the details panel shows who sent and received the money according to
  Banxico.
- Banxico only answers from 09:30 to 23:00, Mexico City time. Outside those hours a
  receipt isn't reported as Not Found, since Banxico's answer says nothing about it.
- When Banxico says there have been too many lookups, the rest of the batch stops asking
  it and fails with "try again later".
- The check is recorded in the [history](#history), and a transfer already confirmed for
  another receipt is caught.

## Receipts used twice

A real receipt can be shown more than once: two customers forwarding the same
screenshot, or one customer sending last week's receipt again. Banxico confirms the
transfer every time, because it did happen. CEPxico remembers which receipt file each
confirmed transfer was first confirmed for. The same transfer (clave de rastreo, date and
sending bank) on any other file is marked **Review**: "Already used: confirmed on
10/11/2026 for juan.png". When the transfer was already confirmed in an earlier check,
Banxico isn't asked again.

"The same receipt" means the same file: same path and same content. Checking a receipt
again from where it is stays Confirmed. A copy under another name or in another folder
counts as another receipt, because that's exactly what a forwarded receipt looks like.
Two receipts of one transfer checked in the same batch can't both pass.

`cepxico --no-history` turns this off for one run (and doesn't record it).

## History

Every check is kept in `history.sqlite3` in the data folder: when, which file, the result
and its message, the transfer's data, sender and beneficiary names from the CEP, and
where the CEP was saved. The **History** button lists it, newest first, with a search box
(file, clave de rastreo, amount, name, bank) and **Export CSV...** for what's shown.
**Open CEP** (or double-click) opens a row's saved CEP. **Forget** deletes a check, for
example when a receipt was wrongly taken as [used twice](#receipts-used-twice) (a moved
folder): once the first check is forgotten, its transfer no longer counts as used.

The CSV is UTF-8 with a byte order mark, so Excel shows accents correctly, and accounts
and claves are written as text (`="012180001234567893"`), so Excel keeps every digit. The
history holds account numbers and names, like the CEPs themselves; it never leaves the
computer.

## Dollar transfers (SPID)

SPID transfers (US dollars between Mexican banks) have their own Banxico service,
[CEP-SPID](https://www.banxico.org.mx/cep-spid/). Unlike the SPEI one, it always asks for
the characters in a security image, so a person types them for every dollar receipt.
CEPxico never reads the image itself.

- **Desktop app:** when a dollar receipt's turn comes, a window shows Banxico's image
  (enlarged), the receipt's amount and clave de rastreo. Type the characters and press
  **Check**; the app does the rest as for any receipt (download the CEP, compare it, save
  it). **Another image** asks Banxico for a new one; **Skip this receipt** leaves it
  Failed ("no security code was typed"). Cancelling the batch closes the window.
- **Command line:** the image opens in the system's image viewer and the code is typed in
  the terminal (`?` for another image, Enter to skip). Only when a person is at the
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
account too. CEPs are saved as `CEP_SPID_<date>_<clave>`.

## Known gaps

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

## Reporting a bug

Attach `cepxico.log` from the data folder (Settings → Data folder → Open). Account
numbers, cards, phones and claves de rastreo are cut to their last 4 characters in it,
but file names and amounts aren't, so look it over before posting it publicly. Never
attach real receipts or CEPs.
