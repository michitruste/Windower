"""
Windower control panel.

Flow:  pick a layout  ->  put windows into its zones  ->  Apply.
The real application windows are moved/resized, so every app keeps running
live and stays fully interactive (just click into it).
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, simpledialog, ttk

from . import hotkeys
from .desktop import DesktopHandles, SnapOverlay
from .editor import LayoutEditor
from .model import (MIN_ZONE, Layout, Monitor, Placement, Rect, Screen, Slot, WindowInfo, Zone, crop_from,
                    dividers, edge_coord, edge_group, fit_on_screen, match_window, monitor_at, move_edges,
                    neighbour, node_edges, nodes, snap_value)
from .presets import PRESETS
from .storage import Store
from .ui_common import (ACCENT, BG, CANVAS_BG, FG, MUTED, PANEL, SELECT, IconCache, Overlay,
                        blend, zone_color)
from .zoomview import AreaPicker, ZoomViews

TICK_MS = 1000          # keep-in-place / title refresh period
EVENT_MS = 25           # how often desktop events (drags, hotkeys) are handled
PREVIEW_GRIP = 8        # px: how close to a divider/node counts as grabbing it
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
        # one Screen (layout + windows) per monitor; the panel edits screens[cur]
        self.monitors: list[Monitor] = self._get_monitors()
        self.screens: list[Screen] = []
        self.handles: list[DesktopHandles] = []
        self.cur = min(max(int(s.get("monitor", 0)), 0), len(self.monitors) - 1)
        self.original: dict[int, Placement] = {}
        self.windows: list[WindowInfo] = []
        self._win_sig: tuple = ()
        self._tree_drag: dict | None = None
        self._zone_drag: dict | None = None
        self._drag_label: tk.Toplevel | None = None
        self._picking: dict | None = None
        self._pending_launch: dict | None = None
        self._movesize: dict | None = None       # a window the user is dragging/resizing on the desktop
        self._grip: dict | None = None           # divider/node being dragged in the preview
        self._draw: dict | None = None           # new zone being drawn in the preview

        self.events = self.be.EventSource()
        self.snap_overlay = SnapOverlay(root, backend)
        # zones that show only part of a window (slots with a crop)
        self.views = ZoomViews(root, backend, on_menu=self._view_menu, is_tiled=lambda h: self._find(h) is not None)
        self._area_picker: AreaPicker | None = None
        self._snap_keys: list[tuple[int, int]] = []   # (monitor, zone) of each snap overlay rect
        self._sync_screens()
        self.icons = IconCache(root, backend, size=round(16 * self.scale))

        self.monitor_var = tk.StringVar()
        self.gap_var = tk.IntVar(value=int(s.get("gap", 0)))
        self.keep_var = tk.BooleanVar(value=bool(s.get("keep_in_place", False)))
        self.minimize_var = tk.BooleanVar(value=bool(s.get("minimize_panel", False)))
        self.launch_var = tk.BooleanVar(value=bool(s.get("launch_missing", True)))
        self.linked_var = tk.BooleanVar(value=bool(s.get("linked_edges", True)))
        self.shiftsnap_var = tk.BooleanVar(value=bool(s.get("shift_snap", True)))
        self.handles_var = tk.BooleanVar(value=bool(s.get("desktop_handles", False)))
        self.hotkey_var = tk.StringVar(value=s.get("hotkey_modifier", "Ctrl+Alt"))
        self.filter_var = tk.StringVar()
        self.layout_var = tk.StringVar()
        self.ws_var = tk.StringVar()
        self.topmost_var = tk.BooleanVar()

        self._style()
        self._build()
        self._refresh_monitors(select=self.cur)
        self._refresh_layouts()
        self._refresh_workspaces()
        self.refresh_windows(force=True)
        self._select_zone(0)
        self.root.after(TICK_MS, self._tick)
        self.root.after(LIST_REFRESH_MS, self._auto_refresh)
        self.root.after(EVENT_MS, self._pump_events)
        self._apply_hotkeys(announce=False)
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
        # flat list: no expand/collapse indicator, so the app icon sits at the left edge
        st.layout("Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
            ("Treeitem.image", {"side": "left", "sticky": ""}),
            ("Treeitem.text", {"sticky": "nswe"})]})])
        st.configure("TLabelframe", background=BG, bordercolor="#3a3c45")
        st.configure("TLabelframe.Label", background=BG, foreground=MUTED)

    # ================================================================ build
    def _build(self) -> None:
        r = self.root
        pad = 10

        # ---- header -------------------------------------------------------
        head = tk.Frame(r, bg=BG)
        head.pack(fill="x", padx=pad, pady=(pad, 4))
        tk.Label(head, text="Windower (michi's version)", bg=BG, fg=FG, font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Label(head, text=f"  {'DEMO MODE - simulated windows' if self.be.NAME == 'demo' else ''}",
                 bg=BG, fg="#f1b44c").pack(side="left")
        ttk.Spinbox(head, from_=0, to=60, increment=2, width=4, textvariable=self.gap_var,
                    command=self._gap_changed).pack(side="right")
        tk.Label(head, text="Gap px", bg=BG, fg=FG).pack(side="right", padx=(12, 4))
        self.monitor_cb = ttk.Combobox(head, state="readonly", width=40, textvariable=self.monitor_var)
        self.monitor_cb.pack(side="right")
        self.monitor_cb.bind("<<ComboboxSelected>>", lambda _e: self._monitor_changed())
        tk.Label(head, text="Monitor", bg=BG, fg=FG).pack(side="right", padx=(0, 4))

        # ---- options row --------------------------------------------------
        opts = tk.Frame(r, bg=BG)
        opts.pack(fill="x", padx=pad, pady=(0, 6))
        for text, var, cmd in (
            ("Keep windows in place", self.keep_var, self._save_settings),
            ("Linked edges", self.linked_var, self._save_settings),
            ("Shift-drag snapping", self.shiftsnap_var, self._save_settings),
            ("Resize handles on desktop", self.handles_var, self._handles_toggled),
            ("Minimize panel after Apply", self.minimize_var, self._save_settings),
        ):
            ttk.Checkbutton(opts, text=text, variable=var, command=cmd).pack(side="left", padx=(0, 14))
        ttk.Button(opts, text="?", width=3, command=self.show_hotkey_help).pack(side="right")
        hk = ttk.Combobox(opts, state="readonly", width=12, textvariable=self.hotkey_var,
                          values=list(hotkeys.MODIFIER_CHOICES))
        hk.pack(side="right", padx=(4, 4))
        hk.bind("<<ComboboxSelected>>", lambda _e: self._apply_hotkeys())
        tk.Label(opts, text="Hotkeys", bg=BG, fg=FG).pack(side="right")

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
        self.tree = ttk.Treeview(tf, columns=("title",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="App", anchor="w")
        self.tree.heading("title", text="Title")
        self.tree.column("#0", width=int(116 * self.scale), stretch=False)
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
        ttk.Button(lrow, text="Show zones", command=self.identify).pack(side="right")
        self.reset_btn = ttk.Button(lrow, text="Reset layout", command=self.reset_layout_sizes)
        self.reset_btn.pack(side="right", padx=6)
        self.saveas_btn = ttk.Button(lrow, text="Save layout as...", command=self.save_layout_as)
        self.saveas_btn.pack(side="right")

        self.canvas = tk.Canvas(right, bg=CANVAS_BG, highlightthickness=0,
                                width=int(600 * self.scale), height=int(340 * self.scale))
        self.canvas.pack(fill="both", expand=True, pady=8)
        self.canvas.bind("<Configure>", lambda _e: self.draw_preview())
        self.canvas.bind("<ButtonPress-1>", self._zone_press)
        self.canvas.bind("<B1-Motion>", self._zone_motion)
        self.canvas.bind("<ButtonRelease-1>", self._zone_release)
        self.canvas.bind("<Double-Button-1>", self._zone_double)
        self.canvas.bind("<Button-3>", self._zone_menu)
        self.canvas.bind("<Motion>", self._canvas_hover)

        # selected-zone bar
        zbar = tk.Frame(right, bg=PANEL, padx=8, pady=6)
        zbar.pack(fill="x")
        self.zone_label = tk.Label(zbar, text="", bg=PANEL, fg=FG, anchor="w", width=44)
        self.zone_label.pack(side="left", fill="x", expand=True)
        ttk.Button(zbar, text="Clear", command=self.clear_selected).pack(side="right")
        ttk.Button(zbar, text="Pick on screen", command=self.pick_on_screen).pack(side="right", padx=6)
        ttk.Button(zbar, text="Zoom area...", command=self.zoom_area).pack(side="right")
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

    # the panel (layout dropdown, zone bar, editor...) works on the current monitor's screen
    @property
    def screen(self) -> Screen:
        return self.screens[self.cur]

    @property
    def layout(self) -> Layout:
        return self.screen.layout

    @layout.setter
    def layout(self, lay: Layout) -> None:
        self.screen.layout = lay

    @property
    def slots(self) -> list[Slot | None]:
        return self.screen.slots

    @slots.setter
    def slots(self, slots: list[Slot | None]) -> None:
        self.screen.slots = slots

    @property
    def layout_adjusted(self) -> bool:
        return self.screen.adjusted

    @layout_adjusted.setter
    def layout_adjusted(self, v: bool) -> None:
        self.screen.adjusted = v

    @property
    def selected_zone(self) -> int | None:
        return self.screen.selected

    @selected_zone.setter
    def selected_zone(self, i: int | None) -> None:
        self.screen.selected = i

    @property
    def multi(self) -> bool:
        return len(self.monitors) > 1

    def monitor(self) -> Monitor:
        return self.monitors[self.cur]

    def _assigned(self):
        """(monitor, zone, slot) for every zone on every monitor that has a window tiled in it.
        Zoom zones are left out: their window isn't moved into the zone (see _zooms)."""
        for m, i, s in self._all_slots():
            if not s.crop:
                yield m, i, s

    def _zooms(self):
        """(monitor, zone, slot) for every zoom zone (shows part of a window)."""
        for m, i, s in self._all_slots():
            if s.crop:
                yield m, i, s

    def _all_slots(self):
        for m, scr in enumerate(self.screens):
            for i, s in enumerate(scr.slots):
                if s:
                    yield m, i, s

    def _zone_name(self, m: int, i: int) -> str:
        return f"monitor {m + 1}, zone {i + 1}" if self.multi else f"zone {i + 1}"

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

    def _target(self, i: int, m: int | None = None) -> Rect:
        m = self.cur if m is None else m
        return self.screens[m].layout.zones[i].to_rect(self.monitors[m].work, self.gap())

    def _save_settings(self) -> None:
        self.store.settings.update({
            "layout": self.layout.name, "monitor": self.cur,
            "screen_layouts": [scr.layout.name for scr in self.screens],
            "gap": self.gap(), "keep_in_place": self.keep_var.get(),
            "minimize_panel": self.minimize_var.get(), "launch_missing": self.launch_var.get(),
            "linked_edges": self.linked_var.get(), "shift_snap": self.shiftsnap_var.get(),
            "desktop_handles": self.handles_var.get(), "hotkey_modifier": self.hotkey_var.get(),
        })
        try:
            self.store.save()
        except OSError:
            pass

    def _slot_alive(self, i: int, m: int | None = None) -> bool:
        slots = self.slots if m is None else self.screens[m].slots
        s = slots[i] if i < len(slots) else None
        return bool(s and s.hwnd and self.be.is_window(s.hwnd))

    # ========================================================== monitors
    def _get_monitors(self) -> list[Monitor]:
        return self.be.get_monitors() or [Monitor("?", Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1040), True)]

    def _sync_screens(self) -> None:
        """One screen and one set of desktop handles per monitor (after monitors appear/disappear)."""
        names = self.store.settings.get("screen_layouts") or []
        while len(self.screens) < len(self.monitors):
            k = len(self.screens)
            name = names[k] if k < len(names) else self.store.settings.get("layout", "2 columns")
            self.screens.append(Screen(self._find_layout(name) or self._default_layout()))
        for scr in self.screens[len(self.monitors):]:
            for s in scr.slots:
                if s and s.topmost and not s.crop and self.be.is_window(s.hwnd):
                    self.be.set_topmost(s.hwnd, False)
        del self.screens[len(self.monitors):]
        for h in self.handles:
            h.hide()
        self.handles = [DesktopHandles(self.root, self.be, lambda *a, m=m: self._handle_drag(m, *a))
                        for m in range(len(self.monitors))]
        self.cur = min(self.cur, len(self.monitors) - 1)

    def _refresh_monitors(self, select: int = 0) -> None:
        self.monitors = self._get_monitors()
        self._sync_screens()
        self.cur = min(max(select, 0), len(self.monitors) - 1)
        self._refresh_monitor_labels()

    def _refresh_monitor_labels(self) -> None:
        self.monitor_cb.configure(values=[f"{m.label(k)} - {self.screens[k].layout.name}"
                                          for k, m in enumerate(self.monitors)])
        self.monitor_cb.current(self.cur)

    def _set_current(self, m: int) -> None:
        """Make monitor m the one the panel edits (layout dropdown, zone bar...)."""
        if m == self.cur or not 0 <= m < len(self.screens):
            return
        self.cur = m
        self.monitor_cb.current(m)
        self._refresh_layouts()
        self._select_zone(self.selected_zone)

    def _monitor_changed(self) -> None:
        self._set_current(max(0, self.monitor_cb.current()))
        self._save_settings()

    def _gap_changed(self) -> None:
        self._save_settings()
        self.draw_preview()

    # =========================================================== layouts
    def _refresh_layouts(self) -> None:
        self._refresh_monitor_labels()
        values = [p.name for p in PRESETS] + [CUSTOM_MARK + lay.name for lay in self.store.layouts]
        self.layout_cb.configure(values=values)
        self.layout_var.set(CUSTOM_MARK + self.layout.name if not self.layout.builtin else self.layout.name)
        self.del_layout_btn.state(["disabled"] if self.layout.builtin else ["!disabled"])
        adj = ["!disabled"] if self.layout_adjusted else ["disabled"]
        self.reset_btn.state(adj)
        self.saveas_btn.state(adj)

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
        self.layout_adjusted = False
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
            where = f" on monitor {self.cur + 1}" if self.multi else ""
            self.set_status(f"Layout '{lay.name}'{where}: {n} zone(s). Press Apply to arrange the windows.")
        if self._already_applied():
            self.apply(quiet=True, only={self.cur})
        else:
            self._refresh_handles()

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

    def _default_layout(self) -> Layout:
        lay = (next((p for p in PRESETS if p.name == "2 columns"), None) or PRESETS[0]).copy()
        lay.builtin = True
        return lay

    def reset_layout_sizes(self) -> None:
        """Undo divider/node/edge drags and added/removed zones: back to the saved layout."""
        fresh = self._find_layout(self.layout.name)
        if not fresh:
            return
        if len(fresh.zones) != len(self.layout.zones):
            self.set_layout(fresh)   # keeps the windows, in zone order
            return
        self.layout.zones = fresh.zones
        self.layout_adjusted = False
        self._layout_changed(live=False, adjusted=False)
        self.set_status(f"'{self.layout.name}' reset to its original sizes.")

    def save_layout_as(self) -> None:
        default = self.layout.name if not self.layout.builtin else f"My {self.layout.name}"
        name = simpledialog.askstring("Save layout", "Save these zone sizes as a custom layout named:",
                                      initialvalue=default, parent=self.root)
        if not name or not name.strip():
            return
        lay = Layout(name.strip(), [Zone(z.x, z.y, z.w, z.h) for z in self.layout.zones])
        self.store.put_layout(lay)
        self.layout = lay.copy()
        self.layout_adjusted = False
        self._refresh_layouts()
        self._save_settings()
        self.set_status(f"Saved custom layout '{lay.name}'.")
    def delete_layout(self) -> None:
        if self.layout.builtin:
            return
        if messagebox.askyesno("Windower", f"Delete custom layout '{self.layout.name}'?"):
            self.store.delete_layout(self.layout.name)
            self.set_layout(self._default_layout())

    def identify(self) -> None:
        self.overlay.show_many([(scr.layout, self.monitors[m].work,
                                 [(_short_app(s.exe) + (" (zoom)" if s.crop else "")) if s else "" for s in scr.slots])
                                for m, scr in enumerate(self.screens)], self.gap(), ms=2000)

    # =========================================================== windows
    def refresh_windows(self, force: bool = False) -> None:
        try:
            wins = self.be.list_windows()
        except Exception as ex:  # pragma: no cover
            self.set_status(f"Could not list windows: {ex}", warn=True)
            return
        used = {s.hwnd for _m, _i, s in self._assigned()}
        sig = tuple((w.hwnd, w.title) for w in wins) + (self.filter_var.get(), tuple(sorted(used)))
        if not force and sig == self._win_sig:
            return
        self._win_sig = sig
        self.windows = wins
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        flt = self.filter_var.get().lower().strip()
        self.icons.prune({w.hwnd for w in wins} | used)
        for w in wins:
            if flt and flt not in w.title.lower() and flt not in w.exe.lower():
                continue
            self.tree.insert("", "end", iid=str(w.hwnd), text=f" {w.app}", values=(w.title,),
                             image=self.icons.get(w.hwnd) or self.icons.blank,
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
        """Put win into a zone of the current monitor."""
        if zone is None or zone >= len(self.slots):
            return
        # a window can only live in one zone (on any monitor) -> move it
        for m, i, s in list(self._assigned()):
            if s.hwnd == win.hwnd:
                self.screens[m].slots[i] = None
        self.slots[zone] = Slot.from_window(win)
        self.set_status(f"{self._zone_name(self.cur, zone).capitalize()}  <-  {win.app}: {win.title}")
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
        """Fill the empty zones of the current monitor with the most recently used free windows."""
        used = {s.hwnd for _m, _i, s in self._assigned()}
        candidates = [w for w in self.windows if w.hwnd not in used]
        filled = 0
        for i in range(len(self.slots)):
            if not self._slot_alive(i) and candidates:
                self.slots[i] = Slot.from_window(candidates.pop(0))
                filled += 1
        self.draw_preview()
        self._select_zone(self.selected_zone)
        self.refresh_windows(force=True)
        where = f" on monitor {self.cur + 1}" if self.multi else ""
        self.set_status(f"Auto-filled {filled} zone(s){where} with the most recently used windows.")

    def clear_selected(self) -> None:
        i = self.selected_zone
        if i is not None and i < len(self.slots):
            s = self.slots[i]
            if s and s.topmost and not s.crop and self.be.is_window(s.hwnd):
                self.be.set_topmost(s.hwnd, False)
            self.slots[i] = None
            self.draw_preview()
            self._select_zone(i)
            self.refresh_windows(force=True)

    def clear_all(self) -> None:
        """Empty every zone of the current monitor."""
        for s in self.slots:
            if s and s.topmost and not s.crop and self.be.is_window(s.hwnd):
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
            icon = self.icons.get(w.hwnd) if w else None
            tk.Label(self._drag_label, text=f"  {w.app if w else '?'}  ", bg=ACCENT, fg="white",
                     font=("Segoe UI", 10, "bold"), pady=3, padx=4,
                     image=icon or "", compound="left").pack()
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
        key = self._zone_at_root(e.x_root, e.y_root)
        w = self._window(int(d["iid"]))
        if key is not None and w:
            self._set_current(key[0])
            self.assign(key[1], w)
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
    def _preview_geom(self, m: int | None = None) -> tuple[float, float, float, float]:
        """Where monitor m's work area is drawn inside the canvas: (ox, oy, width, height).

        All monitors are drawn at once, arranged the way Windows has them."""
        m = self.cur if m is None else m
        cw = max(self.canvas.winfo_width(), 50)
        ch = max(self.canvas.winfo_height(), 50)
        areas = [mo.work for mo in self.monitors]
        bx1, by1 = min(a.x for a in areas), min(a.y for a in areas)
        bx2, by2 = max(a.x + a.w for a in areas), max(a.y + a.h for a in areas)
        pad = 14
        sc = min((cw - 2 * pad) / (bx2 - bx1), (ch - 2 * pad) / (by2 - by1))
        ox, oy = (cw - (bx2 - bx1) * sc) / 2, (ch - (by2 - by1) * sc) / 2
        sep = 8 if self.multi else 0          # keeps neighbouring monitors visibly apart
        a = areas[m]
        return (ox + (a.x - bx1) * sc + sep, oy + (a.y - by1) * sc + sep,
                a.w * sc - 2 * sep, a.h * sc - 2 * sep)

    def _zone_at(self, cx: float, cy: float) -> tuple[int, int] | None:
        """(monitor, zone) under a canvas point."""
        for m, scr in enumerate(self.screens):
            ox, oy, w, h = self._preview_geom(m)
            fx, fy = (cx - ox) / w, (cy - oy) / h
            if not (0 <= fx < 1 and 0 <= fy < 1):
                continue
            for i in range(len(scr.layout.zones) - 1, -1, -1):
                if scr.layout.zones[i].contains(fx, fy):
                    return m, i
        return None

    def _zone_at_root(self, x_root: int, y_root: int) -> tuple[int, int] | None:
        c = self.canvas
        cx, cy = x_root - c.winfo_rootx(), y_root - c.winfo_rooty()
        if 0 <= cx < c.winfo_width() and 0 <= cy < c.winfo_height():
            return self._zone_at(cx, cy)
        return None

    def draw_preview(self, hover: tuple[int, int] | None = None,
                     swap_from: tuple[int, int] | None = None) -> None:
        c = self.canvas
        c.delete("all")
        for m, scr in enumerate(self.screens):
            self._draw_screen(m, scr, hover)
        self._sync_views()
        d = self._draw
        if d and d.get("zone"):
            ox, oy, w, h = self._preview_geom(d["m"])
            z = d["zone"]
            c.create_rectangle(ox + z.x * w, oy + z.y * h, ox + (z.x + z.w) * w, oy + (z.y + z.h) * h,
                               outline=ACCENT, fill=blend(ACCENT, alpha=0.18), dash=(5, 3), width=2)
            r = z.to_rect(self.monitors[d["m"]].work, self.gap())
            c.create_text(ox + (z.x + z.w / 2) * w, oy + (z.y + z.h / 2) * h, fill=FG,
                          text=f"new zone\n{r.w} x {r.h}", justify="center", font=("Segoe UI", 9, "bold"))
        if swap_from is not None and hover is not None and hover != swap_from:
            name = (lambda k: f"{k[0] + 1}.{k[1] + 1}") if self.multi else (lambda k: str(k[1] + 1))
            c.create_text(c.winfo_width() / 2, c.winfo_height() - 2,
                          text=f"swap zone {name(swap_from)} <-> {name(hover)}",
                          fill=ACCENT, anchor="s", font=("Segoe UI", 9, "bold"))

    def _draw_screen(self, m: int, scr: Screen, hover: tuple[int, int] | None) -> None:
        c = self.canvas
        ox, oy, w, h = self._preview_geom(m)
        current = m == self.cur
        c.create_rectangle(ox - 4, oy - 4, ox + w + 4, oy + h + 4, width=2,
                           outline=ACCENT if current and self.multi else "#3a3c45")
        g = self.gap() * (w / self.monitors[m].work.w)
        for i, z in enumerate(scr.layout.zones):
            x1 = ox + z.x * w + g / 2 + 2
            y1 = oy + z.y * h + g / 2 + 2
            x2 = ox + (z.x + z.w) * w - g / 2 - 2
            y2 = oy + (z.y + z.h) * h - g / 2 - 2
            col = zone_color(i)
            sel = current and i == scr.selected
            hot = hover == (m, i)
            alive = self._slot_alive(i, m)
            fill = blend(col, alpha=0.45 if hot else (0.32 if alive else 0.12))
            outline = SELECT if (sel or hot) else col
            c.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=3 if sel or hot else 2,
                               dash=() if alive else (5, 3))
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            c.create_text(x1 + 12, y1 + 10, text=str(i + 1), fill=col, anchor="nw",
                          font=("Segoe UI", 16, "bold"))
            s = scr.slots[i] if i < len(scr.slots) else None
            wrap = max(40, x2 - x1 - 16)
            if s and alive:
                icon = self.icons.get(s.hwnd)
                if icon and y2 - y1 > 110:
                    c.create_image(cx, cy - 26, image=icon, anchor="s")
                c.create_text(cx, cy - 10, text=_short_app(s.exe), fill=FG, width=wrap,
                              font=("Segoe UI", 12, "bold"), justify="center")
                c.create_text(cx, cy + 6, text=_trim(s.title, 70), fill=MUTED, width=wrap, anchor="n",
                              font=("Segoe UI", 9), justify="center")   # long titles wrap downwards
                badges = ([f"ZOOM {s.crop.w}x{s.crop.h}"] if s.crop else []) + (["ON TOP"] if s.topmost else [])
                for k, badge in enumerate(badges):
                    c.create_text(x2 - 8, y1 + 10 + 16 * k, text=badge, fill=col, anchor="ne",
                                  font=("Segoe UI", 9, "bold"))
            elif s:
                c.create_text(cx, cy, text=f"{_short_app(s.exe)}\n(closed)", fill=MUTED, width=wrap,
                              justify="center", font=("Segoe UI", 10))
            else:
                c.create_text(cx, cy, text="drop a window here", fill=MUTED, width=wrap,
                              justify="center", font=("Segoe UI", 9, "italic"))
        # dividers (lines between zones) and nodes (where lines meet) - drag them to resize
        divs = dividers(scr.layout.zones)
        active = self._grip["edges"] if self._grip and self._grip["m"] == m else set()
        for d in divs:
            hot = bool(set(d.edges) & active)
            if d.axis == "v":
                x = ox + d.coord * w
                c.create_line(x, oy + d.span[0] * h + 6, x, oy + d.span[1] * h - 6,
                              fill=ACCENT if hot else "#6b6f7d", width=4 if hot else 2, capstyle="round")
            else:
                y = oy + d.coord * h
                c.create_line(ox + d.span[0] * w + 6, y, ox + d.span[1] * w - 6, y,
                              fill=ACCENT if hot else "#6b6f7d", width=4 if hot else 2, capstyle="round")
        for n in nodes(scr.layout.zones, divs):
            x, y = ox + n.x * w, oy + n.y * h
            v, hh = node_edges(n)
            hot = bool(set(v + hh) & active)
            r = 8 if hot else 6
            c.create_oval(x - r, y - r, x + r, y + r, fill="#f1b44c", outline=SELECT, width=2)
        if self.multi:  # monitor tag in the bottom-right corner
            t = c.create_text(ox + w - 8, oy + h - 6, text=f"Monitor {m + 1}", anchor="se",
                              fill="white" if current else FG, font=("Segoe UI", 9, "bold"))
            x1, y1, x2, y2 = c.bbox(t)
            bg = c.create_rectangle(x1 - 6, y1 - 2, x2 + 6, y2 + 2, width=0,
                                    fill=ACCENT if current else "#3a3c45")
            c.tag_lower(bg, t)

    def _sync_views(self) -> None:
        """One zoom view on the desktop per zoom zone whose window is open (updated in place)."""
        self.views.sync({(m, i): (s, self._target(i, m), self.monitors[m].work)
                         for m, i, s in self._zooms() if self.be.is_window(s.hwnd)})

    def _select_zone(self, i: int | None) -> None:
        self.selected_zone = i if (i is not None and i < len(self.layout.zones)) else None
        where = f"Monitor {self.cur + 1}, zone" if self.multi else "Zone"
        if self.selected_zone is None:
            self.zone_label.configure(text=f"Monitor {self.cur + 1}: no zone selected" if self.multi
                                      else "No zone selected")
            self.topmost_var.set(False)
        else:
            s = self.slots[self.selected_zone]
            r = self._target(self.selected_zone)
            what = f"{_short_app(s.exe)} - {_trim(s.title, 40)}" if s else "empty"
            if s and s.crop:
                what = f"zoom of {what} ({s.crop.w}x{s.crop.h} area)"
            self.zone_label.configure(text=f"{where} {self.selected_zone + 1} ({r.w}x{r.h}): {what}")
            self.topmost_var.set(bool(s and s.topmost))
        self.draw_preview()

    # -------------------------------------------------------- canvas mouse
    def _grip_at(self, cx: float, cy: float) -> dict | None:
        """Node or divider under the pointer in the preview (on any monitor)."""
        for m, scr in enumerate(self.screens):
            ox, oy, w, h = self._preview_geom(m)
            divs = dividers(scr.layout.zones)
            for n in nodes(scr.layout.zones, divs):
                if abs(ox + n.x * w - cx) <= PREVIEW_GRIP + 2 and abs(oy + n.y * h - cy) <= PREVIEW_GRIP + 2:
                    v, hh = node_edges(n)
                    return {"m": m, "v": v, "h": hh, "edges": set(v + hh), "kind": "node"}
            for d in divs:
                if d.axis == "v":
                    near = abs(ox + d.coord * w - cx) <= PREVIEW_GRIP and oy + d.span[0] * h <= cy <= oy + d.span[1] * h
                else:
                    near = abs(oy + d.coord * h - cy) <= PREVIEW_GRIP and ox + d.span[0] * w <= cx <= ox + d.span[1] * w
                if near:
                    v = d.edges if d.axis == "v" else []
                    hh = d.edges if d.axis == "h" else []
                    return {"m": m, "v": v, "h": hh, "edges": set(d.edges), "kind": d.axis}
        return None

    def _canvas_hover(self, e) -> None:
        if self._grip or self._zone_drag or self._draw:
            return
        g = self._grip_at(e.x, e.y)
        cur = {"node": "fleur", "v": "sb_h_double_arrow", "h": "sb_v_double_arrow"}.get(g["kind"]) if g else ""
        if not g and self._draws_zone(e):
            cur = "crosshair"
        try:
            self.canvas.configure(cursor=cur)
        except tk.TclError:
            pass

    def _monitor_at_canvas(self, cx: float, cy: float) -> tuple[int, float, float] | None:
        """(monitor, fx, fy) of a canvas point that lies on a monitor's work area in the preview."""
        for m in range(len(self.screens)):
            ox, oy, w, h = self._preview_geom(m)
            fx, fy = (cx - ox) / w, (cy - oy) / h
            if 0 <= fx <= 1 and 0 <= fy <= 1:
                return m, fx, fy
        return None

    def _draws_zone(self, e) -> bool:
        """A press here draws a new zone: on empty monitor space, or anywhere with Ctrl held."""
        return self._monitor_at_canvas(e.x, e.y) is not None and \
            (bool(e.state & 0x4) or self._zone_at(e.x, e.y) is None)

    def _draw_snap(self, m: int, v: float, axis: str) -> float:
        """Snap a drawn edge to the screen edges and other zones' edges, else to a 1/12 grid."""
        _ox, _oy, w, h = self._preview_geom(m)
        size = w if axis == "x" else h
        edges = [0.0, 1.0] + [e for z in self.screens[m].layout.zones
                              for e in ((z.x, z.x + z.w) if axis == "x" else (z.y, z.y + z.h))]
        s = snap_value(v, edges, PREVIEW_GRIP / size)
        return s if s != v else snap_value(v, [k / 12 for k in range(13)], PREVIEW_GRIP / 2 / size)

    def _zone_press(self, e) -> None:
        g = self._grip_at(e.x, e.y)
        if g:
            self._set_current(g["m"])
            self._grip = g
            self.draw_preview()
            return
        if self._draws_zone(e):
            m, fx, fy = self._monitor_at_canvas(e.x, e.y)
            self._set_current(m)
            self._draw = {"m": m, "fx": self._draw_snap(m, fx, "x"), "fy": self._draw_snap(m, fy, "y"),
                          "zone": None}
            self._select_zone(None)
            return
        key = self._zone_at(e.x, e.y)
        if key is not None:
            self._set_current(key[0])
        self._zone_drag = {"from": key, "x": e.x, "y": e.y, "active": False} if key is not None else None
        self._select_zone(key[1] if key else None)

    def _draw_motion(self, e) -> None:
        d = self._draw
        m = d["m"]
        ox, oy, w, h = self._preview_geom(m)
        x2 = self._draw_snap(m, min(max((e.x - ox) / w, 0.0), 1.0), "x")
        y2 = self._draw_snap(m, min(max((e.y - oy) / h, 0.0), 1.0), "y")
        d["zone"] = Zone(min(d["fx"], x2), min(d["fy"], y2), abs(x2 - d["fx"]), abs(y2 - d["fy"]))
        self.draw_preview()

    def _draw_release(self, e) -> None:
        self._draw_motion(e)
        d, self._draw = self._draw, None
        z = d["zone"]
        if z.w < MIN_ZONE or z.h < MIN_ZONE:
            self.draw_preview()
            if z.w > 0.01 or z.h > 0.01:
                self.set_status("Too small for a zone - drag a bigger rectangle.", warn=True)
            return
        i = self.screen.add_zone(z)
        self.selected_zone = i
        self._zones_edited(f"Added zone {i + 1}. Drop a window on it, or double-click one in the list.")

    def split_selected(self, vertical: bool) -> None:
        i = self.selected_zone
        if i is None:
            return
        n = self.screen.split_zone(i, vertical)
        self.selected_zone = n
        how = "left | right" if vertical else "top / bottom"
        self._zones_edited(f"Split zone {i + 1} {how}. The new zone {n + 1} is empty - drop a window on it.")

    def remove_selected_zone(self) -> None:
        i = self.selected_zone
        if i is None:
            return
        if len(self.layout.zones) <= 1:
            self.set_status("A layout needs at least one zone.", warn=True)
            return
        s = self.screen.remove_zone(i)
        if s and s.topmost and not s.crop and self.be.is_window(s.hwnd):
            self.be.set_topmost(s.hwnd, False)
        left = f" {_short_app(s.exe)} stays where it is." if s and not s.crop and self._window(s.hwnd) else ""
        self._zones_edited(f"Removed zone {i + 1}.{left}")

    def _zones_edited(self, status: str) -> None:
        """Zones of the current monitor were added/split/removed in the preview."""
        self._save_settings()
        self._layout_changed(live=False)
        self.refresh_windows(force=True)
        self.set_status(status + "  'Save layout as...' keeps it, 'Reset layout' undoes it.")

    def _zone_motion(self, e) -> None:
        if self._draw:
            self._draw_motion(e)
            return
        if self._grip:
            ox, oy, w, h = self._preview_geom()
            self._move_grip(self._grip["v"], self._grip["h"], (e.x - ox) / w, (e.y - oy) / h, live=True)
            return
        d = self._zone_drag
        if not d:
            return
        if abs(e.x - d["x"]) + abs(e.y - d["y"]) > 8:
            d["active"] = True
        if d["active"]:
            self.draw_preview(hover=self._zone_at(e.x, e.y), swap_from=d["from"])

    def _zone_release(self, e) -> None:
        if self._draw:
            self._draw_release(e)
            return
        if self._grip:
            g, self._grip = self._grip, None
            ox, oy, w, h = self._preview_geom()
            self._move_grip(g["v"], g["h"], (e.x - ox) / w, (e.y - oy) / h, live=False)
            return
        d, self._zone_drag = self._zone_drag, None
        if not d or not d["active"]:
            return
        to = self._zone_at(e.x, e.y)
        fr = d["from"]
        if to is not None and to != fr:
            (fm, fi), (tm, ti) = fr, to
            a, b = self.screens[fm].slots, self.screens[tm].slots
            a[fi], b[ti] = b[ti], a[fi]
            self.set_status(f"Swapped {self._zone_name(fm, fi)} and {self._zone_name(tm, ti)}. Press Apply "
                            f"(or it's automatic with 'Keep windows in place').")
            self._set_current(tm)
            self._select_zone(ti)
            if (self._slot_alive(fi, fm) or self._slot_alive(ti, tm)) and \
                    (self._already_applied(fm) or self._already_applied(tm)):
                self.apply(quiet=True, only={fm, tm})
        else:
            self.draw_preview()

    def _already_applied(self, m: int | None = None) -> bool:
        m = self.cur if m is None else m
        tiled = any(s and not s.crop and s.hwnd in self.original for s in self.screens[m].slots)
        return tiled or self.views.on_monitor(m)

    def _zone_double(self, e) -> None:
        key = self._zone_at(e.x, e.y)
        if key is not None:
            self._set_current(key[0])
            self._select_zone(key[1])
            self.focus_selected()

    def _zone_menu(self, e) -> None:
        key = self._zone_at(e.x, e.y)
        if key is not None:
            self._show_zone_menu(*key, e.x_root, e.y_root)

    def _view_menu(self, key: tuple[int, int], x_root: int, y_root: int) -> None:
        """Right-click on a zoom view on the desktop."""
        self._show_zone_menu(*key, x_root, y_root)

    def _show_zone_menu(self, zm: int, i: int, x_root: int, y_root: int) -> None:
        self._set_current(zm)
        self._select_zone(i)
        m = tk.Menu(self.root, tearoff=False, bg=PANEL, fg=FG, activebackground=ACCENT)
        alive = self._slot_alive(i)
        zoom = bool(alive and self.slots[i].crop)
        m.add_command(label="Use window (peek)" if zoom else "Focus window", command=self.focus_selected,
                      state="normal" if alive else "disabled")
        m.add_checkbutton(label="Always on top", variable=self.topmost_var, command=self._topmost_toggled,
                          state="normal" if alive else "disabled")
        m.add_command(label="Pick window on screen...", command=self.pick_on_screen)
        m.add_command(label="Change zoom area..." if zoom else "Zoom into an area of a window...",
                      command=self.zoom_area)
        if zoom:
            m.add_command(label="Show whole window (tile it)", command=self.unzoom_selected)
        m.add_separator()
        m.add_command(label="Clear zone", command=self.clear_selected)
        m.add_separator()
        m.add_command(label="Split zone  left | right", command=lambda: self.split_selected(True))
        m.add_command(label="Split zone  top / bottom", command=lambda: self.split_selected(False))
        m.add_command(label="Remove zone", command=self.remove_selected_zone,
                      state="normal" if len(self.layout.zones) > 1 else "disabled")
        m.add_command(label="Tip: Ctrl+drag in the preview draws a new zone", state="disabled")
        m.tk_popup(x_root, y_root)

    # ========================================================== actions
    def apply(self, quiet: bool = False, only: set[int] | None = None) -> None:
        """Arrange the windows of every monitor (or just the monitors in `only`)."""
        moved, failed, missing = 0, [], 0
        order, used = [], set()
        for m, i, s in list(self._assigned()):
            if only is not None and m not in only:
                continue
            if not self.be.is_window(s.hwnd):
                missing += 1
                continue
            target = self._target(i, m)
            self._remember(s.hwnd)
            if self.be.place(s.hwnd, target):
                moved += 1
                order.append(s)
                used.add(m)
            else:
                failed.append(_short_app(s.exe))
        # zoom zones: their window stays where it is, it only must not be minimized (DWM can't show it)
        zooms = 0
        for m, _i, s in self._zooms():
            if only is not None and m not in only:
                continue
            if not self.be.is_window(s.hwnd):
                missing += 1
                continue
            if self.be.is_minimized(s.hwnd):
                self.be.unminimize(s.hwnd)
                self.be.send_to_back(s.hwnd)
            zooms += 1
            used.add(m)
        # z-order: everything tiled comes up together; topmost flags last
        for s in order:
            self.be.raise_no_focus(s.hwnd)
        for s in order:
            self.be.set_topmost(s.hwnd, s.topmost)
        self._save_settings()
        self.draw_preview()
        self.views.lift_all()
        self._refresh_handles()
        if quiet:
            return
        what = " and ".join(p for p in (f"{moved} window(s)" if moved or not zooms else "",
                                        f"{zooms} zoom view(s)" if zooms else "") if p)
        if len(used) > 1:
            msg = f"Arranged {what} on {len(used)} monitors."
        else:
            msg = f"Arranged {what} on monitor {(min(used) if used else self.cur) + 1}."
        if missing:
            msg += f"  {missing} assigned window(s) are closed."
        if failed:
            msg += (f"  Could not move: {', '.join(failed)} (apps running as Administrator need "
                    f"Windower to run as Administrator too).")
        self.set_status(msg, warn=bool(failed or missing))
        if moved == 0 and zooms == 0 and not failed:
            self.set_status("Nothing to arrange yet - drag windows from the list onto the zones.", warn=True)
        elif self.minimize_var.get():
            self.root.iconify()

    def bring_all_front(self) -> None:
        n, failed = 0, []
        for _m, _i, s in self._assigned():
            if not self.be.is_window(s.hwnd):
                continue
            if self.be.raise_no_focus(s.hwnd):
                n += 1
            else:
                failed.append(_short_app(s.exe))
        self.views.lift_all()
        for h in self.handles:           # grips stay above the windows they resize
            h.lift()
        msg = f"Brought {n} window(s) to the front."
        if failed:
            msg += (f"  Could not raise: {', '.join(failed)} (not responding, or running as Administrator "
                    f"while Windower isn't).")
        self.set_status(msg, warn=bool(failed))

    def focus_selected(self) -> None:
        if self.selected_zone is not None:
            self._focus_zone(self.cur, self.selected_zone)

    def _focus_zone(self, m: int, i: int) -> bool:
        """Focus the window of a zone; for a zoom zone, bring the window over the view to use it."""
        if not self._slot_alive(i, m):
            return False
        s = self.screens[m].slots[i]
        if s.crop and (m, i) in self.views.views:
            self.views.peek((m, i))
        else:
            self.be.focus(s.hwnd)
        return True

    def _topmost_toggled(self) -> None:
        i = self.selected_zone
        if i is None or not self.slots[i]:
            self.topmost_var.set(False)
            return
        s = self.slots[i]
        s.topmost = bool(self.topmost_var.get())
        if not s.crop and self.be.is_window(s.hwnd):   # a zoom view's own window is what stays on top
            self.be.set_topmost(s.hwnd, s.topmost)
        self.draw_preview()

    def _remember(self, hwnd: int) -> None:
        """Record where a window is before Windower moves it for the first time."""
        if hwnd not in self.original:
            self.original[hwnd] = self.be.save_placement(hwnd)

    def restore_originals(self) -> None:
        self.views.end_peek()
        n = 0
        monitors = self.be.get_monitors()
        for hwnd, p in list(self.original.items()):
            if self.be.is_window(hwnd):
                self.be.set_topmost(hwnd, False)
                if p.rect is not None:  # never send a window back somewhere off-screen
                    p = replace(p, rect=fit_on_screen(p.rect, monitors))
                self.be.restore_placement(hwnd, p)
                n += 1
        self.original.clear()
        for h in self.handles:
            h.hide()
        for _m, _i, s in self._assigned():
            s.topmost = False
        self.keep_var.set(False)
        self._select_zone(self.selected_zone)
        self.set_status(f"Restored {n} window(s) to where they were before Windower moved them. "
                        f"('Keep windows in place' was turned off.)")

    # --------------------------------------------------------- pick mode
    def pick_on_screen(self, zoom: bool = False) -> None:
        """Click a window on the desktop to put it in the selected zone
        (zoom=True: then drag over the part of it the zone should show)."""
        i = self.selected_zone
        if i is None:
            self.set_status("Select a zone first.", warn=True)
            return
        self._picking = {"m": self.cur, "zone": i, "left": 150, "start_fg": self.be.foreground(), "zoom": zoom}
        what = "to zoom into for" if zoom else "in"
        self.set_status(f"Click on the window you want {what} {self._zone_name(self.cur, i)}...  (15 s)")
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
            if p["zoom"]:
                self._pick_area(p["m"], p["zone"], fg)
                return
            self.root.deiconify()
            self.root.lift()
            self._set_current(p["m"])
            self.assign(p["zone"], wins[fg])
            return
        if p["left"] <= 0:
            self._picking = None
            self.root.deiconify()
            self.set_status("Pick cancelled (timed out).", warn=True)
            return
        self.root.after(100, self._pick_poll)

    # -------------------------------------------------------- zoom views
    def zoom_area(self) -> None:
        """Make the selected zone show just part of a window, zoomed to fit the zone.

        The window is the zone's own one, else the one selected in the list, else
        you click it on the desktop; then you drag over the part you want to see."""
        i = self.selected_zone
        if i is None:
            self.set_status("Select a zone first.", warn=True)
            return
        s = self.slots[i]
        hwnd = s.hwnd if s and self._slot_alive(i) else 0
        if not hwnd:
            sel = self.tree.selection()
            w = self._window(int(sel[0])) if sel else None
            hwnd = w.hwnd if w and self.be.is_window(w.hwnd) else 0
        if hwnd:
            self._pick_area(self.cur, i, hwnd)
        else:
            self.pick_on_screen(zoom=True)

    def _pick_area(self, m: int, i: int, hwnd: int) -> None:
        if self._area_picker:
            return
        self.views.end_peek()
        self.be.focus(hwnd)              # the window must be visible to drag over it
        s = self.screens[m].slots[i]
        current = s.crop if s and s.hwnd == hwnd else None
        self.root.iconify()
        self.set_status("Drag over the part of the window you want to see (Esc cancels).")

        def done(rect: Rect | None) -> None:
            self._area_picker = None
            self.root.deiconify()
            self.root.lift()
            if rect:
                self._set_zoom(m, i, hwnd, rect)
            else:
                self.set_status("Zoom cancelled.")

        def start() -> None:
            if self.be.is_window(hwnd):
                self._area_picker = AreaPicker(self.root, self.be, hwnd, done, current)
            else:
                done(None)

        self.root.after(250, start)      # let the window come to the front first

    def _set_zoom(self, m: int, i: int, hwnd: int, crop: Rect) -> None:
        """Zone i of monitor m now shows `crop` (client coords) of window hwnd."""
        wins = {w.hwnd: w for w in self.be.list_windows()}
        if hwnd not in wins:
            self.set_status("That window can't be zoomed (it was closed or is a system window).", warn=True)
            return
        self.windows = list(wins.values())
        old = self.screens[m].slots[i]
        if old and old.topmost and not old.crop and self.be.is_window(old.hwnd):
            self.be.set_topmost(old.hwnd, False)      # the zoom view stays on top instead
        slot = old if old and old.hwnd == hwnd else Slot.from_window(wins[hwnd])
        slot.topmost = bool(old and old.topmost)
        slot.crop = crop
        self.screens[m].slots[i] = slot
        self._set_current(m)
        self._select_zone(i)             # redraws the preview, which creates/updates the zoom view
        self.views.lift_all()
        self.refresh_windows(force=True)
        self._refresh_handles()
        t = self._target(i, m)
        factor = min(t.w / crop.w, t.h / crop.h)
        self.set_status(f"{self._zone_name(m, i).capitalize()} shows a {crop.w}x{crop.h} area of "
                        f"{_short_app(slot.exe)} ({factor:.1f}x). Click it to use the window; keep the "
                        f"window open and not minimized.")

    def unzoom_selected(self) -> None:
        """Turn the selected zoom zone back into a normal zone (the whole window is tiled there)."""
        i = self.selected_zone
        s = self.slots[i] if i is not None else None
        if not s or not s.crop:
            return
        for m, k, t in list(self._assigned()):    # a window is tiled in one zone only
            if t.hwnd == s.hwnd:
                self.screens[m].slots[k] = None
        s.crop = None
        if self._already_applied():
            self.apply(quiet=True, only={self.cur})
        self._select_zone(i)
        self.refresh_windows(force=True)

    # ======================================================== workspaces
    def _refresh_workspaces(self) -> None:
        names = sorted(self.store.workspaces)
        self.ws_cb.configure(values=names)
        if self.ws_var.get() not in names:
            self.ws_var.set(names[0] if names else "")

    def save_workspace(self) -> None:
        if not any(True for _ in self._all_slots()):
            messagebox.showinfo("Windower", "Assign some windows to zones first.")
            return
        name = simpledialog.askstring("Save workspace", "Workspace name (e.g. 'Coding', 'Study', 'Streaming'):",
                                      initialvalue=self.ws_var.get() or "", parent=self.root)
        if not name:
            return
        name = name.strip()
        self.store.put_workspace(name, {
            # every monitor's layout and windows
            "screens": [{"monitor": m, "device": self.monitors[m].name, "layout": scr.layout.to_dict(),
                         "slots": [s.signature() if s else None for s in scr.slots]}
                        for m, scr in enumerate(self.screens)],
            "monitor": self.cur,
            "gap": self.gap(),
            # the current monitor in the old one-monitor format, for older Windower versions
            "layout": self.layout.to_dict(),
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

    def _monitor_for(self, saved: dict, used: set[int], legacy: bool) -> int | None:
        """Which connected monitor a saved screen belongs on: same device name, else same position."""
        names = [mo.name for mo in self.monitors]
        dev = saved.get("device")
        if dev in names and names.index(dev) not in used:
            return names.index(dev)
        k = int(saved.get("monitor", 0))
        if legacy:  # old one-monitor workspaces always load somewhere
            k = min(max(k, 0), len(self.monitors) - 1)
        return k if 0 <= k < len(self.monitors) and k not in used else None

    def load_workspace(self) -> None:
        name = self.ws_var.get()
        data = self.store.workspaces.get(name)
        if not data:
            return
        legacy = "screens" not in data
        saved = data.get("screens") or [{"monitor": data.get("monitor", 0), "layout": data["layout"],
                                         "slots": data.get("slots", [])}]
        self._refresh_monitors(select=self.cur)   # monitors may have been plugged in/out since start
        self.gap_var.set(int(data.get("gap", 0)))
        sigs_by_m: dict[int, list] = {}
        skipped = 0
        for sd in saved:
            m = self._monitor_for(sd, set(sigs_by_m), legacy)
            if m is None:
                skipped += 1
                continue
            lay = Layout.from_dict(sd["layout"])
            existing = self._find_layout(lay.name)
            if existing:
                lay.builtin = existing.builtin
            scr = self.screens[m]
            for s in scr.slots:   # windows leaving this monitor shouldn't stay on top
                if s and s.topmost and not s.crop and self.be.is_window(s.hwnd):
                    self.be.set_topmost(s.hwnd, False)
            scr.layout = lay
            scr.adjusted = bool(existing) and [
                (round(z.x, 4), round(z.y, 4), round(z.w, 4), round(z.h, 4)) for z in existing.zones] != [
                (round(z.x, 4), round(z.y, 4), round(z.w, 4), round(z.h, 4)) for z in lay.zones]
            scr.slots = [None] * len(lay.zones)
            scr.selected = 0 if lay.zones else None
            sigs = list(sd.get("slots", []))
            sigs_by_m[m] = sigs + [None] * (len(lay.zones) - len(sigs))
        if not sigs_by_m:
            self.set_status(f"Workspace '{name}': none of its monitors are connected.", warn=True)
            return
        cur = int(data.get("monitor", 0))
        self.cur = cur if cur in sigs_by_m else min(sigs_by_m)
        self._refresh_layouts()
        missing = self._match_slots(sigs_by_m)
        launched = 0
        if missing and self.launch_var.get():
            for m, i in missing:
                sig = sigs_by_m[m][i]
                path = sig.get("exe_path") if sig else ""
                if path and self.be.launch(path):
                    launched += 1
        self._select_zone(self.selected_zone)
        self.refresh_windows(force=True)
        self.apply(quiet=True, only=set(sigs_by_m))
        gone = f"  {skipped} saved monitor(s) are not connected." if skipped else ""
        if launched:
            self._pending_launch = {"sigs": sigs_by_m, "tries": 20}
            self.set_status(f"Workspace '{name}': started {launched} app(s), waiting for their windows...{gone}")
            self.root.after(1000, self._wait_for_launched)
        else:
            extra = f"  {len(missing)} app(s) not running." if missing else ""
            self.set_status(f"Workspace '{name}' loaded.{extra}{gone}", warn=bool(missing or skipped))

    def _match_slots(self, sigs_by_m: dict[int, list]) -> list[tuple[int, int]]:
        """Fill empty slots from saved signatures; returns the (monitor, zone)s still missing."""
        wins = self.be.list_windows()
        self.windows = wins
        taken = {s.hwnd for _m, _i, s in self._assigned() if self.be.is_window(s.hwnd)}
        missing = []
        for m, sigs in sigs_by_m.items():
            if m >= len(self.screens):
                continue
            slots = self.screens[m].slots
            for i, sig in enumerate(sigs):
                if not sig or i >= len(slots):
                    continue
                if self._slot_alive(i, m):
                    continue
                crop = crop_from(sig.get("crop"))
                w = match_window(sig, wins, set() if crop else taken)   # zooms may share a window
                if w:
                    slot = Slot.from_window(w)
                    slot.topmost = bool(sig.get("topmost"))
                    slot.crop = crop
                    slots[i] = slot
                    if not crop:
                        taken.add(w.hwnd)
                else:
                    missing.append((m, i))
        return missing

    def _wait_for_launched(self) -> None:
        p = self._pending_launch
        if not p:
            return
        p["tries"] -= 1
        missing = self._match_slots(p["sigs"])
        self.apply(quiet=True, only=set(p["sigs"]))
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
            for m, i, s in list(self._all_slots()):
                if not self.be.is_window(s.hwnd):
                    continue
                title = self.be.get_title(s.hwnd)
                if title and title != s.title:
                    s.title = title
                    changed = True
                if (self.keep_var.get() and not s.crop and s.hwnd in self.original and not self._busy_dragging()
                        and not self.be.is_minimized(s.hwnd) and not self.be.mouse_button_down()):
                    target = self._target(i, m)
                    if not self.be.get_rect(s.hwnd).close_to(target, 6):
                        self.be.place(s.hwnd, target)
            if changed and not self._zone_drag and not self._tree_drag:
                self.draw_preview()
                if self.selected_zone is not None:
                    self._select_zone(self.selected_zone)
        finally:
            self.root.after(TICK_MS, self._tick)

    def on_close(self) -> None:
        for _m, _i, s in self._assigned():  # don't leave windows stuck on top after we quit
            if s.topmost and self.be.is_window(s.hwnd):
                self.be.set_topmost(s.hwnd, False)
        self._save_settings()
        self.views.close_all()           # also puts a peeked window back
        self.overlay.hide()
        self.snap_overlay.hide()
        for h in self.handles:
            h.hide()
        try:
            self.events.stop()
        except Exception:
            pass
        self.root.destroy()

    # ====================================================== linked edges
    def _busy_dragging(self) -> bool:
        return bool(self._grip or self._movesize or any(h.dragging for h in self.handles))

    def _move_grip(self, edges_v: list, edges_h: list, fx: float, fy: float, live: bool) -> None:
        """Move dividers/node of the current monitor to fractional position (fx, fy) and update everything."""
        changed = False
        if edges_v:
            before = edge_coord(self.layout.zones[edges_v[0][0]], edges_v[0][1])
            changed |= abs(move_edges(self.layout.zones, edges_v, fx) - before) > 1e-6
        if edges_h:
            before = edge_coord(self.layout.zones[edges_h[0][0]], edges_h[0][1])
            changed |= abs(move_edges(self.layout.zones, edges_h, fy) - before) > 1e-6
        if changed or not live:
            self._layout_changed(live=live, adjusted=True if changed else None)

    def _layout_changed(self, live: bool, skip: int | None = None, adjusted: bool | None = True) -> None:
        """Zones of the current monitor were resized: redraw, move the real windows, refresh handles."""
        if adjusted is not None:
            self.layout_adjusted = self.layout_adjusted or adjusted
        if self._already_applied():
            self._place_all(fast=live, skip=skip)
        self.draw_preview()
        if live:
            if self.handles[self.cur].visible:
                self.handles[self.cur].reposition(self.layout.zones)
        else:
            self._refresh_layouts()
            self.root.after_idle(self._refresh_handles)
            if self.selected_zone is not None:
                self._select_zone(self.selected_zone)

    def _place_all(self, fast: bool, skip: int | None = None, m: int | None = None) -> None:
        m = self.cur if m is None else m
        for i, s in enumerate(self.screens[m].slots):
            if not s or s.crop or s.hwnd == skip or not self.be.is_window(s.hwnd):
                continue
            target = self._target(i, m)
            if fast and self.be.get_rect(s.hwnd).close_to(target, 1):
                continue
            self._remember(s.hwnd)
            self.be.place(s.hwnd, target, fast=fast)

    def _handle_drag(self, m: int, edges_v: list, edges_h: list, x_root: int, y_root: int,
                     finished: bool) -> None:
        self._set_current(m)
        a = self.monitor().work
        self._move_grip(edges_v, edges_h, (x_root - a.x) / a.w, (y_root - a.y) / a.h, live=not finished)

    def _handles_toggled(self) -> None:
        self._save_settings()
        self._refresh_handles()
        if self.handles_var.get() and not any(self._already_applied(m) for m in range(len(self.screens))):
            self.set_status("Resize handles appear on the desktop once the layout is applied.")

    def _refresh_handles(self) -> None:
        if any(h.dragging for h in self.handles):
            return
        for m, h in enumerate(self.handles):
            if self.handles_var.get() and self._already_applied(m):
                h.show(self.screens[m].layout.zones, self.monitors[m].work)
                h.lift()
            else:
                h.hide()

    def _sticky_resize(self, i: int, r: Rect, live: bool, start: Rect | None = None) -> None:
        """The user resized the window of zone i (current monitor) to r: drag the shared edges along.

        Only the sides the user actually grabbed (changed since `start`) count, so an
        app that refuses to fit its zone (minimum size) doesn't drag other edges.
        """
        t = self._target(i)
        a = self.monitor().work
        deltas = {"L": (r.x - t.x) / a.w, "R": (r.x + r.w - t.x - t.w) / a.w,
                  "T": (r.y - t.y) / a.h, "B": (r.y + r.h - t.y - t.h) / a.h}
        if start is not None:
            grabbed = {"L": r.x != start.x, "R": r.x + r.w != start.x + start.w,
                       "T": r.y != start.y, "B": r.y + r.h != start.y + start.h}
        else:
            grabbed = dict.fromkeys("LRTB", True)
        changed = False
        for side, dv in deltas.items():
            if not grabbed[side] or abs(dv) * (a.w if side in "LR" else a.h) < 2:
                continue
            group = edge_group(self.layout.zones, i, side)
            if not group.interior:          # screen edge: stays pinned, no new gaps
                continue
            before = group.coord
            changed |= abs(move_edges(self.layout.zones, group.edges, before + dv) - before) > 1e-6
        if changed or not live:
            self._layout_changed(live=live, skip=self.slots[i].hwnd if live else None,
                                 adjusted=True if changed else None)

    # ================================================= desktop events
    def _pump_events(self) -> None:
        try:
            for ev in self.events.poll():
                kind = ev[0]
                if kind == "movesize_start":
                    self._on_movesize_start(ev[1])
                elif kind == "movesize_end":
                    self._on_movesize_end(ev[1])
                elif kind == "hotkey":
                    self._on_hotkey(ev[1])
                elif kind == "hotkey_failed":
                    combos = ", ".join(hotkeys.describe(h, self.hotkey_var.get()) for h in ev[1][:4])
                    more = "..." if len(ev[1]) > 4 else ""
                    self.set_status(f"Some hotkeys are already used by another program: {combos}{more}", warn=True)
            if self._movesize:
                self._movesize_poll()
        except Exception as ex:  # keep the loop alive whatever happens
            self.set_status(f"Event error: {ex}", warn=True)
        finally:
            self.root.after(EVENT_MS, self._pump_events)

    def _find(self, hwnd: int) -> tuple[int, int] | None:
        """(monitor, zone) that holds this window."""
        return next(((m, i) for m, i, s in self._assigned() if s.hwnd == hwnd), None)

    def _on_movesize_start(self, hwnd: int) -> None:
        hwnd = self.be.root_window(hwnd)
        if not self.be.is_window(hwnd):
            return
        key = self._find(hwnd)
        if key is not None and hwnd not in self.original:
            key = None                        # assigned but never applied: not tiled yet
        self._movesize = {"hwnd": hwnd, "zone": key, "start": self.be.get_rect(hwnd), "mode": None}

    def _movesize_poll(self) -> None:
        ms = self._movesize
        hwnd = ms["hwnd"]
        if not self.be.is_window(hwnd):
            self._movesize = None
            self.snap_overlay.hide()
            return
        r = self.be.get_rect(hwnd)
        st = ms["start"]
        if ms["mode"] is None:
            if abs(r.w - st.w) > 2 or abs(r.h - st.h) > 2:
                ms["mode"] = "resize"
            elif abs(r.x - st.x) > 2 or abs(r.y - st.y) > 2:
                ms["mode"] = "move"
        if ms["mode"] == "resize":
            if ms["zone"] is not None and self.linked_var.get():
                m, i = ms["zone"]
                self._set_current(m)          # linked edges work on that monitor's layout
                self._sticky_resize(i, r, live=True, start=ms["start"])
        elif self.shiftsnap_var.get():
            if self.be.shift_down():
                if not self.snap_overlay.visible:
                    self._snap_keys = [(m, i) for m, scr in enumerate(self.screens)
                                       for i in range(len(scr.layout.zones))]
                    self.snap_overlay.show([self._target(i, m) for m, i in self._snap_keys],
                                           numbers=[i for _m, i in self._snap_keys])
                self.snap_overlay.highlight(self.snap_overlay.zone_at(*self.be.cursor_pos()))
            elif self.snap_overlay.visible:
                self.snap_overlay.hide()

    def _on_movesize_end(self, hwnd: int) -> None:
        ms = self._movesize
        if not ms:
            return
        self._movesize_poll()
        ms = self._movesize
        self._movesize = None
        if not ms:
            return
        target = self.snap_overlay.current if self.snap_overlay.visible else None
        self.snap_overlay.hide()
        if ms["mode"] == "resize" and ms["zone"] is not None and self.linked_var.get():
            m, i = ms["zone"]
            self._set_current(m)
            self._sticky_resize(i, self.be.get_rect(ms["hwnd"]), live=False, start=ms["start"])
            self.set_status("Resized - neighbouring windows followed. 'Save layout as...' keeps these proportions.")
        elif target is not None and target < len(self._snap_keys):
            self.put_window_in_zone(ms["hwnd"], *self._snap_keys[target])

    def put_window_in_zone(self, hwnd: int, m: int, zone: int) -> bool:
        """Snap a (real) window into zone `zone` of monitor m; if the zone is taken the two windows swap."""
        if not 0 <= m < len(self.screens) or zone is None or zone >= len(self.screens[m].slots):
            return False
        wins = {w.hwnd: w for w in self.be.list_windows()}
        win = wins.get(hwnd)
        if not win:
            return False
        self.windows = list(wins.values())
        old = self._find(hwnd)
        if old == (m, zone):
            self._place_all(fast=False, m=m)
            return True
        dest = self.screens[m].slots
        displaced = dest[zone]
        new_slot = Slot.from_window(win)
        if old is not None:
            om, oi = old
            new_slot.topmost = self.screens[om].slots[oi].topmost
            self.screens[om].slots[oi] = displaced
        elif displaced and displaced.topmost and not displaced.crop and self.be.is_window(displaced.hwnd):
            self.be.set_topmost(displaced.hwnd, False)
        dest[zone] = new_slot
        for h in {hwnd} | ({displaced.hwnd} if displaced and old is not None else set()):
            if self.be.is_window(h):
                self._remember(h)
        for km, ki in {(m, zone), old} - {None}:
            s = self.screens[km].slots[ki]
            if s and not s.crop and self.be.is_window(s.hwnd):
                self.be.place(s.hwnd, self._target(ki, km))
                self.be.set_topmost(s.hwnd, s.topmost)
        self._set_current(m)
        self._select_zone(zone)
        self.refresh_windows(force=True)
        self._refresh_handles()
        self.set_status(f"Snapped {win.app} into {self._zone_name(m, zone)}" +
                        (f" (swapped with {_short_app(displaced.exe)})" if displaced and old is not None else "."))
        return True

    # ========================================================== hotkeys
    def _apply_hotkeys(self, announce: bool = True) -> None:
        mod = self.hotkey_var.get()
        self.events.set_hotkeys(hotkeys.build(mod))
        self._save_settings()
        if announce:
            self.set_status("Hotkeys off." if mod == "Off" else
                            f"Hotkeys: {mod} + 1-9 / arrows / Enter / W / H / Z  (press ? for the full list)")

    def show_hotkey_help(self) -> None:
        t = tk.Toplevel(self.root)
        t.title("Windower - hotkeys")
        t.configure(bg=BG, padx=16, pady=14)
        t.transient(self.root)
        tk.Label(t, text="Global hotkeys (work in any app)", bg=BG, fg=FG,
                 font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        for r, (combo, what) in enumerate(hotkeys.help_rows(self.hotkey_var.get()), start=1):
            tk.Label(t, text=combo, bg=BG, fg=ACCENT, font=("Consolas", 10, "bold")).grid(
                row=r, column=0, sticky="w", padx=(0, 16), pady=2)
            tk.Label(t, text=what, bg=BG, fg=FG).grid(row=r, column=1, sticky="w", pady=2)
        tips = ("Linked edges: drag the border between two tiled windows and the neighbour follows.\n"
                "Resize handles: grips on the lines/intersections between windows on the desktop.\n"
                "With several monitors, zone numbers refer to the monitor the active window is on.")
        tk.Label(t, text=tips, bg=BG, fg=MUTED, justify="left").grid(
            row=99, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Button(t, text="Close", command=t.destroy).grid(row=100, column=1, sticky="e", pady=(10, 0))

    def _active_zone(self) -> tuple[int, int] | None:
        fg = self.be.foreground()
        return self._find(self.be.root_window(fg)) if fg else None

    def _screen_here(self) -> int:
        """The monitor the user is working on: the one the active window is on (else the panel's)."""
        fg = self.be.foreground()
        if not fg:
            return self.cur
        hwnd = self.be.root_window(fg)
        key = self._find(hwnd)
        if key is not None:
            return key[0]
        if hwnd == self.be.root_window(self.root.winfo_id()) or not self.be.is_window(hwnd):
            return self.cur
        r = self.be.get_rect(hwnd)
        k = monitor_at(self.monitors, r.x + r.w // 2, r.y + r.h // 2)
        return self.cur if k is None else k

    def _on_hotkey(self, hid: int) -> None:
        if hid not in hotkeys.ACTIONS:
            return
        action, arg = hotkeys.ACTIONS[hid][:2]
        if action == "focus_zone":
            m = self._screen_here()
            if arg < len(self.screens[m].slots) and self._focus_zone(m, arg):
                self._set_current(m)
                self._select_zone(arg)
        elif action == "move_to_zone":
            fg = self.be.root_window(self.be.foreground() or 0)
            m = self._screen_here()
            if arg < len(self.screens[m].slots) and fg and not self.put_window_in_zone(fg, m, arg):
                self.set_status("That window can't be tiled (it may be Windower itself or a system window).",
                                warn=True)
        elif action in ("focus_dir", "swap_dir"):
            cur = self._active_zone()
            if cur is None:
                # the active window isn't tiled: arrows just jump into the tiled set on this monitor
                m = self._screen_here()
                k = self.screens[m].selected or 0
                if action == "focus_dir" and k < len(self.screens[m].slots):
                    self._focus_zone(m, k)
                return
            # zones of every monitor, in desktop pixels: arrows cross from one monitor to the next
            keys = [(m, i) for m, scr in enumerate(self.screens) for i in range(len(scr.layout.zones))]
            j = neighbour([self._target(i, m) for m, i in keys], keys.index(cur), arg)
            if j is None:
                return
            (cm, ci), (jm, ji) = cur, keys[j]
            if action == "focus_dir":
                if self._focus_zone(jm, ji):
                    self._set_current(jm)
                    self._select_zone(ji)
            else:
                a, b = self.screens[cm].slots, self.screens[jm].slots
                a[ci], b[ji] = b[ji], a[ci]
                for km, ki in (cur, keys[j]):
                    s = self.screens[km].slots[ki]
                    if s and not s.crop and self.be.is_window(s.hwnd):
                        self._remember(s.hwnd)
                        self.be.place(s.hwnd, self._target(ki, km))
                self._set_current(jm)
                self._select_zone(ji)
        elif action == "apply":
            self.apply()
        elif action == "toggle_panel":
            if self.root.state() in ("iconic", "withdrawn"):
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
            else:
                self.root.iconify()
        elif action == "toggle_handles":
            self.handles_var.set(not self.handles_var.get())
            self._handles_toggled()
        elif action == "show_zones":
            self.identify()


def _short_app(exe: str) -> str:
    return exe[:-4] if exe.lower().endswith(".exe") else (exe or "?")


def _trim(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"
