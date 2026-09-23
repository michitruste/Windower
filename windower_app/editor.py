"""
Custom layout editor.

  * drag on empty space ........ draw a new zone
  * drag inside a zone ......... move it
  * drag a zone's edge/corner .. resize it
  * right-click a zone ......... delete it
  * V / H keys (or buttons) .... split the selected zone left|right / top-bottom
  * Delete key ................. delete the selected zone
Edges snap to the grid and to the edges of the other zones.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from .model import Layout, Monitor, Zone
from .ui_common import (ACCENT, BG, CANVAS_BG, FG, MUTED, PANEL, SELECT, Overlay,
                        blend, set_cursor, zone_color)

SNAP_CHOICES = {"Off": 0, "1/2": 2, "1/3": 3, "1/4": 4, "1/6": 6, "1/8": 8, "1/12": 12, "1/24": 24}
EDGE_PX = 8
MIN_FRAC = 0.04
EDGE_SNAP = 0.012


class LayoutEditor(tk.Toplevel):
    def __init__(self, master: tk.Misc, monitor: Monitor, start: Layout,
                 templates: list[Layout], existing_names: set[str],
                 on_save: Callable[[Layout], None]):
        super().__init__(master)
        self.title("Windower - Layout editor")
        self.configure(bg=BG)
        self.monitor = monitor
        self.templates = templates
        self.existing_names = existing_names
        self.on_save = on_save
        self.overlay = Overlay(self)

        self.zones: list[Zone] = [Zone(z.x, z.y, z.w, z.h) for z in start.zones]
        self.selected: int | None = 0 if self.zones else None
        self._drag: dict | None = None
        self._undo: list[list[Zone]] = []

        area = monitor.work
        ui = max(1.0, self.winfo_fpixels("1i") / 96.0)  # high-DPI screens
        max_w = min(760 * ui, self.winfo_screenwidth() * 0.62)
        max_h = min(520 * ui, self.winfo_screenheight() * 0.62)
        self.cw = round(max_w)
        self.ch = max(150, round(self.cw * area.h / area.w))
        if self.ch > max_h:
            self.ch = round(max_h)
            self.cw = round(self.ch * area.w / area.h)

        default_name = start.name if not start.builtin else f"My {start.name}"
        self.name_var = tk.StringVar(value=default_name)
        self.snap_var = tk.StringVar(value="1/12")
        self.field_vars = {k: tk.StringVar() for k in ("x", "y", "w", "h")}

        self._build()
        self._redraw()
        self._sync_fields()
        self.transient(master)
        self.grab_set()
        self.focus_set()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=12, pady=(12, 6))
        tk.Label(top, text="Name", bg=BG, fg=FG).pack(side="left")
        ttk.Entry(top, textvariable=self.name_var, width=24).pack(side="left", padx=(6, 16))
        tk.Label(top, text="Start from", bg=BG, fg=FG).pack(side="left")
        self.tpl = ttk.Combobox(top, state="readonly", width=24,
                                values=[t.name for t in self.templates])
        self.tpl.pack(side="left", padx=(6, 16))
        self.tpl.bind("<<ComboboxSelected>>", self._load_template)
        tk.Label(top, text="Snap grid", bg=BG, fg=FG).pack(side="left")
        snap = ttk.Combobox(top, state="readonly", width=6, values=list(SNAP_CHOICES),
                            textvariable=self.snap_var)
        snap.pack(side="left", padx=6)
        snap.bind("<<ComboboxSelected>>", lambda _e: self._redraw())

        mid = tk.Frame(self, bg=BG)
        mid.pack(fill="both", expand=True, padx=12)
        self.canvas = tk.Canvas(mid, width=self.cw, height=self.ch, bg=CANVAS_BG,
                                highlightthickness=1, highlightbackground="#3a3c45")
        self.canvas.pack(side="left")
        c = self.canvas
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._motion)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Motion>", self._hover)
        c.bind("<Button-3>", self._right_click)
        c.bind("<Double-Button-1>", lambda e: self._split(e.state & 0x1 == 0))

        side = tk.Frame(mid, bg=PANEL, padx=12, pady=12)
        side.pack(side="left", fill="y", padx=(12, 0))
        tk.Label(side, text="Selected zone", bg=PANEL, fg=FG, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.sel_label = tk.Label(side, text="-", bg=PANEL, fg=MUTED)
        self.sel_label.pack(anchor="w", pady=(0, 8))
        grid = tk.Frame(side, bg=PANEL)
        grid.pack(anchor="w")
        for r, (k, lbl) in enumerate([("x", "Left %"), ("y", "Top %"), ("w", "Width %"), ("h", "Height %")]):
            tk.Label(grid, text=lbl, bg=PANEL, fg=FG, width=9, anchor="w").grid(row=r, column=0, pady=2)
            e = ttk.Spinbox(grid, from_=0, to=100, increment=1, width=7, textvariable=self.field_vars[k],
                            command=self._fields_changed)
            e.grid(row=r, column=1, pady=2)
            e.bind("<Return>", lambda _e: self._fields_changed())
            e.bind("<FocusOut>", lambda _e: self._fields_changed())

        def btn(text, cmd):
            ttk.Button(side, text=text, command=cmd).pack(fill="x", pady=2)

        tk.Frame(side, bg=PANEL, height=10).pack()
        btn("Split  left | right   (V)", lambda: self._split(True))
        btn("Split  top / bottom  (H)", lambda: self._split(False))
        btn("Delete zone   (Del)", self._delete_selected)
        btn("Undo   (Ctrl+Z)", self._undo_last)
        btn("Clear all", self._clear)
        tk.Frame(side, bg=PANEL, height=10).pack()
        btn("Preview on monitor", self._preview)
        tk.Label(side, text=("Drag empty space: new zone\nDrag zone: move\n"
                             "Drag edge/corner: resize\nRight-click: delete\n"
                             "Double-click: split (Shift = rows)"),
                 bg=PANEL, fg=MUTED, justify="left").pack(anchor="w", pady=(14, 0))

        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="x", padx=12, pady=12)
        self.status = tk.Label(bottom, text="", bg=BG, fg=MUTED)
        self.status.pack(side="left")
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="Save layout", command=self._save).pack(side="right", padx=6)

        def shortcut(fn):
            # ignore shortcuts while the user is typing in a text field
            return lambda e: None if isinstance(e.widget, (ttk.Entry, tk.Entry)) else fn()

        self.bind("<Delete>", shortcut(self._delete_selected))
        self.bind("<Control-z>", shortcut(self._undo_last))
        self.bind("<Escape>", lambda _e: self.destroy())
        for key, vert in (("v", True), ("V", True), ("h", False), ("H", False)):
            self.bind(key, shortcut(lambda v=vert: self._split(v)))

    # ------------------------------------------------------------- geometry
    def _to_px(self, z: Zone) -> tuple[float, float, float, float]:
        return z.x * self.cw, z.y * self.ch, (z.x + z.w) * self.cw, (z.y + z.h) * self.ch

    def _grid_n(self) -> int:
        return SNAP_CHOICES.get(self.snap_var.get(), 0)

    def _snap(self, v: float, axis: str, ignore: int | None) -> float:
        """Snap a fraction to grid lines and to other zones' edges."""
        candidates = [0.0, 1.0]
        for i, z in enumerate(self.zones):
            if i == ignore:
                continue
            candidates += [z.x, z.x + z.w] if axis == "x" else [z.y, z.y + z.h]
        best = min(candidates, key=lambda c: abs(c - v))
        n = self._grid_n()
        if n:
            g = round(v * n) / n
            if abs(best - v) <= EDGE_SNAP and abs(best - v) < abs(g - v):
                return best
            return g
        return best if abs(best - v) <= EDGE_SNAP else v

    def _hit(self, px: float, py: float) -> tuple[int | None, str]:
        """Zone under the pointer (topmost first) and which edges are grabbed."""
        for i in range(len(self.zones) - 1, -1, -1):
            x1, y1, x2, y2 = self._to_px(self.zones[i])
            if x1 - 3 <= px <= x2 + 3 and y1 - 3 <= py <= y2 + 3:
                edges = ""
                if abs(px - x1) <= EDGE_PX:
                    edges += "l"
                elif abs(px - x2) <= EDGE_PX:
                    edges += "r"
                if abs(py - y1) <= EDGE_PX:
                    edges += "t"
                elif abs(py - y2) <= EDGE_PX:
                    edges += "b"
                return i, edges
        return None, ""

    # --------------------------------------------------------------- mouse
    def _press(self, e) -> None:
        self.canvas.focus_set()
        i, edges = self._hit(e.x, e.y)
        fx, fy = e.x / self.cw, e.y / self.ch
        self._push_undo()
        if i is None:
            self.selected = None
            self._drag = {"mode": "create", "fx": self._snap(fx, "x", None), "fy": self._snap(fy, "y", None)}
        else:
            self.selected = i
            z = self.zones[i]
            self._drag = {"mode": "resize" if edges else "move", "edges": edges, "i": i,
                          "fx": fx, "fy": fy, "orig": Zone(z.x, z.y, z.w, z.h), "moved": False}
        self._redraw()
        self._sync_fields()

    def _motion(self, e) -> None:
        d = self._drag
        if not d:
            return
        fx = min(max(e.x / self.cw, 0.0), 1.0)
        fy = min(max(e.y / self.ch, 0.0), 1.0)
        if d["mode"] == "create":
            x2, y2 = self._snap(fx, "x", None), self._snap(fy, "y", None)
            d["rect"] = (min(d["fx"], x2), min(d["fy"], y2), abs(x2 - d["fx"]), abs(y2 - d["fy"]))
            self._redraw()
            return
        i, o = d["i"], d["orig"]
        dx, dy = fx - d["fx"], fy - d["fy"]
        d["moved"] = True
        if d["mode"] == "move":
            nx = self._snap(o.x + dx, "x", i)
            # also let the right edge snap
            rx = self._snap(o.x + o.w + dx, "x", i) - o.w
            nx = rx if abs(rx - (o.x + dx)) < abs(nx - (o.x + dx)) else nx
            ny = self._snap(o.y + dy, "y", i)
            by = self._snap(o.y + o.h + dy, "y", i) - o.h
            ny = by if abs(by - (o.y + dy)) < abs(ny - (o.y + dy)) else ny
            self.zones[i] = Zone(nx, ny, o.w, o.h).clamp()
        else:
            x1, y1, x2, y2 = o.x, o.y, o.x + o.w, o.y + o.h
            ed = d["edges"]
            if "l" in ed:
                x1 = min(self._snap(o.x + dx, "x", i), x2 - MIN_FRAC)
            if "r" in ed:
                x2 = max(self._snap(o.x + o.w + dx, "x", i), x1 + MIN_FRAC)
            if "t" in ed:
                y1 = min(self._snap(o.y + dy, "y", i), y2 - MIN_FRAC)
            if "b" in ed:
                y2 = max(self._snap(o.y + o.h + dy, "y", i), y1 + MIN_FRAC)
            x1, y1 = max(x1, 0.0), max(y1, 0.0)
            x2, y2 = min(x2, 1.0), min(y2, 1.0)
            self.zones[i] = Zone(x1, y1, x2 - x1, y2 - y1).clamp()
        self._redraw()
        self._sync_fields()

    def _release(self, _e) -> None:
        d, self._drag = self._drag, None
        if not d:
            return
        if d["mode"] == "create":
            r = d.get("rect")
            if r and r[2] >= MIN_FRAC and r[3] >= MIN_FRAC:
                self.zones.append(Zone(*r).clamp())
                self.selected = len(self.zones) - 1
            else:
                self._undo.pop()  # nothing happened
        elif not d.get("moved"):
            self._undo.pop()
        self._redraw()
        self._sync_fields()

    def _hover(self, e) -> None:
        if self._drag:
            return
        i, edges = self._hit(e.x, e.y)
        c = self.canvas
        if i is None:
            set_cursor(c, "crosshair")
        elif edges in ("lt", "rb"):
            set_cursor(c, "size_nw_se", "sizing")
        elif edges in ("rt", "lb"):
            set_cursor(c, "size_ne_sw", "sizing")
        elif edges in ("l", "r"):
            set_cursor(c, "sb_h_double_arrow")
        elif edges in ("t", "b"):
            set_cursor(c, "sb_v_double_arrow")
        else:
            set_cursor(c, "fleur")

    def _right_click(self, e) -> None:
        i, _ = self._hit(e.x, e.y)
        if i is not None:
            self._push_undo()
            del self.zones[i]
            self.selected = None
            self._redraw()
            self._sync_fields()

    # ------------------------------------------------------------ actions
    def _push_undo(self) -> None:
        self._undo.append([Zone(z.x, z.y, z.w, z.h) for z in self.zones])
        self._undo = self._undo[-50:]

    def _undo_last(self) -> None:
        if self._undo:
            self.zones = self._undo.pop()
            self.selected = None
            self._redraw()
            self._sync_fields()

    def _split(self, vertical: bool) -> None:
        if self.selected is None:
            self.status.configure(text="Select a zone first.")
            return
        self._push_undo()
        a, b = self.zones[self.selected].split(vertical)
        self.zones[self.selected] = a
        self.zones.insert(self.selected + 1, b)
        self._redraw()
        self._sync_fields()

    def _delete_selected(self) -> None:
        if self.selected is not None and self.selected < len(self.zones):
            self._push_undo()
            del self.zones[self.selected]
            self.selected = None
            self._redraw()
            self._sync_fields()

    def _clear(self) -> None:
        self._push_undo()
        self.zones = []
        self.selected = None
        self._redraw()
        self._sync_fields()

    def _load_template(self, _e=None) -> None:
        name = self.tpl.get()
        for t in self.templates:
            if t.name == name:
                self._push_undo()
                self.zones = [Zone(z.x, z.y, z.w, z.h) for z in t.zones]
                self.selected = 0 if self.zones else None
                if not t.builtin:
                    self.name_var.set(t.name)
                self._redraw()
                self._sync_fields()
                return

    def _preview(self) -> None:
        self.overlay.show(Layout("preview", self.zones), self.monitor.work, 0, ms=2000)

    def _fields_changed(self) -> None:
        if self.selected is None:
            return
        try:
            vals = {k: float(v.get()) / 100 for k, v in self.field_vars.items()}
        except ValueError:
            return
        z = self.zones[self.selected]
        nz = Zone(vals["x"], vals["y"], vals["w"], vals["h"]).clamp()
        if nz != z:
            self._push_undo()
            self.zones[self.selected] = nz
            self._redraw()

    def _save(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Windower", "Give the layout a name.", parent=self)
            return
        if not self.zones:
            messagebox.showwarning("Windower", "Draw at least one zone.", parent=self)
            return
        if name in self.existing_names and not messagebox.askyesno(
                "Windower", f"A layout called '{name}' already exists. Replace it?", parent=self):
            return
        self.on_save(Layout(name, [z.clamp() for z in self.zones]))
        self.destroy()

    # ------------------------------------------------------------- drawing
    def _sync_fields(self) -> None:
        if self.selected is None or self.selected >= len(self.zones):
            self.sel_label.configure(text="(none - click a zone)")
            for v in self.field_vars.values():
                v.set("")
        else:
            z = self.zones[self.selected]
            r = z.to_rect(self.monitor.work)
            self.sel_label.configure(text=f"Zone {self.selected + 1}  ->  {r.w} x {r.h} px")
            for k in ("x", "y", "w", "h"):
                self.field_vars[k].set(f"{getattr(z, k) * 100:.1f}")
        self.status.configure(text=f"{len(self.zones)} zone(s)   |   monitor work area "
                                   f"{self.monitor.work.w} x {self.monitor.work.h}")

    def _redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        n = self._grid_n()
        if n:
            for k in range(1, n):
                x, y = k * self.cw / n, k * self.ch / n
                c.create_line(x, 0, x, self.ch, fill="#23252c")
                c.create_line(0, y, self.cw, y, fill="#23252c")
        for i, z in enumerate(self.zones):
            x1, y1, x2, y2 = self._to_px(z)
            col = zone_color(i)
            sel = i == self.selected
            c.create_rectangle(x1 + 2, y1 + 2, x2 - 2, y2 - 2, fill=blend(col, alpha=0.35 if sel else 0.22),
                               outline=SELECT if sel else col, width=3 if sel else 2)
            c.create_text((x1 + x2) / 2, (y1 + y2) / 2 - 8, text=str(i + 1), fill=FG,
                          font=("Segoe UI", 20, "bold"))
            c.create_text((x1 + x2) / 2, (y1 + y2) / 2 + 18, fill=MUTED, font=("Segoe UI", 9),
                          text=f"{z.w * 100:.0f}% x {z.h * 100:.0f}%")
            if sel:
                for hx, hy in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
                    c.create_rectangle(hx - 4, hy - 4, hx + 4, hy + 4, fill=SELECT, outline=ACCENT)
        d = self._drag
        if d and d["mode"] == "create" and d.get("rect"):
            x, y, w, h = d["rect"]
            c.create_rectangle(x * self.cw, y * self.ch, (x + w) * self.cw, (y + h) * self.ch,
                               outline=ACCENT, dash=(4, 3), width=2)
