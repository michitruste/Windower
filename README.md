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
| **Monitor** | Which screen the panel is editing (see *Several monitors* below). Each monitor uses its own work area, so the taskbar isn't covered |
| **Bring all to front** | Brings all the tiled windows back above whatever is covering them |
| **Show zones on screen** | Flashes numbered overlays on the real monitor |
| **Restore original positions** | Puts every window back where it was before Windower moved it |
| App icons | The *Open windows* list, the zones and the drag label show each app's icon |

### Several monitors

Every monitor has its **own layout and its own windows**, all active at the same time. For example,
you can have *Big left + 2 stacked* on a laptop screen and *Grid 2x2* on an external monitor.

- The preview shows all your monitors side by side, arranged the way Windows has them. The monitor
  you're editing has a blue frame and a blue *Monitor N* tag.
- Clicking a zone, or dropping a window on it, switches the panel to that monitor. The **Layout**
  dropdown, the zone bar, **Auto-fill zones** and **Clear all zones** then work on that monitor.
  The **Monitor** dropdown does the same and also shows each monitor's layout.
- Drag one zone onto a zone of another monitor to swap the two windows between screens.
- **Apply layout**, **Keep windows in place**, **Show zones**, **Bring all to front**, the desktop
  resize handles and Shift-drag snapping cover every monitor at once.
- Hotkeys work on the monitor of the active window: `Ctrl+Alt+1` focuses zone 1 *of that screen*.
  The arrow hotkeys cross from one monitor to the next.
- Workspaces remember every monitor. If a saved monitor isn't connected, the rest still load.

### Linked edges, dividers and nodes (no gaps, ever)

Once a layout is applied, the tiled windows behave like one connected surface:

- **Resize a window normally** (drag its border on the desktop). With **Linked edges** on, the
  neighbouring windows follow live, so no gap or overlap appears. Screen edges stay pinned; if
  you pull a window away from the screen edge it snaps back when you let go.
- **In the preview**, the grey lines between zones are *dividers* and the orange dots are
  *nodes* (where lines meet, like the centre of a 2x2 grid or the "T" of *Big left + 2 stacked*).
  Drag a divider to move that line, or drag a node to move every line that meets there. The real
  windows follow live.
- **Resize handles on desktop** puts the same grips (blue bars on the dividers, orange dots on the nodes)
  right on your screen, between the windows. Toggle them with the checkbox or the hotkey.
- A divider only moves the windows that actually share it. In a 2x2 grid you can move the top
  and bottom halves of the middle line separately, or grab the centre node to move both together.
- After adjusting, **Save sizes as...** stores the new proportions as a custom layout.
  **Reset sizes** goes back to the original proportions. Saving a *workspace* also remembers the
  adjusted sizes.

### Shift-drag snapping

Drag **any** window by its title bar and hold **Shift**. The zones appear on screen and the one
under the mouse is highlighted. Let go and the window snaps into that zone. If the zone already
has a window, the two windows swap places.

### Global hotkeys

These work from any app. The modifier can be changed in the *Hotkeys* box (`Ctrl+Alt` by default,
`Off` disables them). The **?** button shows the list.

| Keys | Action |
|---|---|
| Ctrl+Alt + 1...9 | Focus the window in zone 1-9 |
| Ctrl+Alt + Shift + 1...9 | Move the active window into zone 1-9 (swaps if taken) |
| Ctrl+Alt + Arrow | Focus the neighbouring zone in that direction |
| Ctrl+Alt + Shift + Arrow | Swap the active window with its neighbour |
| Ctrl+Alt + Enter | Apply / re-tile the layout |
| Ctrl+Alt + W | Show / hide the Windower panel |
| Ctrl+Alt + H | Show / hide the resize handles on the desktop |
| Ctrl+Alt + Z | Flash the zones on screen |

If another program already uses a combination, the status bar tells you which one. You can then
pick a different modifier. (Some Intel graphics drivers use Ctrl+Alt+Arrow to rotate the screen;
if that happens, switch to *Win+Alt*.)

### Custom layouts (layout editor)

Press **New custom...** (or **Edit...**):

- drag on empty space to draw a zone
- drag a zone to move it; drag an edge or corner to resize it
- **V** / **H** (or double-click / Shift+double-click) to split the selected zone left|right or top/bottom
- right-click or **Del** to delete a zone, **Ctrl+Z** to undo
- type exact percentages in the *Left / Top / Width / Height* boxes
- edges snap to the grid you choose and to the edges of neighboring zones
- with **Link shared edges** on, dragging a shared edge also resizes the neighbouring zone, and the
  orange node dots move every line that meets there
- **Preview on monitor** shows the zones on the real screen

Zones can overlap. For example, you can place a small zone on top of a big one for a
picture-in-picture setup, and turn on *Always on top* for that zone.

### Workspaces

**Save current as...** remembers the layout of every monitor, the gap and *which app goes in which zone*.
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
  win32.py              Win32 API via ctypes: windows/monitors, move, focus, topmost, icons,
                        move/resize event hook + global hotkeys (background thread)
  fakewin.py            simulated desktop (demo mode + tests)
  backend.py            picks win32 or fake
  model.py              Rect, Zone, Layout, Slot, Screen, window matching, dividers/nodes geometry
  desktop.py            on-screen snap overlay and resize handles
  hotkeys.py            hotkey table
  presets.py            built-in layouts
  storage.py            JSON persistence
  editor.py             custom layout editor
  app.py                control panel
  icons.py              icon pixels -> PNG (no Pillow needed)
  ui_common.py          colors, on-screen overlay, icon cache
tests/test_core.py      python -m unittest discover tests
```

## Ideas for next steps

- Live DWM thumbnails of each window inside the preview
- A tray icon and start with Windows
