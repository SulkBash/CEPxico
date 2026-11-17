"""Dialog showing Banxico's CEP-SPID security image, for the person to type its code.

The app never reads the image itself: Banxico shows it so a person confirms each lookup.
"""

from __future__ import annotations

import io
import logging
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from PIL import Image, ImageTk

from cepxico.banxico import BanxicoError
from cepxico.gui import theme
from cepxico.i18n import tr
from cepxico.pipeline import MAX_CODE_ATTEMPTS, CodeRequest

logger = logging.getLogger(__name__)

ERROR_COLOR = theme.STATUS_COLORS["status_failed"]
IMAGE_SCALE = 2  # Banxico's image is small; shown larger so it's easy to read


class CodeDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, *, request: CodeRequest, on_answer: Callable[[str | None], None]):
        super().__init__(parent)
        self.title(tr("Banxico security code"))
        self.configure(bg=theme.CARD_BG)
        self.resizable(False, False)
        self.transient(parent)  # type: ignore[arg-type]
        self._request = request
        self._on_answer = on_answer
        self._answered = False
        self._photo: ImageTk.PhotoImage | None = None  # kept: Tk shows nothing once it's collected
        self.code = tk.StringVar()

        body = ttk.Frame(self, style="Card.TFrame", padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=request.file_name, style="CardTitle.TLabel").pack(anchor=tk.W)
        self._hint(
            body,
            tr(
                "Dollar transfer (SPID) of {amount}, clave de rastreo {clave}. Banxico's CEP-SPID "
                "service asks for the characters in this image before it answers.",
                amount=request.amount,
                clave=request.tracking_key,
            ),
        )
        if request.retry:
            tk.Label(
                body,
                text=tr(
                    "Banxico didn't accept the last code. Try this new image (attempt {attempt} of {max}).",
                    attempt=request.attempt,
                    max=MAX_CODE_ATTEMPTS,
                ),
                bg=theme.CARD_BG,
                fg=ERROR_COLOR,
                font=theme.font(9),
                justify=tk.LEFT,
                wraplength=380,
            ).pack(anchor=tk.W, pady=(6, 0))

        self.image_label = tk.Label(body, bg=theme.CARD_BG, font=theme.font(9), fg=ERROR_COLOR)
        self.image_label.pack(pady=(12, 4))
        self._show_image(request.image)
        theme.make_button(body, tr("Another image"), self.another_image).pack(pady=(0, 10))

        entry = ttk.Entry(body, textvariable=self.code, width=24, font=theme.font(14), justify=tk.CENTER)
        entry.pack()

        buttons = tk.Frame(body, bg=theme.CARD_BG)
        buttons.pack(fill=tk.X, pady=(14, 0))
        theme.make_button(buttons, tr("Check"), self.submit, variant="primary").pack(side=tk.RIGHT)
        theme.make_button(buttons, tr("Skip this receipt"), self.skip).pack(side=tk.RIGHT, padx=6)

        self.bind("<Return>", lambda _e: self.submit())
        self.bind("<Escape>", lambda _e: self.skip())
        self.protocol("WM_DELETE_WINDOW", self.skip)
        entry.focus_set()
        self.grab_set()

    @staticmethod
    def _hint(parent: tk.Misc, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            bg=theme.CARD_BG,
            fg=theme.TEXT_MUTED,
            font=theme.font(9),
            justify=tk.LEFT,
            wraplength=380,
        ).pack(anchor=tk.W, pady=(2, 0))

    def _show_image(self, data: bytes) -> None:
        try:
            with Image.open(io.BytesIO(data)) as image:
                image = image.convert("RGB")
                size = (image.width * IMAGE_SCALE, image.height * IMAGE_SCALE)
                self._photo = ImageTk.PhotoImage(image.resize(size, Image.LANCZOS))
            self.image_label.configure(image=self._photo, text="")
        except Exception as e:  # Pillow raises many types for damaged images
            logger.warning("Couldn't show Banxico's security image: %s", e)
            self._photo = None
            self.image_label.configure(
                image="", text=tr("Couldn't show Banxico's image; ask for another one.")
            )

    def another_image(self) -> None:
        try:
            self._show_image(self._request.new_image())
        except BanxicoError as e:
            self.image_label.configure(image="", text=str(e))
            self._photo = None
        self.code.set("")

    def _answer(self, code: str | None) -> None:
        if not self._answered:
            self._answered = True
            self._on_answer(code)
        self.destroy()

    def submit(self) -> None:
        if self.code.get().strip():
            self._answer(self.code.get().strip())

    def skip(self) -> None:
        self._answer(None)
