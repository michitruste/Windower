"""
Things Windower draws directly on the desktop (outside its panel):

  * SnapOverlay     - the zones that appear while you Shift-drag a window
  * DesktopHandles  - small grips on the lines between tiled windows and on
                      their intersections (nodes); dragging one resizes every
                      window touching that line / point at the same time
"""
from __future__ import annotations

import sys
import tkinter as tk
from typing import Callable

from .model import Divider, Rect, Zone, dividers, edge_coord, edge_span, node_edges, nodes
from .ui_common import ACCENT, SELECT, geometry, zone_color

IDLE_ZONE = "#2a2c33"


class SnapOverlay:
    def __init__(self, root: tk.Misc, backend):
        self.root = root
        self.be = backend
        self.wins: list[tuple[tk.Toplevel, tk.Frame, tk.Label]] = []
        self.rects: list[Rect] = []
        self.current: int | None = None

    @property
    def visible(self) -> bool:
        return bool(self.wins)

    def show(self, rects: list[Rect]) -> None:
        self.hide()
        self.rects = rects
        for i, r in enumerate(rects):
            t = tk.Toplevel(self.root)
            t.overrideredirect(True)
            try:
                t.attributes("-topmost", True)
                t.attributes("-alpha", 0.5)
            except tk.TclError:
                pass
            t.geometry(geometry(r))
            f = tk.Frame(t, bg=IDLE_ZONE, highlightthickness=3, highlightbackground=zone_color(i))
            f.pack(fill="both", expand=True)
            lbl = tk.Label(f, text=str(i + 1), bg=IDLE_ZONE, fg="white",
                           font=("Segoe UI", max(20, min(r.w, r.h) // 6), "bold"))
            lbl.pack(expand=True)
            t.update_idletasks()
            try:
                self.be.style_overlay(int(t.winfo_id()), click_through=True)
            except Exception:
                pass
            self.wins.append((t, f, lbl))
        self.current = None

    def zone_at(self, x: int, y: int) -> int | None:
        hit = None
        for i, r in enumerate(self.rects):       # last one wins (overlapping zones)
            if r.x <= x < r.x + r.w and r.y <= y < r.y + r.h:
                hit = i
        return hit

    def highlight(self, i: int | None) -> None:
        if i == self.current:
            return
        self.current = i
        for k, (_t, f, lbl) in enumerate(self.wins):
            bg = zone_color(k) if k == i else IDLE_ZONE
            f.configure(bg=bg, highlightbackground=SELECT if k == i else zone_color(k))
            lbl.configure(bg=bg)

    def hide(self) -> None:
        for t, _f, _l in self.wins:
            try:
                t.destroy()
            except tk.TclError:
                pass
        self.wins, self.rects, self.current = [], [], None


class _Handle:
    """One grip window. kind = 'v' | 'h' (divider) or 'node'."""

    def __init__(self, owner: "DesktopHandles", kind: str, edges_v, edges_h, color: str):
        self.owner = owner
        self.kind = kind
        self.edges_v = edges_v
        self.edges_h = edges_h
        s = owner.ui
        if kind == "node":
            self.w = self.h = int(20 * s)
        elif kind == "v":
            self.w, self.h = int(10 * s), int(56 * s)
        else:
            self.w, self.h = int(56 * s), int(10 * s)
        t = self.win = tk.Toplevel(owner.root)
        t.withdraw()                      # shown by place_at() once it has a position
        self.shown = False
        t.overrideredirect(True)
        key = "#010203"
        c = tk.Canvas(t, width=self.w, height=self.h, highlightthickness=0, bg=key)
        c.pack()
        try:
            t.attributes("-topmost", True)
            if sys.platform == "win32":
                t.attributes("-transparentcolor", key)
        except tk.TclError:
            c.configure(bg=color)
        if kind == "node":
            c.create_oval(1, 1, self.w - 2, self.h - 2, fill=color, outline=SELECT, width=2)
            c.configure(cursor="fleur")
        else:
            r = min(self.w, self.h) / 2
            # rounded pill = two circles + a rectangle
            if kind == "v":
                c.create_oval(0, 0, self.w - 1, 2 * r, fill=color, outline=color)
                c.create_oval(0, self.h - 2 * r - 1, self.w - 1, self.h - 1, fill=color, outline=color)
                c.create_rectangle(0, r, self.w - 1, self.h - r, fill=color, outline=color)
                c.configure(cursor="sb_h_double_arrow")
            else:
                c.create_oval(0, 0, 2 * r, self.h - 1, fill=color, outline=color)
                c.create_oval(self.w - 2 * r - 1, 0, self.w - 1, self.h - 1, fill=color, outline=color)
                c.create_rectangle(r, 0, self.w - r, self.h - 1, fill=color, outline=color)
                c.configure(cursor="sb_v_double_arrow")
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._motion)
        c.bind("<ButtonRelease-1>", self._release)

    def _press(self, e):
        self.owner.dragging = self
        self.owner.on_drag(self.edges_v, self.edges_h, e.x_root, e.y_root, False)

    def _motion(self, e):
        self.owner.on_drag(self.edges_v, self.edges_h, e.x_root, e.y_root, False)

    def _release(self, e):
        self.owner.dragging = None
        self.owner.on_drag(self.edges_v, self.edges_h, e.x_root, e.y_root, True)

    def place_at(self, cx: float, cy: float) -> None:
        self.win.geometry(f"+{round(cx - self.w / 2)}+{round(cy - self.h / 2)}")
        if not self.shown:
            self.shown = True
            self.win.deiconify()
            self.win.update_idletasks()
            try:   # clicking a grip must not steal focus from the app you're using
                self.owner.be.style_overlay(int(self.win.winfo_id()), click_through=False)
            except Exception:
                pass

    def destroy(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class DesktopHandles:
    """
    on_drag(edges_v, edges_h, x_root, y_root, finished) is called while a grip is
    dragged; the app moves the zones/windows and then calls reposition().
    """

    def __init__(self, root: tk.Misc, backend,
                 on_drag: Callable[[list, list, int, int, bool], None]):
        self.root = root
        self.be = backend
        self.on_drag = on_drag
        self.ui = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self.handles: list[_Handle] = []
        self.dragging: _Handle | None = None
        self.area: Rect | None = None

    @property
    def visible(self) -> bool:
        return bool(self.handles)

    def show(self, zones: list[Zone], area: Rect) -> None:
        if self.dragging:
            return
        self.hide()
        self.area = area
        divs = dividers(zones)
        for d in divs:
            color = ACCENT
            h = _Handle(self, d.axis, d.edges if d.axis == "v" else [], d.edges if d.axis == "h" else [], color)
            self.handles.append(h)
        for n in nodes(zones, divs):
            v, hh = node_edges(n)
            self.handles.append(_Handle(self, "node", v, hh, "#f1b44c"))
        self.reposition(zones)

    def reposition(self, zones: list[Zone]) -> None:
        a = self.area
        if not a:
            return
        for h in self.handles:
            if h.kind == "node":
                x = edge_coord(zones[h.edges_v[0][0]], h.edges_v[0][1])
                y = edge_coord(zones[h.edges_h[0][0]], h.edges_h[0][1])
            else:
                d = _span(zones, h.edges_v or h.edges_h)
                c = edge_coord(zones[d.edges[0][0]], d.edges[0][1])
                mid = (d.span[0] + d.span[1]) / 2
                x, y = (c, mid) if h.kind == "v" else (mid, c)
            h.place_at(a.x + x * a.w, a.y + y * a.h)

    def lift(self) -> None:
        for h in self.handles:
            try:
                h.win.lift()
                h.win.attributes("-topmost", True)
            except tk.TclError:
                pass

    def hide(self) -> None:
        for h in self.handles:
            h.destroy()
        self.handles = []
        self.dragging = None


def _span(zones: list[Zone], edges: list[tuple[int, str]]) -> Divider:
    lo = min(edge_span(zones[i], s)[0] for i, s in edges)
    hi = max(edge_span(zones[i], s)[1] for i, s in edges)
    i, s = edges[0]
    return Divider("v" if s in "LR" else "h", edge_coord(zones[i], s), edges, (lo, hi))
