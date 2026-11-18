"""Spanish for every message passed to i18n.tr(), keyed by its English text.

Mexican Spanish, addressing the user as "tú" like most Mexican banking apps. Banxico's
own terms (CEP, clave de rastreo, pago a banco, Liquidado...) are kept as Banxico
writes them. tests/test_i18n.py checks every tr() message is here with the same
{placeholders}.
"""

ES: dict[str, str] = {
    # --- Banxico's answers -----------------------------------------------------------
    "Banxico's lookup limit reached; try again later": (
        "Se alcanzó el límite de consultas de Banxico; intenta más tarde"
    ),
    "Settled (Liquidado), but no CEP yet; check again later": (
        "Liquidado, pero aún sin CEP; vuelve a revisar más tarde"
    ),
    "Not settled yet (En proceso); check again later": (
        "Aún no se liquida (En proceso); vuelve a revisar más tarde"
    ),
    "Cancelled before settling (Cancelado); no money arrived": (
        "Cancelado antes de liquidarse; el dinero no llegó"
    ),
    "Returned by the receiving bank (Retornado); the money didn't stay": (
        "Devuelto por el banco receptor (Retornado); el dinero no se quedó"
    ),
    "Returned by the receiving bank (Devuelto); the money didn't stay": (
        "Devuelto por el banco receptor (Devuelto); el dinero no se quedó"
    ),
    "Found ({status}), but no CEP": ("Encontrado ({status}), pero sin CEP"),
    "CEP downloaded": "CEP descargado",
    "Banxico returned no bank list for {date}": "Banxico no devolvió la lista de bancos del {date}",
    "Invalid date '{date}' (expected dd-mm-yyyy)": "Fecha no válida '{date}' (se espera dd-mm-aaaa)",
    "Invalid clave de rastreo '{clave}'": "Clave de rastreo no válida '{clave}'",
    "Invalid account '{account}'": "Cuenta no válida '{account}'",
    "Invalid amount '{amount}'": "Monto no válido '{amount}'",
    "Both banks are {bank}; CEPs only exist between banks": (
        "Ambos bancos son {bank}; el CEP solo existe entre bancos"
    ),
    "Banxico server error {code}: {message}": "Error del servidor de Banxico {code}: {message}",
    "Banxico rejected the data": ("Banxico rechazó los datos"),
    "Banxico wants a security code (too many lookups); try again later": (
        "Banxico pide un código de seguridad (demasiadas consultas); intenta más tarde"
    ),
    "unknown": "desconocido",
    "Couldn't load Banxico's bank list: {error}": "No se pudo cargar la lista de bancos de Banxico: {error}",
    "Couldn't reach Banxico: {error}": "No se pudo conectar con Banxico: {error}",
    "Banxico request failed: {error}": "Falló la consulta a Banxico: {error}",
    "CEP download failed: {error}": "Falló la descarga del CEP: {error}",
    "no CEP with this data": "no hay CEP con estos datos",
    # --- Command line ----------------------------------------------------------------
    "Files: {count}": "Archivos: {count}",
    "Confirmed: {count}": "Confirmados: {count}",
    "Check SPEI receipts with Banxico and download their CEPs. Without files, opens the desktop app.": (
        "Verifica comprobantes SPEI con Banxico y descarga sus CEP. Sin archivos, abre la app de escritorio."
    ),
    "Uses the desktop app's settings ({settings}) and history ({history}).": (
        "Usa la configuración ({settings}) y el historial ({history}) de la app de escritorio."
    ),
    "receipt PDF/image files, wildcards (*.pdf) or folders": (
        "comprobantes en PDF o imagen, comodines (*.pdf) o carpetas"
    ),
    "folder for downloaded CEPs (default: {folder})": (
        "carpeta para los CEP descargados (por omisión: {folder})"
    ),
    "receipts to check at once, 1-{max} (default: {default})": (
        "comprobantes a verificar a la vez, 1-{max} (por omisión: {default})"
    ),
    "CEP files to save (default: as in Settings)": (
        "archivos del CEP que se guardan (predeterminado: como en Configuración)"
    ),
    "also save this run's results as CSV": ("guarda también los resultados de esta ejecución en CSV"),
    "save the whole history as CSV and exit": ("guarda todo el historial en CSV y termina"),
    "don't use or update the history (no used-twice check)": (
        "no usa ni actualiza el historial (sin revisar comprobantes repetidos)"
    ),
    "message language (default: as in Settings)": (
        "idioma de los mensajes (predeterminado: como en Configuración)"
    ),
    "show debug output": "mostrar mensajes de depuración",
    "must be a whole number from 1 to {max}": "debe ser un número entero del 1 al {max}",
    "Review: {count}": ("Revisar: {count}"),
    "Not found (receipt may be fake): {count}": ("No encontrados (el comprobante puede ser falso): {count}"),
    "Errors or not checked: {count}": "Errores o no verificados: {count}",
    "Wrote {count} checks to {file}": "Se escribieron {count} verificaciones en {file}",
    "Results written to {file}": "Resultados escritos en {file}",
    "Summary": "Resumen",
    # --- Reading receipts ------------------------------------------------------------
    "No text extracted": "No se pudo extraer texto",
    "Missing {field}": "Falta {field}",
    "'{raw}' isn't a date (day/month/year)": ("'{raw}' no es una fecha (día/mes/año)"),
    "must be 1 to {max} letters and digits": "debe tener de 1 a {max} letras y dígitos",
    "digits only": "solo dígitos",
    "has {count} digits; needs 18 (CLABE), 16 (card) or 10 (phone)": (
        "tiene {count} dígitos; deben ser 18 (CLABE), 16 (tarjeta) o 10 (teléfono)"
    ),
    "isn't a valid CLABE; check for a typo": ("no es una CLABE válida; revisa que esté bien escrita"),
    "'{raw}' isn't a valid amount (e.g. 1,500.00)": "'{raw}' no es un monto válido (p. ej. 1,500.00)",
    "Unknown OCR engine '{name}' (choose from {choices})": (
        "Motor de OCR desconocido '{name}' (elige entre {choices})"
    ),
    "OCR needed but no OCR engine is installed (pip install rapidocr)": (
        "Se necesita OCR pero no hay ningún motor de OCR instalado (pip install rapidocr)"
    ),
    "OCR engine '{name}' is not installed": "El motor de OCR '{name}' no está instalado",
    "Unsupported file type '{suffix}'": "Tipo de archivo no admitido '{suffix}'",
    "Failed to read file: {error}": "No se pudo leer el archivo: {error}",
    "OCR engine '{name}' failed to load: {error}": "No se pudo cargar el motor de OCR '{name}': {error}",
    # --- Statuses --------------------------------------------------------------------
    "Pending": "Pendiente",
    "Checking": "Verificando",
    "Confirmed": "Confirmado",
    "Not Found": "No encontrado",
    "Review": "Revisar",
    "Error": "Error",
    "Skipped": "Omitido",
    # --- Main window -----------------------------------------------------------------
    "All Files": "Todos los archivos",
    "Receipt": "Comprobante",
    "Copy": "Copiar",
    "Banxico's signed record of the transfer; accounting software can import it.": (
        "El registro firmado de Banxico de la transferencia; los programas de contabilidad pueden importarlo."
    ),
    "Receipts paid to any other account are marked Review.": (
        "Los comprobantes pagados a otra cuenta quedan en Revisar."
    ),
    "One per line: CLABE, card or phone": "Una por línea: CLABE, tarjeta o teléfono",
    "Settings, history and cepxico.log": "Configuración, historial y cepxico.log",
    "Search file, clave, amount, name or bank": "Buscar por archivo, clave, monto, nombre o banco",
    "Stopped": "Detenido",
    "Code": "Código",
    "Banks": "Bancos",
    # Menu bar
    "Receipts": "Comprobantes",
    "Tools": "Herramientas",
    "Help": "Ayuda",
    "Paste": "Pegar",
    "Select All": "Seleccionar todo",
    "Exit": "Salir",
    "About CEPxico": "Acerca de CEPxico",
    "Checks SPEI receipts with Banxico and saves their CEPs.": (
        "Verifica comprobantes SPEI con Banxico y guarda sus CEP."
    ),
    "Check": "Verificar",
    "Stop": "Detener",
    "No receipt selected": "Ningún comprobante seleccionado",
    "Screenshot added": "Captura agregada",
    "Open CEP Folder": "Abrir carpeta de CEP",
    "Settings saved": "Configuración guardada",
    "Ordering account": "Cuenta ordenante",
    "Account": "Cuenta",
    "Checking…": "Verificando…",
    "{done} of {total}: {name}": "{done} de {total}: {name}",
    "Results": "Resultados",
    "Receipts: {count}": "Comprobantes: {count}",
    "Checked: {count}": "Verificados: {count}",
    "Ready": "Listo",
    "File": "Archivo",
    "Status": "Estado",
    "Result": "Resultado",
    "Wait for the check to finish.": "Espera a que termine la verificación.",
    "Already in the list: {count}": "Ya estaban en la lista: {count}",
    "Nothing to paste": "No hay nada que pegar",
    "Couldn't save the settings: {error}": "No se pudo guardar la configuración: {error}",
    "Settings": "Configuración",
    "Edit Fields": "Editar campos",
    "Select a receipt first.": "Primero selecciona un comprobante.",
    "Only receipts marked Error, Not Found or Review can be edited.": (
        "Solo se pueden editar comprobantes con Error, No encontrado o Revisar."
    ),
    "Edited": "Editado",
    "Paid to the bank itself (pago a banco)": "Pagado al propio banco (pago a banco)",
    "The list is empty.": "La lista está vacía.",
    "All receipts are already confirmed. To check one again, remove it and add it back.": (
        "Todos los comprobantes ya están confirmados. "
        "Para verificar uno de nuevo, quítalo y vuelve a agregarlo."
    ),
    "Waiting": "En espera",
    "Stopping after the receipts in progress…": ("Deteniendo al terminar los comprobantes en curso…"),
    "Done": "Terminado",
    "Already confirmed: {count}": "Ya confirmados: {count}",
    "Not checked: {count}": "No verificados: {count}",
    "CEPs in {folder}": "CEP en {folder}",
    "Review ({count}): the payment exists, but something doesn't match:": (
        "Revisar ({count}): el pago existe, pero algo no coincide:"
    ),
    "Not found ({count}): check the data; the receipt may be fake:": (
        "No encontrados ({count}): revisa los datos; el comprobante puede ser falso:"
    ),
    "Errors ({count}):": "Errores ({count}):",
    "Add Files": "Agregar archivos",
    "Remove": "Quitar",
    "Clear List": "Vaciar lista",
    "History": "Historial",
    "{path} isn't a PDF or an image.": "{path} no es un PDF ni una imagen.",
    "Couldn't open {path}: {error}": "No se pudo abrir {path}: {error}",
    "Path": "Ruta",
    "Date": "Fecha",
    "Clave de rastreo": "Clave de rastreo",
    "Amount": "Monto",
    "Sending bank": "Banco emisor",
    "Receiving bank": "Banco receptor",
    "edited": "editado",
    "Not checked": "No verificado",
    "Drop receipts here or paste a screenshot ({shortcut})": (
        "Suelta aquí los comprobantes o pega una captura ({shortcut})"
    ),
    "Open Receipt": "Abrir comprobante",
    "Status at Banxico": "Estado en Banxico",
    "Sender": "Ordenante",
    "Beneficiary": "Beneficiario",
    "Concept": "Concepto",
    "Edited fields": "Campos editados",
    # --- Edit Fields -----------------------------------------------------------------
    "day/month/year": "día/mes/año",
    "e.g. BANORTE": "p. ej. BANORTE",
    "optional with a CLABE": "opcional si hay CLABE",
    "CLABE, debit card or phone": "CLABE, tarjeta de débito o celular",
    "Beneficiary account": "Cuenta beneficiaria",
    "the bank that was paid": "el banco al que se pagó",
    "account the money came from": ("cuenta de donde salió el dinero"),
    "Save and Check": "Guardar y verificar",
    "Save": "Guardar",
    "Copy the missing or wrong values from the receipt.": (
        "Copia del comprobante los datos que falten o estén mal."
    ),
    # --- History ---------------------------------------------------------------------
    "Export CSV...": "Exportar CSV...",
    "Checked": "Verificado",
    "Details": "Detalles",
    "{shown} of {total}": "{shown} de {total}",
    "Open CEP": "Abrir CEP",
    "Select a row first.": "Primero selecciona una fila.",
    "Couldn't read the history: {error}": "No se pudo leer el historial: {error}",
    "This check's CEP isn't on this computer.": ("El CEP de esta verificación no está en esta computadora."),
    "Couldn't write the file: {error}": "No se pudo escribir el archivo: {error}",
    "Payment date": "Fecha de pago",
    "CEP file": "Archivo del CEP",
    "File path": "Ruta del archivo",
    "yes": "sí",
    # --- Settings --------------------------------------------------------------------
    "PDF and XML (ZIP)": "PDF y XML (ZIP)",
    "System": "Del sistema",
    "Add an account or uncheck the box.": ("Agrega una cuenta o desmarca la casilla."),
    "CEP files": "Archivos del CEP",
    "Your accounts": "Tus cuentas",
    "Only accept payments to these accounts": "Solo aceptar pagos a estas cuentas",
    "Language": "Idioma",
    "Fix these accounts:": "Corrige estas cuentas:",
    # --- How banks were identified ---------------------------------------------------
    "CLABE prefix": "prefijo de la CLABE",
    "receipt field": "campo del comprobante",
    "clave de rastreo prefix": "prefijo de la clave de rastreo",
    "bank-specific wording": "texto propio del banco",
    "bank named on receipt": "banco mencionado en el comprobante",
    # --- Field names -----------------------------------------------------------------
    "payment date": "fecha de pago",
    "clave de rastreo": "clave de rastreo",
    "sending bank": "banco emisor",
    "receiving bank": "banco receptor",
    "beneficiary account": "cuenta beneficiaria",
    "amount": "monto",
    "pago a banco": "pago a banco",
    "dollars (SPID)": "dólares (SPID)",
    "ordering account": "cuenta ordenante",
    # --- Results ---------------------------------------------------------------------
    "Banxico only answers 09:30–23:00 (Mexico City); check then": (
        "Banxico solo responde de 09:30 a 23:00 (Ciudad de México); verifícalo entonces"
    ),
    "Not checked: Banxico stopped answering; try again later": (
        "No verificado: Banxico dejó de responder; intenta más tarde"
    ),
    "Already used: confirmed on {date} for {file} (not checked again)": (
        "Ya usado: confirmado el {date} para {file} (no se volvió a verificar)"
    ),
    "Already used: confirmed on {date} for {file}": ("Ya usado: confirmado el {date} para {file}"),
    "Identifying banks": "Identificando bancos",
    "Checking at Banxico": "Verificando en Banxico",
    "File not found": "Archivo no encontrado",
    "Reading": "Leyendo",
    "Receiving bank '{bank}' not in Banxico's list": (
        "El banco receptor '{bank}' no está en la lista de Banxico"
    ),
    "Sending bank '{bank}' not in Banxico's list": "El banco emisor '{bank}' no está en la lista de Banxico",
    "Couldn't identify the sending bank": "No se pudo identificar el banco emisor",
    "Both banks read as {bank}; check the fields": ("Ambos bancos se leyeron como {bank}; revisa los campos"),
    "Paid to {bank} itself (pago a banco), not to your accounts": (
        "Pagado al propio {bank} (pago a banco), no a tus cuentas"
    ),
    "Paid to {account}, not one of your accounts": ("Pagado a {account}, que no es una de tus cuentas"),
    "CEP doesn't match the receipt: it shows {problems}": (
        "El CEP no coincide con el comprobante: muestra {problems}"
    ),
    "CEP saved: {file}": "CEP guardado: {file}",
    "Banxico: {reason}": "Banxico: {reason}",
    "Unexpected error: {error}": "Error inesperado: {error}",
    # --- Dollar transfers (SPID) ------------------------------------------------------
    "Dollar transfer (SPID): needs a security code; check it in the desktop app or at {url}": (
        "Transferencia en dólares (SPID): requiere un código de seguridad; "
        "verifícala en la app de escritorio o en {url}"
    ),
    "Banxico rejected the code (or the data)": ("Banxico rechazó el código (o los datos)"),
    "Banxico sent an empty security image": "Banxico envió una imagen de seguridad vacía",
    "Couldn't get Banxico's security image: {error}": (
        "No se pudo obtener la imagen de seguridad de Banxico: {error}"
    ),
    "Waiting for the security code": "Esperando el código de seguridad",
    "Code rejected {count} times; check the fields and try again": (
        "Código rechazado {count} veces; revisa los campos e intenta de nuevo"
    ),
    "Not checked: no code typed": "No verificado: no se escribió el código",
    "{file}: dollar transfer (SPID) of {amount}; Banxico asks for a security code.": (
        "{file}: transferencia en dólares (SPID) de {amount}; Banxico pide un código de seguridad."
    ),
    "Wrong code. New image ({attempt} of {max}).": ("Código incorrecto. Nueva imagen ({attempt} de {max})."),
    "Image opened: {path}": ("Imagen abierta: {path}"),
    "Code image: {path}": "Imagen del código: {path}",
    "Code (? for another image, Enter to skip): ": "Código (? para otra imagen, Enter para omitir): ",
    "Dollar transfer (SPID)": ("Transferencia en dólares (SPID)"),
    "Banxico security code": "Código de seguridad de Banxico",
    "Type the characters in the image to check this dollar transfer.": (
        "Escribe los caracteres de la imagen para verificar esta transferencia en dólares."
    ),
    "Another image": "Otra imagen",
    "Skip": "Omitir",
    "Couldn't show the image. Ask for another.": ("No se pudo mostrar la imagen. Pide otra."),
    "Wrong code. Try this one ({attempt} of {max}).": (
        "Código incorrecto. Prueba con este ({attempt} de {max})."
    ),
    # --- Data folder, log, forgetting checks ---------------------------------------------
    "Data folder": "Carpeta de datos",
    "Open": "Abrir",
    "Forget": "Olvidar",
    "Forget the check of {file} on {date}? Its transfer will no longer count as used.": (
        "¿Olvidar la verificación de {file} del {date}? Su transferencia ya no contará como usada."
    ),
    "Couldn't change the history: {error}": "No se pudo modificar el historial: {error}",
}
