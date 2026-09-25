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
- **Global hotkeys**: RegisterHotKey on the event thread; the modifier is selectable (Ctrl+Alt by default). The table is in hotkeys.py (ids 1-9 focus, 11-19 move, 20-27 arrows focus/swap, 30 apply, 31 panel, 32 handles, 33 zones).
- The fake backend (fakewin.py) mirrors all of this. /tmp scripted GUI tests covered node, divider, sticky resize, pinned edges, snap and swap, hotkeys, handles and the editor.

## Status
- Unit tests (15) and a headless GUI flow with the fake backend pass. The real Win32 path (hooks, hotkeys, async placement) has not yet been confirmed on the user's machine.

## Next ideas
Live DWM thumbnails in the preview, a tray icon and autostart, different layouts on each monitor at the same time.
