# Windower – design notes (updated 2026-09-23, v1.1)

Code lives in C:\Python311\windower on albertolap (Windows, Python 3.11), under the user's own git repo. Stdlib only (tkinter + ctypes).
The user has customised: title "Windower (michi's version)" and trimmed presets (removed Full screen, 2 rows, 3 columns, Main + 3 bottom). Keep these when editing.

## Decisions
- Approach: **tile real windows** (SetWindowPos) rather than embedding them (SetParent). Every app stays live and fully interactive; embedding breaks Chrome and UWP apps.
- Zones are stored as fractions (0..1) of a monitor's work area. Gaps are handled so inner and outer gaps are equal.
- DWM extended frame bounds compensate for the invisible Win10/11 borders; the process uses per-monitor DPI v2 awareness.
- Config lives in %APPDATA%\Windower\config.json (layouts, workspaces, settings).
- Workspaces save app signatures (exe, title, class, exe_path) and re-match on load. They store the full (possibly adjusted) zone sizes.

## v1.1 – linked edges, snapping, hotkeys
- **Dividers/nodes (model.py)**: edges on the same line that overlap along a real length form a divider (BFS). A node is where vertical and horizontal dividers meet. move_edges() clamps with MIN_ZONE=5%. In a 2x2 grid the two halves of the middle line are separate dividers; the centre node moves all of them.
- **Sticky edges**: a WinEvent hook (EVENT_SYSTEM_MOVESIZESTART/END) runs on a background thread with its own message loop (win32.EventSource). While a tiled window is being resized, the Tk loop polls its rect every 25 ms and moves the shared dividers. Neighbours are placed with SWP_ASYNCWINDOWPOS. Only the sides the user actually grabbed count. Screen edges stay pinned.
- **Grips**: the preview canvas draws dividers and nodes and they can be dragged. The optional desktop handles (desktop.py) are small topmost no-activate Tk windows.
- **Shift-drag snapping**: when a window move has Shift held, a click-through SnapOverlay appears; dropping on a zone calls put_window_in_zone (swaps if the zone is taken).
- **Global hotkeys**: RegisterHotKey on the event thread; the modifier is selectable (Ctrl+Alt by default). The table is in hotkeys.py (ids 1-9 focus, 11-19 move, 20-27 arrows focus/swap, 30 apply, 31 panel, 32 handles, 33 zones (S), 34 zoom (Z)).
- The fake backend (fakewin.py) mirrors all of this. /tmp scripted GUI tests covered node, divider, sticky resize, pinned edges, snap and swap, hotkeys, handles and the editor.

## Per-monitor layouts
- **model.Screen** = layout + slots + adjusted + selected, one per monitor (`app.screens`, same order as get_monitors()). `app.cur` is the monitor the panel edits; `layout`, `slots`, `layout_adjusted` and `selected_zone` are properties on screens[cur], so single-screen code (layout dropdown, editor, zone bar, grips) is unchanged. Anything that spans monitors uses `_assigned()` -> (m, i, slot), `_target(i, m)`, `_slot_alive(i, m)` and `_find(hwnd)` -> (m, i).
- **Preview**: all monitors are drawn in their real arrangement (work areas, 8 px separation). `_zone_at` returns (m, i); clicking, dropping or dragging a grip switches `cur` via `_set_current`. Desktop drags (sticky resize, desktop handles) also switch `cur` to that monitor.
- **apply(only=set)** arranges every screen or a subset. There's one DesktopHandles per monitor. The snap overlay shows every monitor's zones (`_snap_keys`). Hotkeys use `_screen_here()` (the monitor of the active window). Arrows use model.neighbour on pixel rects, so they cross monitors.
- **Settings**: `screen_layouts` = layout name per monitor. **Workspaces**: `screens: [{monitor, device, layout, slots}]`, matched by device name, then index. The old keys (`layout`, `slots`) are still written, and old one-monitor workspaces load onto their monitor only.

## App icons
- **Icons**: WM_GETICON (SendMessageTimeout, 100 ms), then the class icon, then PrivateExtractIconsW on the exe. Drawn with DrawIconEx on black and on white to recover alpha for any icon type (icons.rgba_from_black_white), encoded as PNG with zlib/struct for Tk. They're cached per hwnd in ui_common.IconCache.

## Zoom views (feature/zoom)
- A **Slot with `crop`** (Rect in the window's client-area pixels) is a zoom zone. The zone shows that area of the window, live and aspect-fitted, through a DWM thumbnail in a borderless no-activate Tk window of ours (zoomview.ZoomView). The window itself is never placed into the zone.
- `_assigned()` yields **tiled slots only**, `_zooms()` the crop slots, `_all_slots()` both. `_find(hwnd)` therefore only finds tiled windows. A window can be tiled in one zone and zoomed in any number of others. Everything that places or un-topmosts a slot's hwnd skips crop slots. A zoom zone's "Always on top" applies to the view window.
- Views are synced (diff, updated in place, keyed by (monitor, zone)) at the end of every `draw_preview()`. They appear as soon as a crop is set. `_already_applied(m)` is true if m has a view.
- **DWM coordinates (measured on the real machine)**: with DWM_TNP_RECTSOURCE, rcSource is relative to the **GetWindowRect** corner (invisible borders included). DwmQueryThumbnailSourceSize reports the **visible frame** size. Win32.Thumbnail.show() maps client coords to that and scales by srcsize/frame (DPI-virtualized apps).
- **Peek**: clicking a view moves the real window (same size) so the crop is centred on the view and kept on that monitor (model.peek_rect), then focuses it. ZoomViews polls every 150 ms and puts it back and sends it to the bottom once the foreground belongs to another pid. If the window is also tiled, it's only focused.
- **AreaPicker**: an overlay over the client area with -alpha plus -transparentcolor. The dragged rect is filled with the key colour, so it shows the window undimmed. It's a one-shot drag; Esc or right-click cancels.
- Workspaces: signature has `crop: [x, y, w, h]`. Crop sigs match windows ignoring `taken`.
- Chromium apps stop painting when fully occluded, which freezes their view (see the README).

## Drawing zones in the preview (feature/draw-zones)
- Ctrl+drag on a monitor in the preview (or a plain drag on empty monitor space) draws a zone (`app._draw`, rendered inside draw_preview). It's appended on top (can overlap). Snap: screen/zone edges within PREVIEW_GRIP px, else a 1/12 grid (model.snap_value). Smaller than MIN_ZONE is dropped.
- Zone menu: Split left|right / top/bottom (window keeps the first half, new empty zone inserted at i+1) and Remove zone (not the last one; its window is left where it is, un-topmosted).
- **model.Screen.add_zone / split_zone / remove_zone** keep `slots` aligned with `layout.zones` and set `adjusted`. Zones after an inserted/removed one shift index; zoom views re-key via the draw_preview diff.
- `adjusted` now also means "zones added/removed". The buttons are **Save layout as...** / **Reset layout**; reset with a different zone count goes through set_layout (keeps windows in zone order).

## Gap removed, deleting layouts
- The **Gap px** spinbox is gone; zones always touch (to_rect is called without a gap). An old `gap` key is dropped from settings on save; workspaces no longer store it and ignore it on load. model.Zone.to_rect and Overlay still take an optional gap.
- **Delete...** opens a dialog (multi-select). Custom layouts are removed from the store; built-in ones are added to `settings["hidden_layouts"]` (`app.presets()` filters them out of the dropdown and editor templates; `_find_layout` still finds them so old workspaces load). *Restore built-in layouts* clears the list. At least one layout must remain. Monitors on a deleted layout go to `_default_layout()` (2 columns, else the first visible).

## Launching Store apps from workspaces
- Store/packaged apps (WhatsApp.Root.exe in WindowsApps) can't be started from their exe (WinError 5, measured). `win32.app_id(hwnd)` = GetApplicationUserModelId of the process, or for ApplicationFrameHost windows the window's PKEY_AppUserModel_ID (property store; untested, no such window was open). Saved as `app_id` in the slot signature (only when set) and kept on Slot.
- `launch(exe_path, app_id)` uses `shell:AppsFolder\<id>`. Without an id, `_store_app_id` works it out from a WindowsApps path (Name_PublisherId + Application Id from AppxManifest.xml, else "App"), so older workspaces work too. A bare ApplicationFrameHost.exe path returns False. Launching WhatsApp this way was confirmed on the real machine.
- `_wait_for_launched` (30 s) no longer calls apply(): it places only the slots that just got a window (`_place_slots`, no z-order change). Before, it raised every tiled window once a second, covering the panel.

## Hidden zoom sources, zoom hotkey
- While a window is seen only through zoom views (not tiled, not peeked, not exempt), ZoomViews.sync_hidden **ghosts** it: win32.ghost adds WS_EX_LAYERED|WS_EX_TRANSPARENT with alpha 0 (click-through, invisible). **Measured**: the DWM thumbnail still shows it at full opacity and stays live; unghost restores the exact exstyle and old layered attrs. Windows already drawing with UpdateLayeredWindow (no GetLayeredWindowAttributes) aren't ghosted. unghost is a no-op unless the window is still ghosted (safe after hwnd reuse).
- Setting `hide_zoomed` (default on, "Hide zoomed windows"). Peek un-ghosts; end_peek re-ghosts (send_to_back only if it couldn't be ghosted). Switching to a ghosted window (Alt+Tab, taskbar) auto-peeks it; `_last_fg` is reset on every ghost change so hiding the active window doesn't count as a switch. `views.exempt` holds windows under the AreaPicker.
- Crash safety: ghosted hwnds + state go to `hidden_windows.json` next to config.json; `views.recover()` at startup un-ghosts them. close_all un-ghosts everything.
- Hotkeys: 33 show zones is now **S**; 34 `zoom_window` = **Z** → `app.zoom_active_window()`: zone = where the active window is tiled, else a zone zooming it, else the selected zone of `_screen_here()`. `_pick_area(reopen=None)` only reopens the panel if it was open.

## Zoom view controls (pan, wheel zoom, title bar)
- ZoomView = FRAME_BG toplevel (BORDER px frame = resize area; `<Motion>`/press on the toplevel itself, `e.widget is t`) holding a title bar (icon, "app · 2.3x", − + ⤢ ≡ ✕) and the picture Label. The thumbnail dest is `fit_aspect(content(), crop)`, below the title bar (DWM draws over child widgets). Sizes x `app.scale`.
- Picture: press+move ≥ DRAG_START px pans (`model.pan_crop`, always from the start crop), a click without movement peeks. `<MouseWheel>` bound on the toplevel: Ctrl = `model.zoom_crop` around the pointer, Shift = sideways, else vertical. All of it just changes `slot.crop` → `on_crop` (app debounces a preview redraw + status). `Slot.home` = the picked area (runtime only; set in `_set_zoom`, else from the crop when the view is made): ⤢ returns to it and zoom keeps its aspect.
- Title-bar drag / frame resize set `view.floating`; `update()` then only records `zone_rect`. `ZoomViews.dock()` is called by apply() (per `only`), double-click on the title bar and the zone menu item. Peek uses the view's on-screen content rect and the work area under a floated view (`sync(want, areas)`).
- Unconfirmed on the real machine: wheel events reaching the no-activate view (relies on Tk 8.6 sending the wheel to the window under the pointer).

## Status
- Unit tests (47) and scripted GUI flows with the fake backend pass. The real Win32 run confirmed the cropped thumbnail pixels, peek and return, and the picker hole. Hooks, hotkeys and async placement are still unconfirmed on the user's machine.

## Next ideas
A tray icon and autostart.
