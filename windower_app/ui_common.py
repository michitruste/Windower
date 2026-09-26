"""Shared GUI bits: colours, on-screen zone overlay, small helpers."""
from __future__ import annotations

import base64
import tkinter as tk

from .icons import png_bytes
from .model import Layout, Rect

BG = "#1e1f24"
PANEL = "#26282f"
CANVAS_BG = "#15161a"
FG = "#e8e8ec"
MUTED = "#9a9ca8"
ACCENT = "#4f8cff"
SELECT = "#ffffff"

ZONE_COLORS = [
    "#4f8cff", "#34c38f", "#f1b44c", "#f46a6a", "#a66efa",
    "#50c8e6", "#e667b8", "#8fc35a", "#ff8f4f", "#7a88ff",
]


def zone_color(i: int) -> str:
    return ZONE_COLORS[i % len(ZONE_COLORS)]


def blend(hex_color: str, bg: str = CANVAS_BG, alpha: float = 0.25) -> str:
    """Mix a colour into the background (Tk canvas has no real transparency)."""
    c = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    m = [round(b[k] + (c[k] - b[k]) * alpha) for k in range(3)]
    return "#%02x%02x%02x" % tuple(m)


def set_cursor(widget: tk.Widget, *names: str) -> None:
    """Try cursor names in order (some only exist on Windows)."""
    for n in names:
        try:
            widget.configure(cursor=n)
            return
        except tk.TclError:
            continue


def geometry(r: Rect) -> str:
    return f"{r.w}x{r.h}+{r.x}+{r.y}"


class IconCache:
    """Window icons as Tk images, fetched once per window."""

    def __init__(self, root: tk.Misc, backend, size: int):
        self.root = root
        self.be = backend
        self.size = size
        self.blank = tk.PhotoImage(master=root, width=size, height=size)  # keeps rows aligned
        self._icons: dict[int, tk.PhotoImage | None] = {}

    def get(self, hwnd: int) -> tk.PhotoImage | None:
        if hwnd not in self._icons:
            img = None
            try:
                rgba = self.be.window_icon(hwnd, self.size)
                if rgba:
                    data = base64.b64encode(png_bytes(self.size, self.size, rgba)).decode("ascii")
                    img = tk.PhotoImage(master=self.root, data=data, format="png")
            except (OSError, ValueError, tk.TclError):
                img = None
            self._icons[hwnd] = img
        return self._icons[hwnd]

    def prune(self, keep: set[int]) -> None:
        """Forget icons of windows that were closed (hwnds get reused)."""
        for h in list(self._icons):
            if h not in keep:
                del self._icons[h]


class Overlay:
    """Translucent numbered rectangles drawn over the real monitor."""

    def __init__(self, root: tk.Misc):
        self.root = root
        self.wins: list[tk.Toplevel] = []
        self._after = None

    def show(self, layout: Layout, area: Rect, gap: int = 0, ms: int = 1800,
             labels: list[str] | None = None) -> None:
        self.show_many([(layout, area, labels)], gap, ms)

    def show_many(self, screens: list[tuple[Layout, Rect, list[str] | None]], gap: int = 0,
                  ms: int = 1800) -> None:
        """Several layouts at once, e.g. one per monitor: (layout, area, labels)."""
        self.hide()
        for layout, area, labels in screens:
            self._add(layout, area, gap, labels)
        if ms:
            self._after = self.root.after(ms, self.hide)

    def _add(self, layout: Layout, area: Rect, gap: int, labels: list[str] | None) -> None:
        for i, z in enumerate(layout.zones):
            r = z.to_rect(area, gap)
            t = tk.Toplevel(self.root)
            t.overrideredirect(True)
            try:
                t.attributes("-topmost", True)
                t.attributes("-alpha", 0.55)
            except tk.TclError:
                pass
            t.geometry(geometry(r))
            color = zone_color(i)
            f = tk.Frame(t, bg=color, highlightthickness=4, highlightbackground=SELECT)
            f.pack(fill="both", expand=True)
            tk.Label(f, text=str(i + 1), bg=color, fg="white",
                     font=("Segoe UI", max(24, min(r.w, r.h) // 5), "bold")).pack(expand=True)
            if labels and i < len(labels) and labels[i]:
                tk.Label(f, text=labels[i], bg=color, fg="white",
                         font=("Segoe UI", 14)).pack(pady=(0, 30))
            t.bind("<Button-1>", lambda _e: self.hide())
            self.wins.append(t)

    def hide(self) -> None:
        if self._after:
            try:
                self.root.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        for w in self.wins:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self.wins = []
