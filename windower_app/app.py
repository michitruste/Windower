"""
Windower control panel.

Flow:  pick a layout  ->  put windows into its zones  ->  Apply.
The real application windows are moved/resized, so every app keeps running
live and stays fully interactive (just click into it).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .editor import LayoutEditor
from .model import Layout, Monitor, Rect, Slot, WindowInfo, match_window
from .presets import PRESETS
from .storage import Store
from .ui_common import (ACCENT, BG, CANVAS_BG, FG, MUTED, PANEL, SELECT, Overlay,
                        blend, zone_color)

TICK_MS = 1000          # keep-in-place / title refresh period
LIST_REFRESH_MS = 3000  # window list auto refresh
CUSTOM_MARK = "* "  # marks user-made layouts in the dropdown


class WindowerApp:
    def __init__(self, root: tk.Tk, backend, store: Store | None = None):
        self.root = root
        self.be = backend
        self.store = store or Store()
        self.overlay = Overlay(root)
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)

        s = self.store.settings
        self.monitors: list[Monitor] = self.be.get_monitors()
        self.layout: Layout = self._find_layout(s.get("layout", "2 columns")) or PRESETS[1]
        self.slots: list[Slot | None] = [None] * len(self.layout.zones)
        self.selected_zone: int | None = 0
        self.original: dict[int, Rect] = {}
        self.windows: list[WindowInfo] = []
        self._win_sig: tuple = ()
        self._tree_drag: dict | None = None
        self._zone_drag: dict | None = None
        self._drag_label: tk.Toplevel | None = None
        self._picking: dict | None = None
        self._pending_launch: dict | None = None

        self.monitor_var = tk.StringVar()
        self.gap_var = tk.IntVar(value=int(s.get("gap", 0)))
        self.keep_var = tk.BooleanVar(value=bool(s.get("keep_in_place", False)))
        self.minimize_var = tk.BooleanVar(value=bool(s.get("minimize_panel", False)))
        self.launch_var = tk.BooleanVar(value=bool(s.get("launch_missing", True)))
        self.filter_var = tk.StringVar()
        self.layout_var = tk.StringVar()
        self.ws_var = tk.StringVar()
        self.topmost_var = tk.BooleanVar()

        self._style()
        self._build()
        self._refresh_monitors(select=int(s.get("monitor", 0)))
        self._refresh_layouts()
        self._refresh_workspaces()
        self.refresh_windows(force=True)
        self._select_zone(0)
        self.root.after(TICK_MS, self._tick)
        self.root.after(LIST_REFRESH_MS, self._auto_refresh)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ================================================================ style
    def _style(self) -> None:
        r = self.root
        r.title("Windower - window organizer")
        r.configure(bg=BG)
        r.minsize(int(980 * self.scale * 0.8), int(600 * self.scale * 0.8))
        st = ttk.Style(r)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=BG, foreground=FG, fieldbackground=PANEL,
                     bordercolor="#3a3c45", lightcolor=PANEL, darkcolor=PANEL,
                     troughcolor=PANEL, arrowcolor=FG, font=("Segoe UI", 10))
        st.configure("TButton", background="#33353e", padding=(10, 5))
        st.map("TButton", background=[("active", "#40434e"), ("pressed", "#4a4d59")])
        st.configure("Accent.TButton", background=ACCENT, foreground="white",
                     font=("Segoe UI", 11, "bold"), padding=(16, 7))
        st.map("Accent.TButton", background=[("active", "#6a9eff"), ("pressed", "#3b74e0")])
        st.configure("TCheckbutton", background=BG, foreground=FG)
        st.map("TCheckbutton", background=[("active", BG)])
        st.configure("Panel.TCheckbutton", background=PANEL)
        st.map("Panel.TCheckbutton", background=[("active", PANEL)])
        st.configure("TCombobox", fieldbackground=PANEL, background="#33353e", foreground=FG)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)],
               selectbackground=[("readonly", PANEL)], selectforeground=[("readonly", FG)])
        r.option_add("*TCombobox*Listbox.background", PANEL)
        r.option_add("*TCombobox*Listbox.foreground", FG)
        r.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        st.configure("TEntry", fieldbackground=PANEL, foreground=FG, insertcolor=FG)
        st.configure("TSpinbox", fieldbackground=PANEL, foreground=FG, arrowsize=12)
        st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                     rowheight=int(26 * self.scale), borderwidth=0)
        st.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "white")])
        st.configure("Treeview.Heading", background="#2f3139", foreground=MUTED, relief="flat")
        st.configure("TLabelframe", background=BG, bordercolor="#3a3c45")
        st.configure("TLabelframe.Label", background=BG, foreground=MUTED)

    # ================================================================ build
    def _build(self) -> None:
        r = self.root
        pad = 10

        # ---- header -------------------------------------------------------
        head = tk.Frame(r, bg=BG)
        head.pack(fill="x", padx=pad, pady=(pad, 4))
        tk.Label(head, text="Windower", bg=BG, fg=FG, font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Label(head, text=f"  {'DEMO MODE - simulated windows' if self.be.NAME == 'demo' else ''}",
                 bg=BG, fg="#f1b44c").pack(side="left")
        ttk.Checkbutton(head, text="Minimize this panel after Apply",
                        variable=self.minimize_var).pack(side="right", padx=(12, 0))
        ttk.Checkbutton(head, text="Keep windows in place", variable=self.keep_var,
                        command=self._save_settings).pack(side="right", padx=(12, 0))
        ttk.Spinbox(head, from_=0, to=60, increment=2, width=4, textvariable=self.gap_var,
                    command=self._gap_changed).pack(side="right")
        tk.Label(head, text="Gap px", bg=BG, fg=FG).pack(side="right", padx=(12, 4))
        self.monitor_cb = ttk.Combobox(head, state="readonly", width=24, textvariable=self.monitor_var)
        self.monitor_cb.pack(side="right")
        self.monitor_cb.bind("<<ComboboxSelected>>", lambda _e: self._monitor_changed())
        tk.Label(head, text="Monitor", bg=BG, fg=FG).pack(side="right", padx=(0, 4))

        body = tk.Frame(r, bg=BG)
        body.pack(fill="both", expand=True, padx=pad)

        # ---- left: open windows ------------------------------------------
        left = tk.Frame(body, bg=BG, width=int(360 * self.scale))
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="Open windows", bg=BG, fg=FG, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(left, text="Drag a window onto a zone, or double-click it\nto fill the selected zone.",
                 bg=BG, fg=MUTED, justify="left").pack(anchor="w", pady=(0, 4))
        fl = tk.Frame(left, bg=BG)
        fl.pack(fill="x", pady=(0, 4))
        tk.Label(fl, text="Filter", bg=BG, fg=FG).pack(side="left")
        fe = ttk.Entry(fl, textvariable=self.filter_var)
        fe.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.filter_var.trace_add("write", lambda *_: self.refresh_windows(force=True))

        tf = tk.Frame(left, bg=BG)
        tf.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tf, columns=("app", "title"), show="headings", selectmode="browse")
        self.tree.heading("app", text="App")
        self.tree.heading("title", text="Title")
        self.tree.column("app", width=int(90 * self.scale), stretch=False)
        self.tree.column("title", width=int(240 * self.scale))
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.tag_configure("used", foreground=MUTED)
        self.tree.bind("<ButtonPress-1>", self._tree_press)
        self.tree.bind("<B1-Motion>", self._tree_motion)
        self.tree.bind("<ButtonRelease-1>", self._tree_release)
        self.tree.bind("<Double-Button-1>", self._tree_double)

        lb = tk.Frame(left, bg=BG)
        lb.pack(fill="x", pady=6)
        ttk.Button(lb, text="Refresh", command=lambda: self.refresh_windows(force=True)).pack(side="left")
        ttk.Button(lb, text="Auto-fill zones", command=self.auto_fill).pack(side="left", padx=6)

        # ---- right: layout + preview --------------------------------------
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(pad, 0))

        lrow = tk.Frame(right, bg=BG)
        lrow.pack(fill="x")
        tk.Label(lrow, text="Layout", bg=BG, fg=FG, font=("Segoe UI", 11, "bold")).pack(side="left")
        self.layout_cb = ttk.Combobox(lrow, state="readonly", width=28, textvariable=self.layout_var)
        self.layout_cb.pack(side="left", padx=8)
        self.layout_cb.bind("<<ComboboxSelected>>", lambda _e: self._layout_selected())
        ttk.Button(lrow, text="New custom...", command=self.new_layout).pack(side="left")
        ttk.Button(lrow, text="Edit...", command=self.edit_layout).pack(side="left", padx=6)
        self.del_layout_btn = ttk.Button(lrow, text="Delete", command=self.delete_layout)
        self.del_layout_btn.pack(side="left")
        ttk.Button(lrow, text="Show zones on screen", command=self.identify).pack(side="right")

        self.canvas = tk.Canvas(right, bg=CANVAS_BG, highlightthickness=0,
                                width=int(600 * self.scale), height=int(340 * self.scale))
        self.canvas.pack(fill="both", expand=True, pady=8)
        self.canvas.bind("<Configure>", lambda _e: self.draw_preview())
        self.canvas.bind("<ButtonPress-1>", self._zone_press)
        self.canvas.bind("<B1-Motion>", self._zone_motion)
        self.canvas.bind("<ButtonRelease-1>", self._zone_release)
        self.canvas.bind("<Double-Button-1>", self._zone_double)
        self.canvas.bind("<Button-3>", self._zone_menu)

        # selected-zone bar
        zbar = tk.Frame(right, bg=PANEL, padx=8, pady=6)
        zbar.pack(fill="x")
        self.zone_label = tk.Label(zbar, text="", bg=PANEL, fg=FG, anchor="w", width=44)
        self.zone_label.pack(side="left", fill="x", expand=True)
        ttk.Button(zbar, text="Clear", command=self.clear_selected).pack(side="right")
        ttk.Button(zbar, text="Pick on screen", command=self.pick_on_screen).pack(side="right", padx=6)
        ttk.Checkbutton(zbar, text="Always on top", variable=self.topmost_var, style="Panel.TCheckbutton",
                        command=self._topmost_toggled).pack(side="right", padx=6)
        ttk.Button(zbar, text="Focus", command=self.focus_selected).pack(side="right")

        # actions
        act = tk.Frame(right, bg=BG)
        act.pack(fill="x", pady=(8, 0))
        ttk.Button(act, text="Apply layout", style="Accent.TButton", command=self.apply).pack(side="left")
        ttk.Button(act, text="Bring all to front", command=self.bring_all_front).pack(side="left", padx=6)
        ttk.Button(act, text="Clear all zones", command=self.clear_all).pack(side="left")
        ttk.Button(act, text="Restore original positions", command=self.restore_originals).pack(side="right")

        # workspaces
        ws = ttk.LabelFrame(right, text=" Workspaces (layout + which apps go where) ", padding=8)
        ws.pack(fill="x", pady=(10, 0))
        self.ws_cb = ttk.Combobox(ws, state="readonly", width=26, textvariable=self.ws_var)
        self.ws_cb.pack(side="left")
        ttk.Button(ws, text="Load", command=self.load_workspace).pack(side="left", padx=6)
        ttk.Button(ws, text="Save current as...", command=self.save_workspace).pack(side="left")
        ttk.Button(ws, text="Delete", command=self.delete_workspace).pack(side="left", padx=6)
        ttk.Checkbutton(ws, text="Launch missing apps", variable=self.launch_var,
                        command=self._save_settings).pack(side="right")

        self.status = tk.Label(r, text="", bg="#17181c", fg=MUTED, anchor="w", padx=pad, pady=4)
        self.status.pack(fill="x", side="bottom", pady=(pad, 0))

    # =========================================================== helpers
    def set_status(self, text: str, warn: bool = False) -> None:
        self.status.configure(text=text, fg="#f1b44c" if warn else MUTED)

    def monitor(self) -> Monitor:
        idx = self.monitor_cb.current()
        if idx < 0 or idx >= len(self.monitors):
            idx = 0
        return self.monitors[idx]

    def gap(self) -> int:
        try:
            return max(0, min(200, int(self.gap_var.get())))
        except (tk.TclError, ValueError):
            return 0

    def all_layouts(self) -> list[Layout]:
        return PRESETS + self.store.layouts

    def _find_layout(self, name: str) -> Layout | None:
        for lay in self.store.layouts:          # user layouts win over presets
            if lay.name == name:
                return lay.copy()
        for lay in PRESETS:
            if lay.name == name:
                c = lay.copy()
                c.builtin = True
                return c
        return None

    def _is_custom(self, name: str) -> bool:
        return any(lay.name == name for lay in self.store.layouts)

    def _display_name(self, lay: Layout) -> str:
        return (CUSTOM_MARK + lay.name) if self._is_custom(lay.name) and not lay.builtin else lay.name

    def _target(self, i: int) -> Rect:
        return self.layout.zones[i].to_rect(self.monitor().work, self.gap())

    def _save_settings(self) -> None:
        self.store.settings.update({
            "layout": self.layout.name, "monitor": max(0, self.monitor_cb.current()),
            "gap": self.gap(), "keep_in_place": self.keep_var.get(),
            "minimize_panel": self.minimize_var.get(), "launch_missing": self.launch_var.get(),
        })
        try:
            self.store.save()
        except OSError:
            pass

    def _slot_alive(self, i: int) -> bool:
        s = self.slots[i] if i < len(self.slots) else None
        return bool(s and s.hwnd and self.be.is_window(s.hwnd))

    # ========================================================== monitors
    def _refresh_monitors(self, select: int = 0) -> None:
        self.monitors = self.be.get_monitors() or [Monitor("?", Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1040), True)]
        self.monitor_cb.configure(values=[m.label(i) for i, m in enumerate(self.monitors)])
        self.monitor_cb.current(min(max(select, 0), len(self.monitors) - 1))

    def _monitor_changed(self) -> None:
        self._save_settings()
        self.draw_preview()

    def _gap_changed(self) -> None:
        self._save_settings()

    # =========================================================== layouts
    def _refresh_layouts(self) -> None:
        values = [p.name for p in PRESETS] + [CUSTOM_MARK + lay.name for lay in self.store.layouts]
        self.layout_cb.configure(values=values)
        self.layout_var.set(CUSTOM_MARK + self.layout.name if not self.layout.builtin else self.layout.name)
        self.del_layout_btn.state(["disabled"] if self.layout.builtin else ["!disabled"])

    def _layout_selected(self) -> None:
        name = self.layout_var.get()
        if name.startswith(CUSTOM_MARK):
            name = name[len(CUSTOM_MARK):]
            lay = next((lay.copy() for lay in self.store.layouts if lay.name == name), None)
        else:
            lay = next((p.copy() for p in PRESETS if p.name == name), None)
            if lay:
                lay.builtin = True
        if lay:
            self.set_layout(lay)

    def set_layout(self, lay: Layout) -> None:
        """Switch layout but keep the windows already assigned (by zone order)."""
        old = [s for s in self.slots if s]
        self.layout = lay
        n = len(lay.zones)
        self.slots = [None] * n
        for i, s in enumerate(old[:n]):
            self.slots[i] = s
        self.selected_zone = 0 if n else None
        self._refresh_layouts()
        self._save_settings()
        self.draw_preview()
        self._select_zone(self.selected_zone)
        dropped = len(old) - n
        if dropped > 0:
            self.set_status(f"Layout '{lay.name}' has {n} zones - {dropped} window(s) were left out.", warn=True)
        else:
            self.set_status(f"Layout '{lay.name}': {n} zone(s). Press Apply to arrange the windows.")

    def new_layout(self) -> None:
        start = self.layout.copy()
        start.builtin = True  # forces a fresh "My ..." name
        self._open_editor(start)

    def edit_layout(self) -> None:
        self._open_editor(self.layout.copy() if not self.layout.builtin else self._builtin_copy())

    def _builtin_copy(self) -> Layout:
        c = self.layout.copy()
        c.builtin = True
        return c

    def _open_editor(self, start: Layout) -> None:
        def on_save(lay: Layout) -> None:
            self.store.put_layout(lay)
            self.set_layout(lay.copy())
            self.set_status(f"Saved custom layout '{lay.name}'.")

        LayoutEditor(self.root, self.monitor(), start, self.all_layouts(),
                     {lay.name for lay in self.store.layouts}, on_save)

    def delete_layout(self) -> None:
        if self.layout.builtin:
            return
        if messagebox.askyesno("Windower", f"Delete custom layout '{self.layout.name}'?"):
            self.store.delete_layout(self.layout.name)
            p = PRESETS[1].copy()
            p.builtin = True
            self.set_layout(p)

    def identify(self) -> None:
        labels = [_short_app(s.exe) if s else "" for s in self.slots]
        self.overlay.show(self.layout, self.monitor().work, self.gap(), ms=2000, labels=labels)

    # =========================================================== windows
    def refresh_windows(self, force: bool = False) -> None:
        try:
            wins = self.be.list_windows()
        except Exception as ex:  # pragma: no cover
            self.set_status(f"Could not list windows: {ex}", warn=True)
            return
        sig = tuple((w.hwnd, w.title) for w in wins) + (self.filter_var.get(),
                                                         tuple(s.hwnd if s else 0 for s in self.slots))
        if not force and sig == self._win_sig:
            return
        self._win_sig = sig
        self.windows = wins
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        flt = self.filter_var.get().lower().strip()
        used = {s.hwnd for s in self.slots if s}
        for w in wins:
            if flt and flt not in w.title.lower() and flt not in w.exe.lower():
                continue
            self.tree.insert("", "end", iid=str(w.hwnd), values=(w.app, w.title),
                             tags=("used",) if w.hwnd in used else ())
        for s in sel:
            if self.tree.exists(s):
                self.tree.selection_set(s)

    def _auto_refresh(self) -> None:
        if not self._tree_drag:
            self.refresh_windows()
        self.root.after(LIST_REFRESH_MS, self._auto_refresh)

    def _window(self, hwnd: int) -> WindowInfo | None:
        return next((w for w in self.windows if w.hwnd == hwnd), None)

    # ------------------------------------------------------------- assign
    def assign(self, zone: int, win: WindowInfo) -> None:
        if zone is None or zone >= len(self.slots):
            return
        # a window can only live in one zone -> move it
        for i, s in enumerate(self.slots):
            if s and s.hwnd == win.hwnd:
                self.slots[i] = None
        self.slots[zone] = Slot.from_window(win)
        self.set_status(f"Zone {zone + 1}  <-  {win.app}: {win.title}")
        self.draw_preview()
        self._select_zone(zone)
        self.refresh_windows(force=True)

    def _next_empty_zone(self, after: int | None = None) -> int | None:
        n = len(self.slots)
        start = 0 if after is None else after + 1
        for k in range(n):
            i = (start + k) % n
            if not self._slot_alive(i):
                return i
        return None

    def auto_fill(self) -> None:
        used = {s.hwnd for s in self.slots if s}
        candidates = [w for w in self.windows if w.hwnd not in used]
        filled = 0
        for i in range(len(self.slots)):
            if not self._slot_alive(i) and candidates:
                self.slots[i] = Slot.from_window(candidates.pop(0))
                filled += 1
        self.draw_preview()
        self._select_zone(self.selected_zone)
        self.refresh_windows(force=True)
        self.set_status(f"Auto-filled {filled} zone(s) with the most recently used windows.")

    def clear_selected(self) -> None:
        i = self.selected_zone
        if i is not None and i < len(self.slots):
            s = self.slots[i]
            if s and s.topmost and self.be.is_window(s.hwnd):
                self.be.set_topmost(s.hwnd, False)
            self.slots[i] = None
            self.draw_preview()
            self._select_zone(i)
            self.refresh_windows(force=True)

    def clear_all(self) -> None:
        for s in self.slots:
            if s and s.topmost and self.be.is_window(s.hwnd):
                self.be.set_topmost(s.hwnd, False)
        self.slots = [None] * len(self.layout.zones)
        self.draw_preview()
        self._select_zone(0)
        self.refresh_windows(force=True)

    # ------------------------------------------------------------- tree dnd
    def _tree_press(self, e) -> None:
        iid = self.tree.identify_row(e.y)
        self._tree_drag = {"iid": iid, "x": e.x_root, "y": e.y_root, "active": False} if iid else None

    def _tree_motion(self, e) -> None:
        d = self._tree_drag
        if not d:
            return
        if not d["active"] and abs(e.x_root - d["x"]) + abs(e.y_root - d["y"]) > 8:
            d["active"] = True
            w = self._window(int(d["iid"]))
            self._drag_label = tk.Toplevel(self.root)
            self._drag_label.overrideredirect(True)
            try:
                self._drag_label.attributes("-topmost", True)
                self._drag_label.attributes("-alpha", 0.9)
            except tk.TclError:
                pass
            tk.Label(self._drag_label, text=f"  {w.app if w else '?'}  ", bg=ACCENT, fg="white",
                     font=("Segoe UI", 10, "bold"), pady=3).pack()
        if d["active"]:
            if self._drag_label:
                self._drag_label.geometry(f"+{e.x_root + 14}+{e.y_root + 10}")
            self.draw_preview(hover=self._zone_at_root(e.x_root, e.y_root))

    def _tree_release(self, e) -> None:
        d, self._tree_drag = self._tree_drag, None
        if self._drag_label:
            self._drag_label.destroy()
            self._drag_label = None
        if not d or not d["active"]:
            return
        zone = self._zone_at_root(e.x_root, e.y_root)
        w = self._window(int(d["iid"]))
        if zone is not None and w:
            self.assign(zone, w)
        else:
            self.draw_preview()

    def _tree_double(self, e) -> None:
        iid = self.tree.identify_row(e.y)
        w = self._window(int(iid)) if iid else None
        if not w:
            return
        zone = self.selected_zone
        if zone is None:
            zone = self._next_empty_zone()
        if zone is None:
            zone = 0
        self.assign(zone, w)
        nxt = self._next_empty_zone(zone)
        if nxt is not None:
            self._select_zone(nxt)

    # ========================================================== preview
    def _preview_geom(self) -> tuple[float, float, float, float]:
        """Where the monitor is drawn inside the canvas: (ox, oy, width, height)."""
        cw = max(self.canvas.winfo_width(), 50)
        ch = max(self.canvas.winfo_height(), 50)
        area = self.monitor().work
        pad = 14
        sc = min((cw - 2 * pad) / area.w, (ch - 2 * pad) / area.h)
        w, h = area.w * sc, area.h * sc
        return (cw - w) / 2, (ch - h) / 2, w, h

    def _zone_at(self, cx: float, cy: float) -> int | None:
        ox, oy, w, h = self._preview_geom()
        fx, fy = (cx - ox) / w, (cy - oy) / h
        for i in range(len(self.layout.zones) - 1, -1, -1):
            if self.layout.zones[i].contains(fx, fy):
                return i
        return None

    def _zone_at_root(self, x_root: int, y_root: int) -> int | None:
        c = self.canvas
        cx, cy = x_root - c.winfo_rootx(), y_root - c.winfo_rooty()
        if 0 <= cx < c.winfo_width() and 0 <= cy < c.winfo_height():
            return self._zone_at(cx, cy)
        return None

    def draw_preview(self, hover: int | None = None, swap_from: int | None = None) -> None:
        c = self.canvas
        c.delete("all")
        ox, oy, w, h = self._preview_geom()
        c.create_rectangle(ox - 4, oy - 4, ox + w + 4, oy + h + 4, outline="#3a3c45", width=2)
        g = self.gap() * (w / self.monitor().work.w)
        for i, z in enumerate(self.layout.zones):
            x1 = ox + z.x * w + g / 2 + 2
            y1 = oy + z.y * h + g / 2 + 2
            x2 = ox + (z.x + z.w) * w - g / 2 - 2
            y2 = oy + (z.y + z.h) * h - g / 2 - 2
            col = zone_color(i)
            sel = i == self.selected_zone
            alive = self._slot_alive(i)
            fill = blend(col, alpha=0.45 if hover == i else (0.32 if alive else 0.12))
            outline = SELECT if (sel or hover == i) else col
            c.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=3 if sel or hover == i else 2,
                               dash=() if alive else (5, 3))
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            c.create_text(x1 + 12, y1 + 10, text=str(i + 1), fill=col, anchor="nw",
                          font=("Segoe UI", 16, "bold"))
            s = self.slots[i] if i < len(self.slots) else None
            wrap = max(40, x2 - x1 - 16)
            if s and alive:
                c.create_text(cx, cy - 10, text=_short_app(s.exe), fill=FG, width=wrap,
                              font=("Segoe UI", 12, "bold"), justify="center")
                c.create_text(cx, cy + 14, text=_trim(s.title, 70), fill=MUTED, width=wrap,
                              font=("Segoe UI", 9), justify="center")
                if s.topmost:
                    c.create_text(x2 - 8, y1 + 10, text="ON TOP", fill=col, anchor="ne",
                                  font=("Segoe UI", 9, "bold"))
            elif s:
                c.create_text(cx, cy, text=f"{_short_app(s.exe)}\n(closed)", fill=MUTED, width=wrap,
                              justify="center", font=("Segoe UI", 10))
            else:
                c.create_text(cx, cy, text="drop a window here", fill=MUTED, width=wrap,
                              justify="center", font=("Segoe UI", 9, "italic"))
        if swap_from is not None and hover is not None and hover != swap_from:
            c.create_text(ox + w / 2, oy + h + 2, text=f"swap zone {swap_from + 1} <-> {hover + 1}",
                          fill=ACCENT, anchor="n", font=("Segoe UI", 9, "bold"))

    def _select_zone(self, i: int | None) -> None:
        self.selected_zone = i if (i is not None and i < len(self.layout.zones)) else None
        if self.selected_zone is None:
            self.zone_label.configure(text="No zone selected")
            self.topmost_var.set(False)
        else:
            s = self.slots[self.selected_zone]
            r = self._target(self.selected_zone)
            what = f"{_short_app(s.exe)} - {_trim(s.title, 40)}" if s else "empty"
            self.zone_label.configure(text=f"Zone {self.selected_zone + 1} ({r.w}x{r.h}): {what}")
            self.topmost_var.set(bool(s and s.topmost))
        self.draw_preview()

    # -------------------------------------------------------- canvas mouse
    def _zone_press(self, e) -> None:
        i = self._zone_at(e.x, e.y)
        self._zone_drag = {"from": i, "x": e.x, "y": e.y, "active": False} if i is not None else None
        self._select_zone(i)

    def _zone_motion(self, e) -> None:
        d = self._zone_drag
        if not d:
            return
        if abs(e.x - d["x"]) + abs(e.y - d["y"]) > 8:
            d["active"] = True
        if d["active"]:
            self.draw_preview(hover=self._zone_at(e.x, e.y), swap_from=d["from"])

    def _zone_release(self, e) -> None:
        d, self._zone_drag = self._zone_drag, None
        if not d or not d["active"]:
            return
        to = self._zone_at(e.x, e.y)
        fr = d["from"]
        if to is not None and to != fr:
            self.slots[fr], self.slots[to] = self.slots[to], self.slots[fr]
            self.set_status(f"Swapped zone {fr + 1} and zone {to + 1}. Press Apply (or it's automatic with "
                            f"'Keep windows in place').")
            self._select_zone(to)
            if any(self._slot_alive(k) for k in (fr, to)) and self._already_applied():
                self.apply(quiet=True)
        else:
            self.draw_preview()

    def _already_applied(self) -> bool:
        return any(s and s.hwnd in self.original for s in self.slots)

    def _zone_double(self, e) -> None:
        i = self._zone_at(e.x, e.y)
        if i is not None:
            self._select_zone(i)
            self.focus_selected()

    def _zone_menu(self, e) -> None:
        i = self._zone_at(e.x, e.y)
        if i is None:
            return
        self._select_zone(i)
        m = tk.Menu(self.root, tearoff=False, bg=PANEL, fg=FG, activebackground=ACCENT)
        alive = self._slot_alive(i)
        m.add_command(label="Focus window", command=self.focus_selected,
                      state="normal" if alive else "disabled")
        m.add_checkbutton(label="Always on top", variable=self.topmost_var, command=self._topmost_toggled,
                          state="normal" if alive else "disabled")
        m.add_command(label="Pick window on screen...", command=self.pick_on_screen)
        m.add_separator()
        m.add_command(label="Clear zone", command=self.clear_selected)
        m.tk_popup(e.x_root, e.y_root)

    # ========================================================== actions
    def apply(self, quiet: bool = False) -> None:
        moved, failed, missing = 0, [], 0
        order = []
        for i, s in enumerate(self.slots):
            if not s:
                continue
            if not self.be.is_window(s.hwnd):
                missing += 1
                continue
            target = self._target(i)
            if s.hwnd not in self.original:
                self.original[s.hwnd] = self.be.get_rect(s.hwnd)
            if self.be.place(s.hwnd, target):
                moved += 1
                order.append(s)
            else:
                failed.append(_short_app(s.exe))
        # z-order: everything tiled comes up together; topmost flags last
        for s in order:
            self.be.raise_no_focus(s.hwnd)
        for s in order:
            self.be.set_topmost(s.hwnd, s.topmost)
        self._save_settings()
        self.draw_preview()
        if quiet:
            return
        msg = f"Arranged {moved} window(s) on monitor {self.monitor_cb.current() + 1}."
        if missing:
            msg += f"  {missing} assigned window(s) are closed."
        if failed:
            msg += (f"  Could not move: {', '.join(failed)} (apps running as Administrator need "
                    f"Windower to run as Administrator too).")
        self.set_status(msg, warn=bool(failed or missing))
        if moved == 0 and not failed:
            self.set_status("Nothing to arrange yet - drag windows from the list onto the zones.", warn=True)
        elif self.minimize_var.get():
            self.root.iconify()

    def bring_all_front(self) -> None:
        n = 0
        for s in self.slots:
            if s and self.be.is_window(s.hwnd):
                self.be.raise_no_focus(s.hwnd)
                n += 1
        self.set_status(f"Brought {n} window(s) to the front.")

    def focus_selected(self) -> None:
        i = self.selected_zone
        if i is not None and self._slot_alive(i):
            self.be.focus(self.slots[i].hwnd)

    def _topmost_toggled(self) -> None:
        i = self.selected_zone
        if i is None or not self.slots[i]:
            self.topmost_var.set(False)
            return
        s = self.slots[i]
        s.topmost = bool(self.topmost_var.get())
        if self.be.is_window(s.hwnd):
            self.be.set_topmost(s.hwnd, s.topmost)
        self.draw_preview()

    def restore_originals(self) -> None:
        n = 0
        for hwnd, rect in list(self.original.items()):
            if self.be.is_window(hwnd):
                self.be.set_topmost(hwnd, False)
                self.be.place(hwnd, rect)
                n += 1
        self.original.clear()
        for s in self.slots:
            if s:
                s.topmost = False
        self.keep_var.set(False)
        self._select_zone(self.selected_zone)
        self.set_status(f"Restored {n} window(s) to where they were before Windower moved them. "
                        f"('Keep windows in place' was turned off.)")

    # --------------------------------------------------------- pick mode
    def pick_on_screen(self) -> None:
        i = self.selected_zone
        if i is None:
            self.set_status("Select a zone first.", warn=True)
            return
        self._picking = {"zone": i, "left": 150, "start_fg": self.be.foreground()}
        self.set_status(f"Click on the window you want in zone {i + 1}...  (15 s)")
        self.root.iconify()
        self.root.after(400, self._pick_poll)

    def _pick_poll(self) -> None:
        p = self._picking
        if not p:
            return
        p["left"] -= 1
        fg = self.be.foreground()
        if fg:
            fg = self.be.root_window(fg)
        wins = {w.hwnd: w for w in self.be.list_windows()}
        if fg in wins and fg != p["start_fg"]:
            self._picking = None
            self.windows = list(wins.values())
            self.root.deiconify()
            self.root.lift()
            self.assign(p["zone"], wins[fg])
            return
        if p["left"] <= 0:
            self._picking = None
            self.root.deiconify()
            self.set_status("Pick cancelled (timed out).", warn=True)
            return
        self.root.after(100, self._pick_poll)

    # ======================================================== workspaces
    def _refresh_workspaces(self) -> None:
        names = sorted(self.store.workspaces)
        self.ws_cb.configure(values=names)
        if self.ws_var.get() not in names:
            self.ws_var.set(names[0] if names else "")

    def save_workspace(self) -> None:
        if not any(self.slots):
            messagebox.showinfo("Windower", "Assign some windows to zones first.")
            return
        name = simpledialog.askstring("Save workspace", "Workspace name (e.g. 'Coding', 'Study', 'Streaming'):",
                                      initialvalue=self.ws_var.get() or "", parent=self.root)
        if not name:
            return
        name = name.strip()
        self.store.put_workspace(name, {
            "layout": self.layout.to_dict(),
            "monitor": max(0, self.monitor_cb.current()),
            "gap": self.gap(),
            "slots": [s.signature() if s else None for s in self.slots],
        })
        self.ws_var.set(name)
        self._refresh_workspaces()
        self.set_status(f"Workspace '{name}' saved.")

    def delete_workspace(self) -> None:
        name = self.ws_var.get()
        if name and messagebox.askyesno("Windower", f"Delete workspace '{name}'?"):
            self.store.delete_workspace(name)
            self.ws_var.set("")
            self._refresh_workspaces()

    def load_workspace(self) -> None:
        name = self.ws_var.get()
        data = self.store.workspaces.get(name)
        if not data:
            return
        lay = Layout.from_dict(data["layout"])
        existing = self._find_layout(lay.name)
        if existing and not existing.builtin and len(existing.zones) == len(lay.zones):
            lay = existing
        elif existing and existing.builtin:
            lay.builtin = True
        self.layout = lay
        self._refresh_monitors(select=int(data.get("monitor", 0)))
        self.gap_var.set(int(data.get("gap", 0)))
        sigs = list(data.get("slots", []))
        sigs += [None] * (len(lay.zones) - len(sigs))
        self.slots = [None] * len(lay.zones)
        self._refresh_layouts()
        missing = self._match_slots(sigs)
        launched = 0
        if missing and self.launch_var.get():
            for i in missing:
                path = sigs[i].get("exe_path") if sigs[i] else ""
                if path and self.be.launch(path):
                    launched += 1
        self._select_zone(0)
        self.refresh_windows(force=True)
        self.apply(quiet=True)
        if launched:
            self._pending_launch = {"sigs": sigs, "tries": 20}
            self.set_status(f"Workspace '{name}': started {launched} app(s), waiting for their windows...")
            self.root.after(1000, self._wait_for_launched)
        else:
            extra = f"  {len(missing)} app(s) not running." if missing else ""
            self.set_status(f"Workspace '{name}' loaded.{extra}", warn=bool(missing))

    def _match_slots(self, sigs: list) -> list[int]:
        """Fill empty slots from saved signatures; returns indexes still missing."""
        wins = self.be.list_windows()
        self.windows = wins
        taken = {s.hwnd for s in self.slots if s and self.be.is_window(s.hwnd)}
        missing = []
        for i, sig in enumerate(sigs):
            if not sig or i >= len(self.slots):
                continue
            if self._slot_alive(i):
                continue
            w = match_window(sig, wins, taken)
            if w:
                slot = Slot.from_window(w)
                slot.topmost = bool(sig.get("topmost"))
                self.slots[i] = slot
                taken.add(w.hwnd)
            else:
                missing.append(i)
        return missing

    def _wait_for_launched(self) -> None:
        p = self._pending_launch
        if not p:
            return
        p["tries"] -= 1
        missing = self._match_slots(p["sigs"])
        self.apply(quiet=True)
        self._select_zone(self.selected_zone)
        self.refresh_windows(force=True)
        if not missing:
            self._pending_launch = None
            self.set_status("All workspace apps are running and arranged.")
        elif p["tries"] <= 0:
            self._pending_launch = None
            self.set_status(f"{len(missing)} app(s) did not open a window in time.", warn=True)
        else:
            self.root.after(1000, self._wait_for_launched)

    # ============================================================ timer
    def _tick(self) -> None:
        try:
            changed = False
            for i, s in enumerate(self.slots):
                if not s or not self.be.is_window(s.hwnd):
                    continue
                title = self.be.get_title(s.hwnd)
                if title and title != s.title:
                    s.title = title
                    changed = True
                if (self.keep_var.get() and s.hwnd in self.original
                        and not self.be.is_minimized(s.hwnd) and not self.be.mouse_button_down()):
                    target = self._target(i)
                    if not self.be.get_rect(s.hwnd).close_to(target, 6):
                        self.be.place(s.hwnd, target)
            if changed and not self._zone_drag and not self._tree_drag:
                self.draw_preview()
                if self.selected_zone is not None:
                    self._select_zone(self.selected_zone)
        finally:
            self.root.after(TICK_MS, self._tick)

    def on_close(self) -> None:
        for s in self.slots:  # don't leave windows stuck on top after we quit
            if s and s.topmost and self.be.is_window(s.hwnd):
                self.be.set_topmost(s.hwnd, False)
        self._save_settings()
        self.overlay.hide()
        self.root.destroy()


def _short_app(exe: str) -> str:
    return exe[:-4] if exe.lower().endswith(".exe") else (exe or "?")


def _trim(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"
