"""Spanish for every message passed to i18n.tr(), keyed by its English text.

Mexican Spanish, addressing the user as "tú" like most Mexican banking apps. Banxico's
own terms (CEP, clave de rastreo, pago a banco, Liquidado...) are kept as Banxico
writes them. tests/test_i18n.py checks every tr() message is here with the same
{placeholders}.
"""

ES: dict[str, str] = {
    # --- Banxico's answers -----------------------------------------------------------
    "Banxico's limit of lookups was reached; try again later": (
        "Se alcanzó el límite de consultas de Banxico; intenta más tarde"
    ),
    "Payment is real and settled (Liquidado), but the receiving bank hasn't issued its CEP yet; "
    "check again later": (
        "El pago es real y está liquidado (Liquidado), pero el banco receptor aún no emite su CEP; "
        "vuelve a revisar más tarde"
    ),
    "Banxico received the payment but hasn't settled it yet (En proceso); check again later": (
        "Banxico recibió el pago pero aún no lo liquida (En proceso); vuelve a revisar más tarde"
    ),
    "Payment was cancelled before it settled (Cancelado); the money didn't arrive": (
        "El pago se canceló antes de liquidarse (Cancelado); el dinero no llegó"
    ),
    "Payment was returned by the beneficiary's bank (Retornado); the money didn't stay in the account": (
        "El banco del beneficiario devolvió el pago (Retornado); el dinero no se quedó en la cuenta"
    ),
    "Payment was returned by the beneficiary's bank (Devuelto); the money didn't stay in the account": (
        "El banco del beneficiario devolvió el pago (Devuelto); el dinero no se quedó en la cuenta"
    ),
    "Banxico found the payment (status: {status}) but has no CEP for it": (
        "Banxico encontró el pago (estado: {status}) pero no tiene CEP para él"
    ),
    "CEP downloaded": "CEP descargado",
    "Banxico returned no bank list for {date}": "Banxico no devolvió la lista de bancos del {date}",
    "Invalid date '{date}' (expected dd-mm-yyyy)": "Fecha no válida '{date}' (se espera dd-mm-aaaa)",
    "Invalid clave de rastreo '{clave}'": "Clave de rastreo no válida '{clave}'",
    "Invalid account '{account}'": "Cuenta no válida '{account}'",
    "Invalid amount '{amount}'": "Monto no válido '{amount}'",
    "Sender and receiver are both {bank}; CEP only covers interbank transfers": (
        "El emisor y el receptor son ambos {bank}; el CEP solo existe para transferencias entre bancos"
    ),
    "Banxico server error {code}: {message}": "Error del servidor de Banxico {code}: {message}",
    "Banxico rejected the data as incomplete or invalid": (
        "Banxico rechazó los datos por incompletos o no válidos"
    ),
    "Banxico is asking for the security image, which it does after too many lookups; try again later "
    "or check this receipt on Banxico's website": (
        "Banxico está pidiendo la imagen de seguridad, lo que hace tras demasiadas consultas; intenta más "
        "tarde o revisa este comprobante en el sitio de Banxico"
    ),
    "unknown": "desconocido",
    "Could not load Banxico bank list: {error}": "No se pudo cargar la lista de bancos de Banxico: {error}",
    "Could not reach Banxico: {error}": "No se pudo conectar con Banxico: {error}",
    "Banxico request failed: {error}": "Falló la consulta a Banxico: {error}",
    "CEP download failed: {error}": "Falló la descarga del CEP: {error}",
    "Banxico returned no CEP for this data": "Banxico no devolvió ningún CEP con estos datos",
    # --- Command line ----------------------------------------------------------------
    "Files: {count}": "Archivos: {count}",
    "CEP found and saved: {count}": "CEP encontrado y guardado: {count}",
    "Extract SPEI transfer data from receipts and download their CEP from Banxico. Run without files "
    "to open the desktop app.": (
        "Extrae los datos de transferencias SPEI de los comprobantes y descarga su CEP de Banxico. "
        "Sin archivos, abre la aplicación de escritorio."
    ),
    "Settings made in the desktop app (own accounts, files to save, language) also apply here: "
    "{settings}. Every check is recorded in {history}.": (
        "La configuración hecha en la aplicación de escritorio (cuentas propias, archivos a guardar, "
        "idioma) también aplica aquí: {settings}. Cada verificación se registra en {history}."
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
    "what to save for each CEP: the PDF, the XML, or both in one ZIP (default: as set in the desktop app)": (
        "qué guardar de cada CEP: el PDF, el XML o ambos en un ZIP (por omisión: lo configurado en la "
        "aplicación de escritorio)"
    ),
    "also write this run's results to a CSV file": (
        "escribir también los resultados de esta ejecución en un CSV"
    ),
    "write every check ever made to a CSV file, and exit": (
        "escribir todas las verificaciones hechas en un archivo CSV, y salir"
    ),
    "don't record this run, and don't flag receipts for transfers already confirmed for another receipt": (
        "no registrar esta ejecución, ni marcar comprobantes de transferencias ya confirmadas con otro "
        "comprobante"
    ),
    "language of the messages (default: as set)": "idioma de los mensajes (por omisión: el configurado)",
    "show debug output": "mostrar mensajes de depuración",
    "must be a whole number from 1 to {max}": "debe ser un número entero del 1 al {max}",
    "NEEDS REVIEW (real payment, but not a clean confirmation): {count}": (
        "REQUIERE REVISIÓN (pago real, pero no una confirmación limpia): {count}"
    ),
    "NOT FOUND at Banxico (check data; receipt may be fake): {count}": (
        "NO ENCONTRADO en Banxico (revisa los datos; el comprobante podría ser falso): {count}"
    ),
    "Errors / skipped: {count}": "Errores / omitidos: {count}",
    "Wrote {count} checks to {file}": "Se escribieron {count} verificaciones en {file}",
    "Results written to {file}": "Resultados escritos en {file}",
    "Summary": "Resumen",
    # --- Reading receipts ------------------------------------------------------------
    "No text extracted": "No se pudo extraer texto",
    "Missing {field}": "Falta {field}",
    "'{raw}' isn't a valid date (day/month/year, e.g. 05/11/2026)": (
        "'{raw}' no es una fecha válida (día/mes/año, p. ej. 05/11/2026)"
    ),
    "must be 1 to {max} letters and digits": "debe tener de 1 a {max} letras y dígitos",
    "must contain digits only": "solo debe contener dígitos",
    "has {count} digits; expected 18 (CLABE), 16 (debit card) or 10 (phone)": (
        "tiene {count} dígitos; se esperan 18 (CLABE), 16 (tarjeta de débito) o 10 (celular)"
    ),
    "isn't a valid CLABE (its last digit doesn't match); check for a typo": (
        "no es una CLABE válida (su último dígito no coincide); revisa si hay un error de captura"
    ),
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
    "Processing": "Procesando",
    "Success": "Confirmado",
    "Not Found": "No encontrado",
    "Review": "Revisar",
    "Failed": "Falló",
    "Cancelled": "Cancelado",
    # --- Main window -----------------------------------------------------------------
    "Documents & Images": "Documentos e imágenes",
    "All Files": "Todos los archivos",
    "CEPxico - SPEI receipt checker": "CEPxico - Verificador de comprobantes SPEI",
    "Receipt": "Comprobante",
    "Copy": "Copiar",
    "Search": "Buscar",
    "Code": "Código",
    "Banks": "Bancos",
    "Banxico's record": "Registro de Banxico",
    # Menu bar
    "Receipts": "Comprobantes",
    "Tools": "Herramientas",
    "Help": "Ayuda",
    "Paste Image": "Pegar imagen",
    "Select All": "Seleccionar todo",
    "Exit": "Salir",
    "About CEPxico": "Acerca de CEPxico",
    "Checks SPEI receipts against Banxico's CEP service and saves the CEP of every transfer it confirms.": (
        "Verifica comprobantes SPEI con el servicio CEP de Banxico y guarda el CEP de cada "
        "transferencia que confirma."
    ),
    "Process Files": "Procesar archivos",
    "Cancel": "Cancelar",
    "Select a file to view details.": "Selecciona un archivo para ver sus detalles.",
    "Image pasted from clipboard": "Imagen pegada desde el portapapeles",
    "Open CEP Folder": "Abrir carpeta de CEP",
    "Settings saved": "Configuración guardada",
    "Ordering account": "Cuenta ordenante",
    "Account": "Cuenta",
    "Processing files...": "Procesando archivos...",
    "Processed {done}/{total}: {name}": "Procesado {done}/{total}: {name}",
    "Processing Summary": "Resumen del proceso",
    "Total files loaded: {count}": "Archivos cargados: {count}",
    "Processed: {count}": "Procesados: {count}",
    "Ready": "Listo",
    "CEP Found": "CEP encontrado",
    "Needs Review": "Por revisar",
    "Not Found at Banxico": "No encontrado en Banxico",
    "File": "Archivo",
    "Status": "Estado",
    "Result": "Resultado",
    "Please wait until current processing finishes.": "Espera a que termine el proceso en curso.",
    "Select Documents": "Seleccionar documentos",
    "Skipped {count} duplicate file(s)": "Se omitieron {count} archivo(s) repetido(s)",
    "No image found on clipboard": "No hay ninguna imagen en el portapapeles",
    "Couldn't save the settings: {error}": "No se pudo guardar la configuración: {error}",
    "Settings": "Configuración",
    "Edit Fields": "Editar campos",
    "Select a file first.": "Primero selecciona un archivo.",
    "Fields can be edited for files that failed, weren't found at Banxico or need review.": (
        "Se pueden editar los campos de archivos que fallaron, no se encontraron en Banxico o "
        "requieren revisión."
    ),
    "Edited, ready to check": "Editado, listo para verificar",
    "N/A": "N/D",
    "Pago a banco: paid to the receiving bank itself": "Pago a banco: pagado al propio banco receptor",
    "No Files": "Sin archivos",
    "No files to process.": "No hay archivos que procesar.",
    "Nothing to Check": "Nada que verificar",
    "Every file is already confirmed at Banxico.\n\nTo check a file again, remove it and add it back.": (
        "Todos los archivos ya están confirmados en Banxico.\n\n"
        "Para verificar un archivo de nuevo, quítalo y vuelve a agregarlo."
    ),
    "Queued": "En cola",
    "Cancel requested. Stopping after the files in progress...": (
        "Cancelación solicitada. Se detendrá al terminar los archivos en curso..."
    ),
    "Processing cancelled by user": "Proceso cancelado por el usuario",
    "Processing complete": "Proceso terminado",
    "Processing Cancelled": "Proceso cancelado",
    "Processing Complete": "Proceso terminado",
    "Already confirmed, not checked again: {count}": "Ya confirmados, no se verificaron de nuevo: {count}",
    "Cancelled: {count}": "Cancelados: {count}",
    "CEPs saved to: {folder}": "CEP guardados en: {folder}",
    "NEEDS REVIEW ({count}) - a real payment, but not a clean confirmation:": (
        "REQUIEREN REVISIÓN ({count}): pago real, pero no una confirmación limpia:"
    ),
    "NOT FOUND at Banxico ({count}) - check the extracted data; the receipt may be fake:": (
        "NO ENCONTRADOS en Banxico ({count}): revisa los datos extraídos; el comprobante podría ser falso:"
    ),
    "Errors ({count}):": "Errores ({count}):",
    "Add Files": "Agregar archivos",
    "Remove Selected": "Quitar seleccionados",
    "Clear All": "Quitar todos",
    "History": "Historial",
    "Invalid File": "Archivo no válido",
    "Only PDF or image files are accepted: {path}": "Solo se aceptan archivos PDF o de imagen: {path}",
    "Couldn't open {path}: {error}": "No se pudo abrir {path}: {error}",
    "Path": "Ruta",
    "Date": "Fecha",
    "Clave de rastreo": "Clave de rastreo",
    "Amount": "Monto",
    "Sending bank": "Banco emisor",
    "Receiving bank": "Banco receptor",
    "edited": "editado",
    "Skipped by user": "Omitido por el usuario",
    "Drag and drop files, paste a screenshot ({shortcut}), or use Add Files.": (
        "Arrastra y suelta archivos, pega una captura de pantalla ({shortcut}) o usa Agregar archivos."
    ),
    "Open Receipt": "Abrir comprobante",
    "Status at Banxico": "Estado en Banxico",
    "Sender": "Ordenante",
    "Beneficiary": "Beneficiario",
    "Concept": "Concepto",
    "Typed by user": "Capturado por el usuario",
    # --- Edit Fields -----------------------------------------------------------------
    "day/month/year": "día/mes/año",
    "name Banxico uses, e.g. BANORTE": "nombre que usa Banxico, p. ej. BANORTE",
    "not needed with a valid CLABE": "no hace falta con una CLABE válida",
    "CLABE, debit card or phone": "CLABE, tarjeta de débito o celular",
    "Beneficiary account": "Cuenta beneficiaria",
    "the bank that was paid": "el banco al que se pagó",
    "the account the payment came from (CLABE, card or phone)": (
        "la cuenta de la que salió el pago (CLABE, tarjeta o celular)"
    ),
    "Save and Check": "Guardar y verificar",
    "Save": "Guardar",
    "Fix anything read wrong and fill in what's missing, copying from the receipt.": (
        "Corrige lo que se leyó mal y completa lo que falta, copiándolo del comprobante."
    ),
    "Pago a banco: paid to the receiving bank itself, not to one of its customers": (
        "Pago a banco: pagado al propio banco receptor, no a uno de sus clientes"
    ),
    # --- History ---------------------------------------------------------------------
    "Export CSV...": "Exportar CSV...",
    "Checked": "Verificado",
    "Details": "Detalles",
    "{shown} of {total}": "{shown} de {total}",
    "Open CEP": "Abrir CEP",
    "Select a row first.": "Primero selecciona una fila.",
    "Couldn't read the history: {error}": "No se pudo leer el historial: {error}",
    "No CEP file for this check on this computer.": (
        "No hay archivo de CEP de esta verificación en esta computadora."
    ),
    "Couldn't write the file: {error}": "No se pudo escribir el archivo: {error}",
    "Kept to catch receipts used twice and for your records. Search by file, clave de rastreo, amount, "
    "name or bank.": (
        "Se guarda para detectar comprobantes usados dos veces y para tus registros. Busca por archivo, "
        "clave de rastreo, monto, nombre o banco."
    ),
    "Payment date": "Fecha de pago",
    "CEP file": "Archivo del CEP",
    "File path": "Ruta del archivo",
    "yes": "sí",
    # --- Settings --------------------------------------------------------------------
    "PDF and XML in one ZIP file": "PDF y XML en un archivo ZIP",
    "Same as the system": "Igual que el sistema",
    "The XML is Banxico's digitally signed record of the transfer. It can be checked at "
    "banxico.org.mx/validador-cep-spei and imported by accounting software. The app always reads it to "
    "confirm the CEP matches the receipt; this only keeps a copy. If Banxico's XML can't be read, the "
    "PDF is saved instead.": (
        "El XML es el registro de la transferencia firmado digitalmente por Banxico. Se puede validar en "
        "banxico.org.mx/validador-cep-spei e importar en software contable. La aplicación siempre lo lee "
        "para confirmar que el CEP coincide con el comprobante; esta opción solo guarda una copia. Si el "
        "XML de Banxico no se puede leer, se guarda el PDF."
    ),
    "A real transfer to someone else's account would otherwise pass as confirmed. Receipts paid "
    "elsewhere are marked Review without asking Banxico. One account per line: CLABE, and also the "
    "debit card or phone number if customers pay to those.": (
        "De lo contrario, una transferencia real a la cuenta de otra persona pasaría como confirmada. Los "
        "comprobantes pagados a otra cuenta se marcan como Revisar sin consultar a Banxico. Una cuenta por "
        "línea: CLABE, y también la tarjeta de débito o el celular si tus clientes pagan a esos."
    ),
    "Add at least one account, or turn the check off.": (
        "Agrega al menos una cuenta, o desactiva la verificación."
    ),
    "Save each CEP as": "Guardar cada CEP como",
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
    "Banxico's CEP service only answers from 09:30 to 23:00 (Mexico City time); check this receipt then": (
        "El servicio de CEP de Banxico solo responde de 09:30 a 23:00 (hora de la Ciudad de México); "
        "verifica este comprobante en ese horario"
    ),
    "Not checked: Banxico stopped answering lookups for now; try again later": (
        "No verificado: Banxico dejó de responder consultas por ahora; intenta más tarde"
    ),
    "Receipt already used: Banxico confirmed this transfer on {date} for {file}; not checked again": (
        "Comprobante ya usado: Banxico confirmó esta transferencia el {date} con {file}; no se volvió a "
        "verificar"
    ),
    "Receipt already used: Banxico confirmed this transfer on {date} for {file}": (
        "Comprobante ya usado: Banxico confirmó esta transferencia el {date} con {file}"
    ),
    "Identifying banks": "Identificando bancos",
    "Checking at Banxico": "Verificando en Banxico",
    "File not found": "Archivo no encontrado",
    "Extracting": "Extrayendo",
    "Receiving bank '{bank}' not in Banxico's list": (
        "El banco receptor '{bank}' no está en la lista de Banxico"
    ),
    "Sending bank '{bank}' not in Banxico's list": "El banco emisor '{bank}' no está en la lista de Banxico",
    "Couldn't identify the sending bank": "No se pudo identificar el banco emisor",
    "Sending and receiving bank are both {bank}; check the extracted fields": (
        "El banco emisor y el receptor son ambos {bank}; revisa los campos extraídos"
    ),
    "Paid to {bank} itself (pago a banco), not to one of your accounts": (
        "Pagado al propio {bank} (pago a banco), no a una de tus cuentas"
    ),
    "Paid to account {account}, which isn't one of your accounts (Settings); not checked at Banxico": (
        "Pagado a la cuenta {account}, que no es una de tus cuentas (Configuración); no se consultó a Banxico"
    ),
    "CEP doesn't match the receipt: it shows {problems}": (
        "El CEP no coincide con el comprobante: muestra {problems}"
    ),
    "CEP saved: {file}": "CEP guardado: {file}",
    "No CEP at Banxico: {reason}": "Sin CEP en Banxico: {reason}",
    "Unexpected error: {error}": "Error inesperado: {error}",
    # --- Dollar transfers (SPID) ------------------------------------------------------
    "Transfer in dollars (SPID). Banxico's CEP-SPID service asks you to type a security image: check "
    "it in the desktop app or from a terminal, or look it up at {url}": (
        "Transferencia en dólares (SPID). El servicio CEP-SPID de Banxico pide escribir una imagen de "
        "seguridad: verifícala en la aplicación de escritorio o desde una terminal, o consúltala en {url}"
    ),
    "Banxico didn't accept the security code (or the data)": (
        "Banxico no aceptó el código de seguridad (o los datos)"
    ),
    "Banxico sent an empty security image": "Banxico envió una imagen de seguridad vacía",
    "Couldn't get Banxico's security image: {error}": (
        "No se pudo obtener la imagen de seguridad de Banxico: {error}"
    ),
    "Waiting for the security code": "Esperando el código de seguridad",
    "Banxico didn't accept the security code {count} times; check the extracted fields and try again": (
        "Banxico no aceptó el código de seguridad {count} veces; revisa los campos extraídos e intenta "
        "de nuevo"
    ),
    "Not checked: no security code was typed": "No verificado: no se escribió el código de seguridad",
    "{file}: dollar transfer (SPID) of {amount}. Banxico's CEP-SPID service asks for the characters "
    "in a security image.": (
        "{file}: transferencia en dólares (SPID) de {amount}. El servicio CEP-SPID de Banxico pide los "
        "caracteres de una imagen de seguridad."
    ),
    "Banxico didn't accept the last code; this is a new image (attempt {attempt} of {max}).": (
        "Banxico no aceptó el último código; esta es una imagen nueva (intento {attempt} de {max})."
    ),
    "The image is open in your image viewer: {path}": (
        "La imagen está abierta en tu visor de imágenes: {path}"
    ),
    "Open this image to see the code: {path}": "Abre esta imagen para ver el código: {path}",
    "Code (? for another image, Enter to skip): ": "Código (? para otra imagen, Enter para omitir): ",
    "Dollar transfer (SPID), checked at Banxico's CEP-SPID ({url})": (
        "Transferencia en dólares (SPID), verificada en el CEP-SPID de Banxico ({url})"
    ),
    "Dollar transfer (SPID): checked at Banxico's CEP-SPID, which asks you to type a security image": (
        "Transferencia en dólares (SPID): se verifica en el CEP-SPID de Banxico, que pide escribir una "
        "imagen de seguridad"
    ),
    "Banxico security code": "Código de seguridad de Banxico",
    "Dollar transfer (SPID) of {amount}, clave de rastreo {clave}. Banxico's CEP-SPID service asks "
    "for the characters in this image before it answers.": (
        "Transferencia en dólares (SPID) de {amount}, clave de rastreo {clave}. El servicio CEP-SPID de "
        "Banxico pide los caracteres de esta imagen antes de responder."
    ),
    "Another image": "Otra imagen",
    "Check": "Verificar",
    "Skip this receipt": "Omitir este comprobante",
    "Couldn't show Banxico's image; ask for another one.": (
        "No se pudo mostrar la imagen de Banxico; pide otra."
    ),
    "Banxico didn't accept the last code. Try this new image (attempt {attempt} of {max}).": (
        "Banxico no aceptó el último código. Prueba con esta imagen nueva (intento {attempt} de {max})."
    ),
    # --- Data folder, log, forgetting checks ---------------------------------------------
    "Data folder": "Carpeta de datos",
    "Settings, history and the log file (cepxico.log, to attach to bug reports).": (
        "Configuración, historial y el archivo de registro "
        "(cepxico.log, para adjuntar a reportes de errores)."
    ),
    "Open": "Abrir",
    "Forget": "Olvidar",
    "Forget the check of {file} on {date}? If Banxico confirmed it, its transfer no longer counts as "
    "used, so another receipt for it can pass.": (
        "¿Olvidar la verificación de {file} del {date}? Si Banxico la confirmó, su transferencia deja de "
        "contar como usada, así que otro comprobante de ella podrá pasar."
    ),
    "Couldn't change the history: {error}": "No se pudo modificar el historial: {error}",
}
