"""
Windower control panel.

Flow:  pick a layout  ->  put windows into its zones  ->  Apply.
The real application windows are moved/resized, so every app keeps running
live and stays fully interactive (just click into it).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import hotkeys
from .desktop import DesktopHandles, SnapOverlay
from .editor import LayoutEditor
from .model import (Layout, Monitor, Rect, Slot, WindowInfo, Zone, dividers, edge_coord, edge_group,
                    match_window, move_edges, node_edges, nodes)
from .presets import PRESETS
from .storage import Store
from .ui_common import (ACCENT, BG, CANVAS_BG, FG, MUTED, PANEL, SELECT, Overlay,
                        blend, zone_color)

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
        self.monitors: list[Monitor] = self.be.get_monitors()
        self.layout: Layout = self._find_layout(s.get("layout", "2 columns")) or self._default_layout()
        self.layout_adjusted = False
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
        self._movesize: dict | None = None       # a window the user is dragging/resizing on the desktop
        self._grip: dict | None = None           # divider/node being dragged in the preview

        self.events = self.be.EventSource()
        self.snap_overlay = SnapOverlay(root, backend)
        self.handles = DesktopHandles(root, backend, self._handle_drag)

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
        self._refresh_monitors(select=int(s.get("monitor", 0)))
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
        self.monitor_cb = ttk.Combobox(head, state="readonly", width=24, textvariable=self.monitor_var)
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
        ttk.Button(lrow, text="Show zones", command=self.identify).pack(side="right")
        self.reset_btn = ttk.Button(lrow, text="Reset sizes", command=self.reset_layout_sizes)
        self.reset_btn.pack(side="right", padx=6)
        self.saveas_btn = ttk.Button(lrow, text="Save sizes as...", command=self.save_layout_as)
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
            "linked_edges": self.linked_var.get(), "shift_snap": self.shiftsnap_var.get(),
            "desktop_handles": self.handles_var.get(), "hotkey_modifier": self.hotkey_var.get(),
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
        self._refresh_handles()

    def _gap_changed(self) -> None:
        self._save_settings()
        self.draw_preview()

    # =========================================================== layouts
    def _refresh_layouts(self) -> None:
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
            self.set_status(f"Layout '{lay.name}': {n} zone(s). Press Apply to arrange the windows.")
        if self._already_applied():
            self.apply(quiet=True)
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
        """Undo divider/node/edge drags: back to the saved proportions."""
        fresh = self._find_layout(self.layout.name)
        if not fresh or len(fresh.zones) != len(self.layout.zones):
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
        # dividers (lines between zones) and nodes (where lines meet) - drag them to resize
        divs = dividers(self.layout.zones)
        active = self._grip["edges"] if self._grip else set()
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
        for n in nodes(self.layout.zones, divs):
            x, y = ox + n.x * w, oy + n.y * h
            v, hh = node_edges(n)
            hot = bool(set(v + hh) & active)
            r = 8 if hot else 6
            c.create_oval(x - r, y - r, x + r, y + r, fill="#f1b44c", outline=SELECT, width=2)
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
    def _grip_at(self, cx: float, cy: float) -> dict | None:
        """Node or divider under the pointer in the preview."""
        ox, oy, w, h = self._preview_geom()
        divs = dividers(self.layout.zones)
        for n in nodes(self.layout.zones, divs):
            if abs(ox + n.x * w - cx) <= PREVIEW_GRIP + 2 and abs(oy + n.y * h - cy) <= PREVIEW_GRIP + 2:
                v, hh = node_edges(n)
                return {"v": v, "h": hh, "edges": set(v + hh), "kind": "node"}
        for d in divs:
            if d.axis == "v":
                near = abs(ox + d.coord * w - cx) <= PREVIEW_GRIP and oy + d.span[0] * h <= cy <= oy + d.span[1] * h
            else:
                near = abs(oy + d.coord * h - cy) <= PREVIEW_GRIP and ox + d.span[0] * w <= cx <= ox + d.span[1] * w
            if near:
                v = d.edges if d.axis == "v" else []
                hh = d.edges if d.axis == "h" else []
                return {"v": v, "h": hh, "edges": set(d.edges), "kind": d.axis}
        return None

    def _canvas_hover(self, e) -> None:
        if self._grip or self._zone_drag:
            return
        g = self._grip_at(e.x, e.y)
        cur = {"node": "fleur", "v": "sb_h_double_arrow", "h": "sb_v_double_arrow"}.get(g["kind"]) if g else ""
        try:
            self.canvas.configure(cursor=cur)
        except tk.TclError:
            pass

    def _zone_press(self, e) -> None:
        g = self._grip_at(e.x, e.y)
        if g:
            self._grip = g
            self.draw_preview()
            return
        i = self._zone_at(e.x, e.y)
        self._zone_drag = {"from": i, "x": e.x, "y": e.y, "active": False} if i is not None else None
        self._select_zone(i)

    def _zone_motion(self, e) -> None:
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
        self._refresh_handles()
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
        self.handles.hide()
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
        if existing:
            lay.builtin = existing.builtin
        self.layout = lay
        self.layout_adjusted = bool(existing) and [
            (round(z.x, 4), round(z.y, 4), round(z.w, 4), round(z.h, 4)) for z in existing.zones] != [
            (round(z.x, 4), round(z.y, 4), round(z.w, 4), round(z.h, 4)) for z in lay.zones]
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
                if (self.keep_var.get() and s.hwnd in self.original and not self._busy_dragging()
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
        self.snap_overlay.hide()
        self.handles.hide()
        try:
            self.events.stop()
        except Exception:
            pass
        self.root.destroy()

    # ====================================================== linked edges
    def _busy_dragging(self) -> bool:
        return bool(self._grip or self._movesize or self.handles.dragging)

    def _move_grip(self, edges_v: list, edges_h: list, fx: float, fy: float, live: bool) -> None:
        """Move dividers/node to fractional position (fx, fy) and update everything."""
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
        """Zones were resized: redraw, move the real windows, refresh handles."""
        if adjusted is not None:
            self.layout_adjusted = self.layout_adjusted or adjusted
        if self._already_applied():
            self._place_all(fast=live, skip=skip)
        self.draw_preview()
        if live:
            if self.handles.visible:
                self.handles.reposition(self.layout.zones)
        else:
            self._refresh_layouts()
            self.root.after_idle(self._refresh_handles)
            if self.selected_zone is not None:
                self._select_zone(self.selected_zone)

    def _place_all(self, fast: bool, skip: int | None = None) -> None:
        for i, s in enumerate(self.slots):
            if not s or s.hwnd == skip or not self.be.is_window(s.hwnd):
                continue
            target = self._target(i)
            if fast and self.be.get_rect(s.hwnd).close_to(target, 1):
                continue
            if s.hwnd not in self.original:
                self.original[s.hwnd] = self.be.get_rect(s.hwnd)
            self.be.place(s.hwnd, target, fast=fast)

    def _handle_drag(self, edges_v: list, edges_h: list, x_root: int, y_root: int, finished: bool) -> None:
        a = self.monitor().work
        self._move_grip(edges_v, edges_h, (x_root - a.x) / a.w, (y_root - a.y) / a.h, live=not finished)

    def _handles_toggled(self) -> None:
        self._save_settings()
        self._refresh_handles()
        if self.handles_var.get() and not self._already_applied():
            self.set_status("Resize handles appear on the desktop once the layout is applied.")

    def _refresh_handles(self) -> None:
        if self.handles.dragging:
            return
        if self.handles_var.get() and self._already_applied():
            self.handles.show(self.layout.zones, self.monitor().work)
            self.handles.lift()
        else:
            self.handles.hide()

    def _sticky_resize(self, i: int, r: Rect, live: bool, start: Rect | None = None) -> None:
        """The user resized the window of zone i to r: drag the shared edges along.

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

    def _zone_of_hwnd(self, hwnd: int) -> int | None:
        return next((i for i, s in enumerate(self.slots) if s and s.hwnd == hwnd), None)

    def _on_movesize_start(self, hwnd: int) -> None:
        hwnd = self.be.root_window(hwnd)
        if not self.be.is_window(hwnd):
            return
        zone = self._zone_of_hwnd(hwnd)
        if zone is not None and hwnd not in self.original:
            zone = None                       # assigned but never applied: not tiled yet
        self._movesize = {"hwnd": hwnd, "zone": zone, "start": self.be.get_rect(hwnd), "mode": None}

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
                self._sticky_resize(ms["zone"], r, live=True, start=ms["start"])
        elif self.shiftsnap_var.get():
            if self.be.shift_down():
                if not self.snap_overlay.visible:
                    self.snap_overlay.show([self._target(i) for i in range(len(self.layout.zones))])
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
        target_zone = self.snap_overlay.current if self.snap_overlay.visible else None
        self.snap_overlay.hide()
        if ms["mode"] == "resize" and ms["zone"] is not None and self.linked_var.get():
            self._sticky_resize(ms["zone"], self.be.get_rect(ms["hwnd"]), live=False, start=ms["start"])
            self.set_status("Resized - neighbouring windows followed. 'Save sizes as...' keeps these proportions.")
        elif target_zone is not None:
            self.put_window_in_zone(ms["hwnd"], target_zone)

    def put_window_in_zone(self, hwnd: int, zone: int) -> bool:
        """Snap a (real) window into a zone; if the zone is taken the two windows swap."""
        if zone is None or zone >= len(self.slots):
            return False
        wins = {w.hwnd: w for w in self.be.list_windows()}
        win = wins.get(hwnd)
        if not win:
            return False
        self.windows = list(wins.values())
        old = self._zone_of_hwnd(hwnd)
        if old == zone:
            self._place_all(fast=False)
            return True
        displaced = self.slots[zone]
        new_slot = Slot.from_window(win)
        if old is not None:
            new_slot.topmost = self.slots[old].topmost
            self.slots[old] = displaced
        elif displaced and displaced.topmost and self.be.is_window(displaced.hwnd):
            self.be.set_topmost(displaced.hwnd, False)
        self.slots[zone] = new_slot
        for h in {hwnd} | ({displaced.hwnd} if displaced and old is not None else set()):
            if self.be.is_window(h) and h not in self.original:
                self.original[h] = self.be.get_rect(h)
        for i in {zone, old} - {None}:
            s = self.slots[i]
            if s and self.be.is_window(s.hwnd):
                self.be.place(s.hwnd, self._target(i))
                self.be.set_topmost(s.hwnd, s.topmost)
        self._select_zone(zone)
        self.refresh_windows(force=True)
        self._refresh_handles()
        self.set_status(f"Snapped {win.app} into zone {zone + 1}" +
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
                "Resize handles: grips on the lines/intersections between windows on the desktop.")
        tk.Label(t, text=tips, bg=BG, fg=MUTED, justify="left").grid(
            row=99, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Button(t, text="Close", command=t.destroy).grid(row=100, column=1, sticky="e", pady=(10, 0))

    def _active_zone(self) -> int | None:
        fg = self.be.foreground()
        return self._zone_of_hwnd(self.be.root_window(fg)) if fg else None

    def neighbour(self, i: int, direction: str) -> int | None:
        zs = self.layout.zones
        a = zs[i]
        best, best_score = None, None
        for j, b in enumerate(zs):
            if j == i:
                continue
            if direction in ("left", "right"):
                gap = (a.x - (b.x + b.w)) if direction == "left" else (b.x - (a.x + a.w))
                along = (b.x + b.w / 2) < (a.x + a.w / 2) if direction == "left" else (b.x + b.w / 2) > (a.x + a.w / 2)
                overlap = min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
                perp = 0 if overlap > 0 else abs((b.y + b.h / 2) - (a.y + a.h / 2))
            else:
                gap = (a.y - (b.y + b.h)) if direction == "up" else (b.y - (a.y + a.h))
                along = (b.y + b.h / 2) < (a.y + a.h / 2) if direction == "up" else (b.y + b.h / 2) > (a.y + a.h / 2)
                overlap = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
                perp = 0 if overlap > 0 else abs((b.x + b.w / 2) - (a.x + a.w / 2))
            if not along:
                continue
            score = max(gap, 0) + 2 * perp - 0.001 * max(overlap, 0)
            if best_score is None or score < best_score:
                best, best_score = j, score
        return best

    def _on_hotkey(self, hid: int) -> None:
        if hid not in hotkeys.ACTIONS:
            return
        action, arg = hotkeys.ACTIONS[hid][:2]
        n = len(self.slots)
        if action == "focus_zone":
            if arg < n and self._slot_alive(arg):
                self.be.focus(self.slots[arg].hwnd)
                self._select_zone(arg)
        elif action == "move_to_zone":
            fg = self.be.root_window(self.be.foreground() or 0)
            if arg < n and fg and not self.put_window_in_zone(fg, arg):
                self.set_status("That window can't be tiled (it may be Windower itself or a system window).",
                                warn=True)
        elif action in ("focus_dir", "swap_dir"):
            cur = self._active_zone()
            if cur is None:
                # the active window isn't tiled: arrows just jump into the tiled set
                k = self.selected_zone if self.selected_zone is not None else 0
                if action == "focus_dir" and k < n and self._slot_alive(k):
                    self.be.focus(self.slots[k].hwnd)
                return
            j = self.neighbour(cur, arg)
            if j is None:
                return
            if action == "focus_dir":
                if self._slot_alive(j):
                    self.be.focus(self.slots[j].hwnd)
                    self._select_zone(j)
            else:
                self.slots[cur], self.slots[j] = self.slots[j], self.slots[cur]
                for k in (cur, j):
                    s = self.slots[k]
                    if s and self.be.is_window(s.hwnd):
                        self.be.place(s.hwnd, self._target(k))
                self._select_zone(j)
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
