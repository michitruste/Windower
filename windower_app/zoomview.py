"""
Zoom views: a zone that shows only part of a window.

  * ZoomView   - one borderless window of ours sitting in the zone; DWM draws the
                 chosen area of the source window into it, live and scaled to fit.
                 Drag the picture to pan, Ctrl+wheel to zoom; its title bar moves it
                 and its frame resizes it (it floats until docked again)
  * ZoomViews - keeps one ZoomView per zoom zone, and "peeks": clicking a view
                 moves the real window over it (the chosen area centred on the view)
                 and focuses it; once you switch to another app it goes back.
                 While it's only seen through views, the window is hidden (made
                 invisible and click-through); switching to it (Alt+Tab) peeks it
  * AreaPicker - a dimmed overlay on a window where you drag the area to zoom

The source window is never moved into the zone. It must stay open and not
minimized, since DWM can only show windows it is drawing.
"""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from typing import Callable

from .model import MIN_CROP, Rect, Slot, clamp_crop, fit_aspect, pan_crop, peek_rect, zoom_crop
from .ui_common import ACCENT, FG, MUTED, PANEL, geometry, set_cursor

VIEW_BG = "#101114"
FRAME_BG = "#3a3c45"   # the thin frame around a view (grab it to resize)
TITLE_BG = PANEL
BUTTON_HOVER = "#3a3c45"
TICK_MS = 150          # how often views check their source window (size, minimized, peek)
PEEK_GRACE = 10        # ticks to wait for the peeked window to become the active one
BORDER = 4             # px (x DPI scale): the frame
TITLE = 24             # px (x DPI scale): the title bar
CORNER = 16            # px (x DPI scale): how far along the frame a corner grab reaches
MIN_VIEW = (120, 60)   # px (x DPI scale): smallest picture a resize leaves
DRAG_START = 4         # px the pointer must move before a press on the picture pans (else it peeks)
ZOOM_STEP = 1.15       # zoom per wheel notch
BUTTON_STEP = 1.25     # zoom per click on - / +
WHEEL_PAN = 0.1        # a wheel notch scrolls this much of the visible area


def _app(slot: Slot) -> str:
    return slot.exe[:-4] if slot.exe.lower().endswith(".exe") else (slot.exe or "?")


class ZoomView:
    """One view: a title bar (drag to move, buttons), the picture below it and a thin
    frame around both (drag to resize). Moving or resizing makes the view float off its
    zone until it's docked again (double-click the title bar, or Apply).

    On the picture: click = peek, drag = pan, wheel = scroll (Shift: sideways),
    Ctrl+wheel = zoom around the pointer. Panning and zooming change slot.crop.
    """

    def __init__(self, owner: "ZoomViews", key: tuple[int, int], slot: Slot, rect: Rect, area: Rect):
        self.owner = owner
        self.key = key
        self.slot = slot
        self.zone_rect = rect              # where its zone is
        self.floating: Rect | None = None  # moved/resized by the user: where it is instead
        self.rect = rect                   # where the view is now
        self.area = area                   # work area of the zone's monitor
        if slot.home is None and slot.crop:
            slot.home = slot.crop
        self._state: tuple | None = None
        self._text: str | None = None
        self._title: str | None = None
        self._drag: dict | None = None
        be, sc = owner.be, owner.scale
        self.border = max(2, round(BORDER * sc))
        self.title_h = round(TITLE * sc)
        t = self.win = tk.Toplevel(owner.root)
        t.withdraw()
        t.overrideredirect(True)
        t.configure(bg=FRAME_BG)
        inner = tk.Frame(t, bg=VIEW_BG)
        inner.pack(fill="both", expand=True, padx=self.border, pady=self.border)
        bar = self.bar = tk.Frame(inner, bg=TITLE_BG, height=self.title_h, cursor="fleur")
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        font = ("Segoe UI", 9)
        self.buttons: dict[str, tk.Label] = {}
        for name, text, cmd in (("clear", "✕", lambda: owner.on_clear(self.key)),
                                ("menu", "≡", self._menu_button),
                                ("fit", "⤢", self.fit),
                                ("in", "+", lambda: self.zoom_by(BUTTON_STEP)),
                                ("out", "−", lambda: self.zoom_by(1 / BUTTON_STEP))):
            b = tk.Label(bar, text=text, bg=TITLE_BG, fg=MUTED, font=font, cursor="hand2", width=3)
            b.pack(side="right", fill="y")
            b.bind("<ButtonRelease-1>", lambda _e, c=cmd: c())
            b.bind("<Enter>", lambda _e, w=b: w.configure(bg=BUTTON_HOVER, fg=FG))
            b.bind("<Leave>", lambda _e, w=b: w.configure(bg=TITLE_BG, fg=MUTED))
            self.buttons[name] = b
        self.icon_img = owner.icon(slot.hwnd) if owner.icon else None
        self.name = tk.Label(bar, bg=TITLE_BG, fg=FG, font=font, anchor="w", cursor="fleur",
                             image=self.icon_img or "", compound="left", padx=6)
        self.name.pack(side="left", fill="both", expand=True)
        for w in (bar, self.name):
            w.bind("<ButtonPress-1>", lambda e: self._frame_press(e, ""))
            w.bind("<B1-Motion>", self._frame_motion)
            w.bind("<ButtonRelease-1>", self._frame_release)
            w.bind("<Double-Button-1>", lambda _e: self.dock())
            w.bind("<Button-3>", lambda e: owner.on_menu(self.key, e.x_root, e.y_root))
        lb = self.label = tk.Label(inner, bg=VIEW_BG, fg=MUTED, font=("Segoe UI", 10), justify="center",
                                   cursor="hand2")
        lb.pack(fill="both", expand=True)
        lb.bind("<ButtonPress-1>", self._pic_press)
        lb.bind("<B1-Motion>", self._pic_motion)
        lb.bind("<ButtonRelease-1>", self._pic_release)
        lb.bind("<Button-3>", lambda e: owner.on_menu(self.key, e.x_root, e.y_root))
        # the frame: only there is the toplevel itself under the pointer (its children cover the rest)
        t.bind("<Motion>", self._frame_hover)
        t.bind("<ButtonPress-1>", lambda e: self._frame_press(e, self._edges(e)) if e.widget is t else None)
        t.bind("<B1-Motion>", lambda e: self._frame_motion(e) if e.widget is t else None)
        t.bind("<ButtonRelease-1>", lambda e: self._frame_release(e) if e.widget is t else None)
        t.bind("<MouseWheel>", self._wheel)        # a toplevel binding fires for all of the view
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

    # ------------------------------------------------------------ placement
    def update(self, rect: Rect, area: Rect) -> None:
        self.area = area
        self.zone_rect = rect
        if self.floating is None and rect != self.rect:
            self._move(rect)
        if self._topmost != self.slot.topmost:
            self.lift()
        self.refresh()

    def dock(self) -> None:
        """Back into its zone."""
        self.floating = None
        if self.rect != self.zone_rect:
            self._move(self.zone_rect)
            self.refresh()

    def _move(self, rect: Rect) -> None:
        self.rect = rect
        self.win.geometry(geometry(rect))

    def content(self) -> Rect:
        """Where the picture goes, in the view's own coordinates (below the title bar)."""
        b = self.border
        return Rect(b, b + self.title_h, max(1, self.rect.w - 2 * b), max(1, self.rect.h - 2 * b - self.title_h))

    def screen_content(self) -> Rect:
        c = self.content()
        return Rect(self.rect.x + c.x, self.rect.y + c.y, c.w, c.h)

    # --------------------------------------------------------------- picture
    def _crop_now(self) -> tuple[Rect, int, int] | None:
        """(the crop as it can be shown, client width, client height), or None."""
        be, s = self.owner.be, self.slot
        if not s.crop or not be.is_window(s.hwnd) or be.is_minimized(s.hwnd):
            return None
        c = be.client_rect(s.hwnd)
        crop = clamp_crop(s.crop, c.w, c.h) if c.w > 0 and c.h > 0 else None
        return (crop, c.w, c.h) if crop else None

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
                self.thumb.show(fit_aspect(self.content(), crop.w, crop.h), crop)
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
            self.label.configure(text=text, wraplength=max(60, self.content().w - 20))
        title = _app(s)
        shown = crop or s.crop
        if shown:
            title += f"  ·  {self.factor(shown):.1f}x"
        if title != self._title:
            self._title = title
            self.name.configure(text=title)

    def factor(self, crop: Rect) -> float:
        """How much the picture is enlarged (screen px per window px)."""
        return fit_aspect(self.content(), crop.w, crop.h).w / crop.w

    def _set_crop(self, crop: Rect) -> None:
        if crop != self.slot.crop:
            self.slot.crop = crop
            self.refresh()
            self.owner.on_crop(self.key)

    def zoom_by(self, factor: float, fx: float = 0.5, fy: float = 0.5) -> None:
        """Zoom in (factor > 1) or out around the point at fractions (fx, fy) of the picture."""
        now = self._crop_now()
        if not now:
            return
        crop, w, h = now
        home = self.slot.home or crop
        self._set_crop(zoom_crop(crop, factor, fx, fy, w, h, home.w / home.h))

    def fit(self) -> None:
        """Back to the area that was picked."""
        if self.slot.home:
            self._set_crop(self.slot.home)

    def _pic_press(self, e) -> None:
        self._drag = {"x": e.x_root, "y": e.y_root, "crop": self.slot.crop, "panning": False}

    def _pic_motion(self, e) -> None:
        d = self._drag
        if not d or "crop" not in d:
            return
        dx, dy = e.x_root - d["x"], e.y_root - d["y"]
        if not d["panning"]:
            if abs(dx) < DRAG_START and abs(dy) < DRAG_START:
                return
            d["panning"] = True
            self.label.configure(cursor="fleur")
        now = self._crop_now()
        if not now or not d["crop"]:
            return
        start = d["crop"]                          # always from where the drag began: no drift
        k = 1 / self.factor(start)                 # window px per screen px
        self._set_crop(pan_crop(start, -dx * k, -dy * k, now[1], now[2]))

    def _pic_release(self, _e) -> None:
        d, self._drag = self._drag, None
        if not d or "crop" not in d:
            return
        if d["panning"]:
            self.label.configure(cursor="hand2")
        else:
            self.owner.peek(self.key)

    def _wheel(self, e) -> None:
        now = self._crop_now()
        if not now or not e.delta:
            return
        crop, w, h = now
        notches = e.delta / 120
        if e.state & 0x4:                          # Ctrl: zoom around the pointer
            dest = fit_aspect(self.content(), crop.w, crop.h)
            px, py = e.x_root - self.rect.x - dest.x, e.y_root - self.rect.y - dest.y
            self.zoom_by(ZOOM_STEP ** notches, min(max(px / dest.w, 0.0), 1.0), min(max(py / dest.h, 0.0), 1.0))
        elif e.state & 0x1:                        # Shift: sideways
            self._set_crop(pan_crop(crop, -notches * crop.w * WHEEL_PAN, 0, w, h))
        else:
            self._set_crop(pan_crop(crop, 0, -notches * crop.h * WHEEL_PAN, w, h))

    # ------------------------------------------------- title bar and frame
    def _edges(self, e) -> str:
        """Which sides of the frame the pointer is on ("" = none); corners are generous."""
        x, y, w, h, b = e.x_root - self.rect.x, e.y_root - self.rect.y, self.rect.w, self.rect.h, self.border
        c = max(b, round(CORNER * self.owner.scale))
        side = x < c or x >= w - c
        ns = "n" if y < b or (y < c and side) else "s" if y >= h - b or (y >= h - c and side) else ""
        we = "w" if x < b or (x < c and ns) else "e" if x >= w - b or (x >= w - c and ns) else ""
        return ns + we

    def _frame_hover(self, e) -> None:
        if e.widget is not self.win or self._drag:
            return
        edges = self._edges(e)
        if edges in ("n", "s"):
            set_cursor(self.win, "sb_v_double_arrow")
        elif edges in ("w", "e"):
            set_cursor(self.win, "sb_h_double_arrow")
        elif edges in ("nw", "se"):
            set_cursor(self.win, "size_nw_se", "bottom_right_corner")
        elif edges:
            set_cursor(self.win, "size_ne_sw", "bottom_left_corner")
        else:
            set_cursor(self.win, "")

    def _frame_press(self, e, edges: str) -> None:
        self._drag = {"x": e.x_root, "y": e.y_root, "rect": self.rect, "edges": edges}

    def _frame_motion(self, e) -> None:
        d = self._drag
        if not d or "rect" not in d:
            return
        dx, dy, r, ed = e.x_root - d["x"], e.y_root - d["y"], d["rect"], d["edges"]
        x1, y1, x2, y2 = r.x, r.y, r.x + r.w, r.y + r.h
        if not ed:                                 # the title bar: move
            x1, x2, y1, y2 = x1 + dx, x2 + dx, y1 + dy, y2 + dy
        else:                                      # the frame: resize
            mw = round(MIN_VIEW[0] * self.owner.scale)
            mh = round(MIN_VIEW[1] * self.owner.scale) + self.title_h + 2 * self.border
            if "w" in ed:
                x1 = min(x1 + dx, x2 - mw)
            if "e" in ed:
                x2 = max(x2 + dx, x1 + mw)
            if "n" in ed:
                y1 = min(y1 + dy, y2 - mh)
            if "s" in ed:
                y2 = max(y2 + dy, y1 + mh)
        new = Rect(x1, y1, x2 - x1, y2 - y1)
        if new != self.rect:
            self.floating = new
            self._move(new)
            self.refresh()

    def _frame_release(self, _e) -> None:
        if self._drag and "rect" in self._drag:
            self._drag = None

    def _menu_button(self) -> None:
        b = self.buttons["menu"]
        self.owner.on_menu(self.key, b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

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
    on_clear(key)                 - the view's close button
    on_crop(key)                  - the view was panned or zoomed (slot.crop changed)
    icon(hwnd)                    - a Tk image for the title bar, or None
    """

    def __init__(self, root: tk.Misc, backend, on_menu: Callable[[tuple[int, int], int, int], None],
                 is_tiled: Callable[[int], bool], journal: Path | None = None,
                 on_clear: Callable[[tuple[int, int]], None] = lambda _k: None,
                 on_crop: Callable[[tuple[int, int]], None] = lambda _k: None,
                 icon: Callable[[int], object] | None = None, scale: float = 1.0):
        self.root = root
        self.be = backend
        self.on_menu = on_menu
        self.is_tiled = is_tiled
        self.on_clear = on_clear
        self.on_crop = on_crop
        self.icon = icon
        self.scale = scale
        self.areas: list[Rect] = []              # every monitor's work area (for floated views)
        self.views: dict[tuple[int, int], ZoomView] = {}
        self._peek: dict | None = None
        # source windows made invisible + click-through while they're only seen through views
        self.hide_sources = True
        self.hidden: dict[int, object] = {}      # hwnd -> what the backend needs to undo it
        self.exempt: set[int] = set()            # never hide these (e.g. while picking an area)
        self.journal = journal                   # hidden windows, to undo it after a crash
        self._last_fg = backend.foreground()
        self._after = root.after(TICK_MS, self._tick)

    def sync(self, want: dict[tuple[int, int], tuple[Slot, Rect, Rect]], areas: list[Rect] | None = None) -> None:
        """want = {(monitor, zone): (slot, rect, monitor work area)}; every other view is removed.
        A view the user moved stays where it is (see dock)."""
        if areas is not None:
            self.areas = list(areas)
        for key in list(self.views):
            if key not in want or want[key][0] is not self.views[key].slot:
                self.views.pop(key).destroy()
        for key, (slot, rect, area) in want.items():
            v = self.views.get(key)
            if v is None:
                self.views[key] = ZoomView(self, key, slot, rect, area)
            else:
                v.update(rect, area)
        self.sync_hidden()

    # ---------------------------------------------------------------- hiding
    def sync_hidden(self) -> None:
        """Hide the windows shown only through views (not tiled, not peeked); un-hide the rest."""
        be = self.be
        want = set()
        if self.hide_sources:
            want = {v.slot.hwnd for v in self.views.values()
                    if be.is_window(v.slot.hwnd) and v.slot.hwnd not in self.exempt}
            want -= {self.peeking}
            want = {h for h in want if not self.is_tiled(h)}
        changed = False
        for h in [h for h in self.hidden if h not in want]:
            be.unghost(h, self.hidden.pop(h))
            changed = True
        for h in want - set(self.hidden):
            state = be.ghost(h)
            if state is not None:
                self.hidden[h] = state
                changed = True
        if changed:
            self._last_fg = be.foreground()   # hiding the active window mustn't count as switching to it
            self._save_journal()

    def unhide_all(self) -> None:
        for h, state in list(self.hidden.items()):
            self.be.unghost(h, state)
        self.hidden = {}
        self._save_journal()

    def recover(self) -> None:
        """Un-hide windows a previous run left hidden (it crashed or was killed)."""
        if not self.journal:
            return
        try:
            data = json.loads(self.journal.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for h, state in data.items():
            try:
                self.be.unghost(int(h), state)
            except (OSError, TypeError, ValueError):
                pass
        self._save_journal()

    def _save_journal(self) -> None:
        if not self.journal:
            return
        try:
            if self.hidden:
                self.journal.write_text(json.dumps({str(h): s for h, s in self.hidden.items()}), encoding="utf-8")
            elif self.journal.exists():
                self.journal.unlink()
        except OSError:
            pass

    def _check_switch(self) -> None:
        """Switching to a hidden window (Alt+Tab, taskbar) peeks it, so you can see what you use."""
        fg = self.be.foreground()
        if fg == self._last_fg:
            return
        self._last_fg = fg
        h = self.be.root_window(fg) if fg else 0
        if h in self.hidden and h != self.peeking and h not in self.exempt:
            key = next((k for k, v in self.views.items() if v.slot.hwnd == h), None)
            if key is not None:
                self.peek(key)

    def on_monitor(self, m: int) -> bool:
        return any(k[0] == m for k in self.views)

    def dock(self, only: set[int] | None = None, key: tuple[int, int] | None = None) -> None:
        """Put moved views back into their zones (all, those of the monitors in `only`, or one)."""
        for k, v in self.views.items():
            if (key is None or k == key) and (only is None or k[0] in only):
                v.dock()

    def floating(self, key: tuple[int, int]) -> bool:
        v = self.views.get(key)
        return bool(v and v.floating)

    def _area_of(self, v: ZoomView) -> Rect:
        """The work area a view is on (a moved one may be on another monitor)."""
        if v.floating:
            cx, cy = v.rect.x + v.rect.w // 2, v.rect.y + v.rect.h // 2
            for a in self.areas:
                if a.x <= cx < a.x + a.w and a.y <= cy < a.y + a.h:
                    return a
        return v.area

    def lift_all(self) -> None:
        for v in self.views.values():
            v.lift()

    def close_all(self) -> None:
        self.end_peek()
        self.unhide_all()
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
            self.sync_hidden()           # a hidden window shows while it's peeked
        client = be.client_rect(hwnd)
        crop = clamp_crop(v.slot.crop, client.w, client.h) if v.slot.crop else None
        crop = crop or Rect(0, 0, client.w, client.h)
        be.place(hwnd, peek_rect(be.get_rect(hwnd), client, crop, v.screen_content(), self._area_of(v)))
        be.focus(hwnd)

    def end_peek(self) -> None:
        """Put the peeked window back where it was and hide it again (else send it behind everything)."""
        p, self._peek = self._peek, None
        if p and self.be.is_window(p["hwnd"]) and not self.be.is_minimized(p["hwnd"]):
            self.be.place(p["hwnd"], p["back"])
            self.sync_hidden()
            if p["hwnd"] not in self.hidden:
                self.be.send_to_back(p["hwnd"])
        elif p:
            self.sync_hidden()

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
            self.sync_hidden()
            self._check_switch()
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
