"""The app's icons, drawn with Pillow when first needed.

Drawn rather than shipped as files so they stay sharp at any display scaling: each one
is painted at four times its size on a 24-unit grid, then scaled down.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from PIL import Image, ImageDraw

SUPERSAMPLE = 4
WHITE = "#FFFFFF"


class Pen:
    """Draws on a square canvas in grid units (0..grid), at SUPERSAMPLE times the size."""

    def __init__(self, size: int, grid: float = 24):
        self.size = size
        self.k = size * SUPERSAMPLE / grid
        self.image = Image.new("RGBA", (size * SUPERSAMPLE, size * SUPERSAMPLE), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.image)

    def _xy(self, points: tuple[float, ...]) -> list[float]:
        return [v * self.k for v in points]

    def _w(self, width: float) -> int:
        return max(1, round(width * self.k))

    def line(self, *points: float, color: str, width: float = 1.8) -> None:
        """A polyline with round caps and joints."""
        xy = self._xy(points)
        self.draw.line(xy, fill=color, width=self._w(width), joint="curve")
        r = width * self.k / 2
        for x, y in ((xy[0], xy[1]), (xy[-2], xy[-1])):
            self.draw.ellipse((x - r, y - r, x + r, y + r), fill=color)

    def circle(
        self,
        cx: float,
        cy: float,
        r: float,
        *,
        fill: str | None = None,
        outline: str | None = None,
        width: float = 1.8,
    ) -> None:
        box = self._xy((cx - r, cy - r, cx + r, cy + r))
        self.draw.ellipse(box, fill=fill, outline=outline, width=self._w(width) if outline else 0)

    def rect(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        *,
        radius: float = 0,
        fill: str | None = None,
        outline: str | None = None,
        width: float = 1.8,
    ) -> None:
        self.draw.rounded_rectangle(
            self._xy((x0, y0, x1, y1)),
            radius=radius * self.k,
            fill=fill,
            outline=outline,
            width=self._w(width) if outline else 0,
        )

    def polygon(
        self, *points: float, fill: str | None = None, outline: str | None = None, width: float = 1.8
    ) -> None:
        self.draw.polygon(self._xy(points), fill=fill)
        if outline:
            self.line(*points, points[0], points[1], color=outline, width=width)

    def arc(
        self, cx: float, cy: float, r: float, start: float, end: float, *, color: str, width: float = 1.8
    ) -> None:
        """Clockwise from `start` to `end` degrees, 0 = three o'clock."""
        self.draw.arc(
            self._xy((cx - r, cy - r, cx + r, cy + r)), start, end, fill=color, width=self._w(width)
        )

    def erase_circle(self, cx: float, cy: float, r: float) -> None:
        self.circle(cx, cy, r, fill=(0, 0, 0, 0))  # type: ignore[arg-type]  # writes, doesn't blend

    def result(self) -> Image.Image:
        return self.image.resize((self.size, self.size), Image.LANCZOS)


# --- pieces shared by several icons -----------------------------------------------------


def _page(p: Pen, x0: float, color: str, fill: str | None = None) -> None:
    """A sheet of paper with a folded corner, 12 units wide, starting at x0."""
    x1, fold = x0 + 12, 4
    p.polygon(x0, 3, x1 - fold, 3, x1, 3 + fold, x1, 21, x0, 21, fill=fill, outline=color, width=1.6)
    p.line(x1 - fold, 3, x1 - fold, 3 + fold, x1, 3 + fold, color=color, width=1.4)


def _badge(p: Pen, cx: float, cy: float, r: float, fill: str) -> None:
    p.erase_circle(cx, cy, r + 1.4)  # a gap between the badge and what's behind it
    p.circle(cx, cy, r, fill=fill)


# --- toolbar icons -----------------------------------------------------------------------
# Each takes (pen, ink, accent): the main line color and the color of the detail that
# says what it does.


def _add(p: Pen, ink: str, accent: str) -> None:
    _page(p, 3, ink)
    _badge(p, 17, 17, 5.2, accent)
    p.line(17, 14.2, 17, 19.8, color=WHITE, width=1.8)
    p.line(14.2, 17, 19.8, 17, color=WHITE, width=1.8)


def _remove(p: Pen, ink: str, accent: str) -> None:
    _page(p, 3, ink)
    _badge(p, 17, 17, 5.2, accent)
    p.line(14.2, 17, 19.8, 17, color=WHITE, width=1.8)


def _edit(p: Pen, ink: str, accent: str) -> None:
    # A pencil from bottom left to top right: body, ferrule, eraser, and the tip.
    def along(t: float, side: float) -> tuple[float, float]:
        # point at distance t along the axis, `side` units off it
        ax, ay, ux, uy = 5.0, 19.0, 1 / math.sqrt(2), -1 / math.sqrt(2)
        return ax + ux * t - uy * side, ay + uy * t + ux * side

    half = 2.6
    body = (*along(4.2, -half), *along(15.5, -half), *along(15.5, half), *along(4.2, half))
    p.polygon(*body, fill=accent)
    eraser = (*along(15.5, -half), *along(19, -half), *along(19, half), *along(15.5, half))
    p.polygon(*eraser, fill=ink)
    tip = (*along(0, 0), *along(4.2, -half), *along(4.2, half))
    p.polygon(*tip, fill="#F3D9A4")
    p.polygon(*along(0, 0), *along(1.7, -1.05), *along(1.7, 1.05), fill=ink)
    p.line(*along(4.2, -half), *along(0, 0), *along(4.2, half), color=ink, width=1.1)
    p.line(*along(4.2, -half), *along(19, -half), *along(19, half), *along(4.2, half), color=ink, width=1.1)


def _trash(p: Pen, ink: str, accent: str) -> None:
    p.line(4, 6.5, 20, 6.5, color=accent, width=1.8)
    p.line(9.5, 6.5, 9.5, 4, 14.5, 4, 14.5, 6.5, color=accent, width=1.6)
    p.polygon(6, 6.5, 18, 6.5, 17, 21, 7, 21, outline=ink, width=1.6)
    for x in (10, 14):
        p.line(x, 10, x, 17.5, color=ink, width=1.4)


def _folder(p: Pen, ink: str, accent: str) -> None:
    p.polygon(2.5, 5, 9.5, 5, 11.5, 7.5, 21.5, 7.5, 21.5, 19.5, 2.5, 19.5, fill="#E0A63A")
    p.rect(2.5, 9.5, 21.5, 19.5, radius=1.2, fill="#F6C45A")
    p.line(2.5, 9.5, 21.5, 9.5, color="#FBDB8E", width=1)


def _history(p: Pen, ink: str, accent: str) -> None:
    p.circle(12.5, 12.5, 8.4, outline=ink, width=1.7)
    p.line(12.5, 7.6, 12.5, 12.5, 16, 14.6, color=accent, width=1.8)
    # the arrow at the start of the dial: time going back
    p.polygon(1.6, 9.4, 6.8, 9.6, 4.6, 14.2, fill=ink)


def _settings(p: Pen, ink: str, accent: str) -> None:
    teeth, outer, inner = 8, 10.2, 7.6
    points: list[float] = []
    for i in range(teeth):
        base = 2 * math.pi * i / teeth
        for offset, r in ((-0.27, inner), (-0.17, outer), (0.17, outer), (0.27, inner)):
            points += [12 + r * math.cos(base + offset), 12 + r * math.sin(base + offset)]
    p.polygon(*points, fill=ink)
    p.circle(12, 12, 7.6, fill=ink)
    p.erase_circle(12, 12, 3.4)


def _play(p: Pen, ink: str, accent: str) -> None:
    p.polygon(7.5, 4.5, 19.5, 12, 7.5, 19.5, fill=accent, outline=accent, width=1.6)


def _stop(p: Pen, ink: str, accent: str) -> None:
    p.rect(5.5, 5.5, 18.5, 18.5, radius=2.4, fill=accent)


ICONS: dict[str, Callable[[Pen, str, str], None]] = {
    "add": _add,
    "remove": _remove,
    "edit": _edit,
    "trash": _trash,
    "folder": _folder,
    "history": _history,
    "settings": _settings,
    "play": _play,
    "stop": _stop,
}


def draw(name: str, size: int, ink: str, accent: str) -> Image.Image:
    pen = Pen(size)
    ICONS[name](pen, ink, accent)
    return pen.result()


# --- status glyphs -----------------------------------------------------------------------


def status(kind: str, size: int, color: str, frame: int = 0) -> Image.Image:
    """A filled disc with a white symbol: "success" ✓, "review" !, "notfound" ?, "failed" ×,
    "cancelled" –; "pending" is an empty ring and "processing" a spinner at `frame` (0-7)."""
    p = Pen(size, grid=16)
    if kind == "pending":
        p.circle(8, 8, 5.6, outline=color, width=1.5)
        return p.result()
    if kind == "processing":
        p.circle(8, 8, 5.4, outline="#F1DDB2", width=2.2)
        start = frame * 45
        p.arc(8, 8, 5.4, start, start + 110, color=color, width=2.2)
        return p.result()
    p.circle(8, 8, 6.6, fill=color)
    if kind == "success":
        p.line(4.9, 8.2, 7.1, 10.4, 11.2, 5.9, color=WHITE, width=1.7)
    elif kind == "failed":
        p.line(5.6, 5.6, 10.4, 10.4, color=WHITE, width=1.7)
        p.line(10.4, 5.6, 5.6, 10.4, color=WHITE, width=1.7)
    elif kind == "review":
        p.line(8, 4.4, 8, 8.8, color=WHITE, width=1.8)
        p.circle(8, 11.3, 1.05, fill=WHITE)
    elif kind == "notfound":
        p.arc(8, 6.3, 2.3, 180, 405, color=WHITE, width=1.6)
        p.line(9.6, 7.95, 8, 9.1, 8, 9.4, color=WHITE, width=1.6)
        p.circle(8, 11.7, 1.0, fill=WHITE)
    elif kind == "cancelled":
        p.line(5.2, 8, 10.8, 8, color=WHITE, width=1.8)
    return p.result()


# --- the app's own mark ---------------------------------------------------------------


def logo(size: int, ink: str, accent: str) -> Image.Image:
    """A receipt with a check stamp on a navy tile: CEPxico's icon."""
    p = Pen(size)
    p.rect(0.5, 0.5, 23.5, 23.5, radius=5.5, fill=ink)
    outline = [6, 4, 18, 4]
    teeth = 6
    for i in range(teeth, -1, -1):
        outline += [6 + i * 12 / teeth, 19.5 if i % 2 == 0 else 18]
    p.polygon(*outline, fill=WHITE)
    for y, end in ((8, 15), (11, 15), (14, 11.5)):
        p.line(8.8, y, end, y, color="#9FB1CB", width=1.3)
    p.circle(16.6, 16.6, 5.4, fill=ink)
    p.circle(16.6, 16.6, 4.4, fill=accent)
    p.line(14.6, 16.7, 16.1, 18.2, 18.8, 15.2, color=WHITE, width=1.4)
    return p.result()
