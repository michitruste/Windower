# Windower

Arrange the windows of different programs side by side on your screen, like
split-screen on a phone. Every app keeps running live and you can click into any of them
and use it right away.

Windower moves and resizes the **real** windows. Nothing gets captured or mirrored, so
videos keep playing, terminals keep printing and editors stay fully usable.

Only the Python standard library is used (tkinter + ctypes), so there's nothing to install.

## Start it

```
cd C:\Python311\windower
C:\Python311\python.exe main.py
```

To start it without a console window, double-click **`Windower.pyw`**.
To try the interface with fake windows (nothing on your desktop moves), run `python main.py --demo`.

## How to use it

1. **Choose a layout** from the *Layout* dropdown, for example *2 columns*, *Big left + 2 stacked*
   or *Grid 2x2*.
2. **Put windows into zones** in any of these ways:
   - drag a window from the *Open windows* list onto a zone in the preview;
   - click a zone, then double-click a window in the list (the next empty zone gets selected
     automatically, so you can double-click one window after another);
   - click a zone, press **Pick on screen**, then click the real window on your desktop;
   - press **Auto-fill zones** to fill the empty zones with your most recently used windows.
3. Press **Apply layout**.

| Feature | What it does |
|---|---|
| Drag one zone onto another in the preview | Swaps the two windows (applied immediately once you've applied a layout) |
| Double-click a zone | Focuses that window |
| Right-click a zone | Menu with Focus, Always on top, Pick, Clear |
| **Always on top** | Keeps that window above the others. Handy for a video or chat |
| **Keep windows in place** | If a window gets moved or maximized, it goes back to its zone within about 1 second |
| **Gap px** | Space between the windows |
| **Monitor** | Which screen the layout goes on (each monitor uses its own work area, so the taskbar isn't covered) |
| **Bring all to front** | Brings all the tiled windows back above whatever is covering them |
| **Show zones on screen** | Flashes numbered overlays on the real monitor |
| **Restore original positions** | Puts every window back where it was before Windower moved it |

### Custom layouts (layout editor)

Press **New custom...** (or **Edit...**):

- drag on empty space to draw a zone
- drag a zone to move it; drag an edge or corner to resize it
- **V** / **H** (or double-click / Shift+double-click) to split the selected zone left|right or top/bottom
- right-click or **Del** to delete a zone, **Ctrl+Z** to undo
- type exact percentages in the *Left / Top / Width / Height* boxes
- edges snap to the grid you choose and to the edges of neighboring zones
- **Preview on monitor** shows the zones on the real screen

Zones can overlap. For example, you can place a small zone on top of a big one for a
picture-in-picture setup, and turn on *Always on top* for that zone.

### Workspaces

**Save current as...** remembers the layout, the monitor, the gap and *which app goes in which zone*.
Later, **Load** finds those apps again (by program and window title) and arranges them.
With **Launch missing apps** checked, it also starts apps that aren't running and places
their windows once they open.

Your layouts, workspaces and settings are stored in `%APPDATA%\Windower\config.json`.

## Good to know

- **Apps running as Administrator** (Task Manager, some installers or games) can only be moved
  if Windower also runs as Administrator. Right-click the console, choose *Run as administrator*
  and start it from there.
- Some apps have a **minimum size** (Spotify, Discord, a few settings windows). In a very small
  zone they stop at their minimum and may overflow the zone a little.
- Fullscreen games in exclusive fullscreen can't be tiled. Switch them to *windowed* or *borderless*.
- Windower handles high-DPI and mixed-DPI monitors and removes the invisible Windows 10/11 borders,
  so windows line up edge to edge.

## Project structure

```
main.py                 entry point  (--demo for simulated windows)
Windower.pyw            double-click launcher without console
windower_app/
  win32.py              Win32 API via ctypes: list windows/monitors, move, focus, topmost
  fakewin.py            simulated desktop (demo mode + tests)
  backend.py            picks win32 or fake
  model.py              Rect, Zone, Layout, Slot, window matching
  presets.py            built-in layouts
  storage.py            JSON persistence
  editor.py             custom layout editor
  app.py                control panel
  ui_common.py          colors, on-screen overlay
tests/test_core.py      python -m unittest discover tests
```

## Ideas for next steps

- Global hotkeys (for example Ctrl+Alt+1..9 to focus zone N, or to re-apply a workspace)
- Live DWM thumbnails of each window inside the preview
- A tray icon and start with Windows
- Snapping a window into a zone by dragging it on the desktop with Shift held
