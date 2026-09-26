"""
Zoom views: a zone that shows only part of a window.

  * ZoomView   - one borderless window of ours sitting in the zone; DWM draws the
                 chosen area of the source window into it, live and scaled to fit
  * ZoomViews  - keeps one ZoomView per zoom zone, and "peeks": clicking a view
                 moves the real window over it (the chosen area centred on the view)
                 and focuses it; once you switch to another app it goes back
  * AreaPicker - a dimmed overlay on a window where you drag the area to zoom

The source window is never moved into the zone. It must stay open and not
minimized, since DWM can only show windows it is drawing.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from .model import MIN_CROP, Rect, Slot, clamp_crop, fit_aspect, peek_rect
from .ui_common import ACCENT, FG, MUTED, geometry

VIEW_BG = "#101114"
TICK_MS = 150          # how often views check their source window (size, minimized, peek)
PEEK_GRACE = 10        # ticks to wait for the peeked window to become the active one


def _app(slot: Slot) -> str:
    return slot.exe[:-4] if slot.exe.lower().endswith(".exe") else (slot.exe or "?")


class ZoomView:
    def __init__(self, owner: "ZoomViews", key: tuple[int, int], slot: Slot, rect: Rect, area: Rect):
        self.owner = owner
        self.key = key
        self.slot = slot
        self.rect = rect
        self.area = area                  # work area of the view's monitor (peeks stay on it)
        self._state: tuple | None = None
        self._text: str | None = None
        be = owner.be
        t = self.win = tk.Toplevel(owner.root)
        t.withdraw()
        t.overrideredirect(True)
        t.configure(bg=VIEW_BG, cursor="hand2")
        self.label = tk.Label(t, bg=VIEW_BG, fg=MUTED, font=("Segoe UI", 10), justify="center")
        self.label.pack(fill="both", expand=True)
        for w in (t, self.label):
            w.bind("<ButtonPress-1>", lambda _e: owner.peek(self.key))
            w.bind("<Button-3>", lambda e: owner.on_menu(self.key, e.x_root, e.y_root))
        t.geometry(geometry(rect))
        t.deiconify()
        t.update_idletasks()
        try:   # clicking a view must not activate Windower; keeps it out of Alt+Tab
            be.style_overlay(int(t.winfo_id()), click_through=False)
        except Exception:
            pass
        self.thumb = None
        if getattr(be, "HAS_THUMBNAILS", False):
            try:
                self.thumb = be.Thumbnail(int(t.winfo_id()), slot.hwnd)
            except OSError:
                self.thumb = None
        self._topmost = None
        self.lift()
        self.refresh()

    def update(self, rect: Rect, area: Rect) -> None:
        self.area = area
        if rect != self.rect:
            self.rect = rect
            self.win.geometry(geometry(rect))
        if self._topmost != self.slot.topmost:
            self.lift()
        self.refresh()

    def refresh(self) -> None:
        """Re-fit the picture if the source or the view changed; explain when there's none."""
        s, be = self.slot, self.owner.be
        alive = be.is_window(s.hwnd)
        minimized = alive and be.is_minimized(s.hwnd)
        size = self.thumb.source_size() if self.thumb and alive and not minimized else None
        crop = clamp_crop(s.crop, *size) if size and s.crop else None
        state = (self.rect, crop)
        if state != self._state:
            if crop:
                self.thumb.show(fit_aspect(Rect(0, 0, self.rect.w, self.rect.h), crop.w, crop.h), crop)
            elif self.thumb:
                self.thumb.hide()
            self._state = state
        if crop:
            text = ""
        elif not alive:
            text = f"{_app(s)} was closed"
        elif minimized:
            text = f"{_app(s)} is minimized\nclick to bring it back"
        elif not self.thumb:
            c = s.crop
            text = (f"Zoom of {_app(s)}\n{c.w} x {c.h} area at ({c.x}, {c.y})\n"
                    f"(the live picture needs Windows)") if c else _app(s)
        elif size:
            text = f"The zoomed area is outside {_app(s)}'s window now.\nRight-click > Change zoom area"
        else:
            text = f"{_app(s)} can't be shown"
        if text != self._text:
            self._text = text
            self.label.configure(text=text, wraplength=max(60, self.rect.w - 20))

    def lift(self) -> None:
        self._topmost = self.slot.topmost
        try:
            self.win.attributes("-topmost", bool(self.slot.topmost))
            self.win.lift()
        except tk.TclError:
            pass

    def destroy(self) -> None:
        if self.thumb:
            try:
                self.thumb.close()
            except OSError:
                pass
            self.thumb = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class ZoomViews:
    """
    on_menu(key, x_root, y_root)  - right-click on a view (key = (monitor, zone))
    is_tiled(hwnd)                - the window also sits in a zone of its own: clicking
                                    a view of it just focuses it instead of peeking
    """

    def __init__(self, root: tk.Misc, backend, on_menu: Callable[[tuple[int, int], int, int], None],
                 is_tiled: Callable[[int], bool]):
        self.root = root
        self.be = backend
        self.on_menu = on_menu
        self.is_tiled = is_tiled
        self.views: dict[tuple[int, int], ZoomView] = {}
        self._peek: dict | None = None
        self._after = root.after(TICK_MS, self._tick)

    def sync(self, want: dict[tuple[int, int], tuple[Slot, Rect, Rect]]) -> None:
        """want = {(monitor, zone): (slot, rect, monitor work area)}; every other view is removed."""
        for key in list(self.views):
            if key not in want or want[key][0] is not self.views[key].slot:
                self.views.pop(key).destroy()
        for key, (slot, rect, area) in want.items():
            v = self.views.get(key)
            if v is None:
                self.views[key] = ZoomView(self, key, slot, rect, area)
            else:
                v.update(rect, area)

    def on_monitor(self, m: int) -> bool:
        return any(k[0] == m for k in self.views)

    def lift_all(self) -> None:
        for v in self.views.values():
            v.lift()

    def close_all(self) -> None:
        self.end_peek()
        for v in self.views.values():
            v.destroy()
        self.views = {}
        try:
            self.root.after_cancel(self._after)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ peek
    @property
    def peeking(self) -> int:
        return self._peek["hwnd"] if self._peek else 0

    def peek(self, key: tuple[int, int]) -> None:
        """Bring the real window over the view, the zoomed area centred on it, to use it."""
        v = self.views.get(key)
        be = self.be
        if not v or not be.is_window(v.slot.hwnd):
            return
        hwnd = v.slot.hwnd
        if self._peek and self._peek["hwnd"] != hwnd:
            self.end_peek()
        if self.is_tiled(hwnd):          # already visible in its own zone
            be.focus(hwnd)
            return
        if self._peek is None:
            be.unminimize(hwnd)
            self._peek = {"hwnd": hwnd, "back": be.get_rect(hwnd), "seen": False, "wait": PEEK_GRACE}
        client = be.client_rect(hwnd)
        crop = clamp_crop(v.slot.crop, client.w, client.h) if v.slot.crop else None
        crop = crop or Rect(0, 0, client.w, client.h)
        be.place(hwnd, peek_rect(be.get_rect(hwnd), client, crop, v.rect, v.area))
        be.focus(hwnd)

    def end_peek(self) -> None:
        """Put the peeked window back where it was, behind everything."""
        p, self._peek = self._peek, None
        if p and self.be.is_window(p["hwnd"]) and not self.be.is_minimized(p["hwnd"]):
            self.be.place(p["hwnd"], p["back"])
            self.be.send_to_back(p["hwnd"])

    def _check_peek(self) -> None:
        p, be = self._peek, self.be
        if not be.is_window(p["hwnd"]):
            self._peek = None
            return
        fg = be.foreground()
        if fg and be.get_pid(fg) == be.get_pid(p["hwnd"]):   # its menus/dialogs count as the app
            p["seen"] = True
            return
        if be.mouse_button_down():       # e.g. still dragging it
            return
        p["wait"] -= 1
        if p["seen"] or p["wait"] <= 0:
            self.end_peek()

    def _tick(self) -> None:
        try:
            if self._peek:
                self._check_peek()
            for v in list(self.views.values()):
                v.refresh()
        except tk.TclError:
            pass
        finally:
            self._after = self.root.after(TICK_MS, self._tick)


class AreaPicker:
    """Dims a window's client area; drag a rectangle over the part you want to zoom.

    on_done(rect) gets the rectangle in the window's client coordinates, or None
    if cancelled (Esc or right-click).
    """

    DIM = "#0b0c10"
    HOLE = "#ff00fe"      # transparent colour: the dragged area shows the window undimmed

    def __init__(self, root: tk.Misc, backend, hwnd: int, on_done: Callable[[Rect | None], None],
                 current: Rect | None = None):
        self.on_done = on_done
        self.area = backend.client_rect(hwnd)
        self._start: tuple[int, int] | None = None
        t = self.win = tk.Toplevel(root)
        t.overrideredirect(True)
        t.geometry(geometry(self.area))
        try:
            t.attributes("-topmost", True)
            t.attributes("-alpha", 0.6)
            t.attributes("-transparentcolor", self.HOLE)
        except tk.TclError:
            pass
        c = self.canvas = tk.Canvas(t, bg=self.DIM, highlightthickness=0, cursor="crosshair")
        c.pack(fill="both", expand=True)
        if current:
            c.create_rectangle(current.x, current.y, current.x + current.w, current.y + current.h,
                               outline=MUTED, dash=(6, 4), width=2)
        hint = c.create_text(self.area.w / 2, 16, anchor="n", fill=FG, font=("Segoe UI", 12, "bold"),
                             text="Drag over the part of this window you want to see.   Esc cancels")
        x1, y1, x2, y2 = c.bbox(hint)
        c.tag_lower(c.create_rectangle(x1 - 10, y1 - 6, x2 + 10, y2 + 6, fill="#26282f", width=0), hint)
        self.rect_id = c.create_rectangle(0, 0, 0, 0, outline=ACCENT, width=2, fill=self.HOLE, state="hidden")
        self.size_id = c.create_text(0, 0, anchor="sw", fill=FG, font=("Segoe UI", 10, "bold"), state="hidden")
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._motion)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Button-3>", lambda _e: self._finish(None))
        t.bind("<Escape>", lambda _e: self._finish(None))
        t.update_idletasks()
        t.lift()
        t.focus_force()

    def _press(self, e) -> None:
        self._start = (e.x, e.y)
        self._motion(e)

    def _box(self, e) -> Rect:
        (sx, sy), ex, ey = self._start, min(max(e.x, 0), self.area.w), min(max(e.y, 0), self.area.h)
        return Rect(min(sx, ex), min(sy, ey), abs(ex - sx), abs(ey - sy))

    def _motion(self, e) -> None:
        if not self._start:
            return
        r = self._box(e)
        c = self.canvas
        c.coords(self.rect_id, r.x, r.y, r.x + r.w, r.y + r.h)
        c.itemconfigure(self.rect_id, state="normal")
        c.coords(self.size_id, r.x + 2, max(r.y - 4, 14))
        c.itemconfigure(self.size_id, text=f"{r.w} x {r.h}", state="normal")

    def _release(self, e) -> None:
        if not self._start:
            return
        r = self._box(e)
        self._start = None
        if r.w >= MIN_CROP and r.h >= MIN_CROP:
            self._finish(r)
        else:                            # a click, not a drag: try again
            self.canvas.itemconfigure(self.rect_id, state="hidden")
            self.canvas.itemconfigure(self.size_id, state="hidden")

    def _finish(self, rect: Rect | None) -> None:
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.on_done(rect)
