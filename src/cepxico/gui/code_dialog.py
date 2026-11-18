"""Dialog showing Banxico's CEP-SPID security image, for the person to type its code.

The app never reads the image itself: Banxico shows it so a person confirms each lookup.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cepxico.banxico import BanxicoError
from cepxico.gui import theme
from cepxico.i18n import tr
from cepxico.pipeline import MAX_CODE_ATTEMPTS, CodeRequest

logger = logging.getLogger(__name__)

IMAGE_SCALE = 2  # Banxico's image is small; shown larger so it's easy to read
WRAP = 380  # pixels: width of the explanation


class CodeDialog(QDialog):
    def __init__(self, parent: QWidget, *, request: CodeRequest, on_answer: Callable[[str | None], None]):
        super().__init__(parent)
        self.setWindowTitle(f"{tr('Banxico security code')} - {request.file_name}")
        self._request = request
        self._on_answer = on_answer
        self._answered = False
        self.picture: QPixmap | None = None  # the image as shown, IMAGE_SCALE times its size

        column = QVBoxLayout(self)
        column.addWidget(
            theme.wrapped(
                tr(
                    "Dollar transfer (SPID) of {amount}, clave de rastreo {clave}. Banxico's CEP-SPID "
                    "service asks for the characters in this image before it answers.",
                    amount=request.amount,
                    clave=request.tracking_key,
                ),
                WRAP,
            )
        )
        if request.retry:
            retry = theme.error_label()
            retry.setText(
                tr(
                    "Banxico didn't accept the last code. Try this new image (attempt {attempt} of {max}).",
                    attempt=request.attempt,
                    max=MAX_CODE_ATTEMPTS,
                )
            )
            retry.setFixedWidth(WRAP)
            column.addWidget(retry)

        # The image in a sunken frame, as pictures sit on classic forms.
        self.image_label = QLabel()
        self.image_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.image_label.setFrameShadow(QFrame.Shadow.Sunken)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setWordWrap(True)
        self.image_label.setMinimumHeight(90)
        column.addWidget(self.image_label)
        self._show_image(request.image)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Code") + ":"))
        self.code = QLineEdit()
        self.code.setFont(theme.mono(3))
        row.addWidget(self.code, 1)
        another = QPushButton(tr("Another image"))
        another.setAutoDefault(False)
        another.clicked.connect(self.another_image)
        row.addWidget(another)
        column.addLayout(row)

        buttons = QDialogButtonBox()
        check = buttons.addButton(tr("Check"), QDialogButtonBox.ButtonRole.AcceptRole)
        skip = buttons.addButton(tr("Skip this receipt"), QDialogButtonBox.ButtonRole.RejectRole)
        check.clicked.connect(self.submit)
        skip.clicked.connect(self.skip)
        check.setDefault(True)  # Enter
        column.addWidget(buttons)

        theme.present(self, parent)
        self.code.setFocus()

    def _show_image(self, data: bytes) -> None:
        try:
            with Image.open(io.BytesIO(data)) as image:
                image = image.convert("RGBA")
                image = image.resize((image.width * IMAGE_SCALE, image.height * IMAGE_SCALE), Image.LANCZOS)
            self.picture = QPixmap.fromImage(theme.qimage(image))
            self.image_label.setPixmap(self.picture)
        except Exception as e:  # Pillow raises many types for damaged images
            logger.warning("Couldn't show Banxico's security image: %s", e)
            self.picture = None
            self.image_label.setText(tr("Couldn't show Banxico's image; ask for another one."))

    def another_image(self) -> None:
        try:
            self._show_image(self._request.new_image())
        except BanxicoError as e:
            self.picture = None
            self.image_label.setText(str(e))
        self.code.clear()

    def _answer(self, code: str | None) -> None:
        if not self._answered:
            self._answered = True
            self._on_answer(code)
        super().done(QDialog.DialogCode.Accepted if code else QDialog.DialogCode.Rejected)

    def submit(self) -> None:
        if self.code.text().strip():
            self._answer(self.code.text().strip())

    def skip(self) -> None:
        self._answer(None)

    def reject(self) -> None:  # Escape and the window's close button
        self.skip()
