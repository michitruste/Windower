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
| Right-click a zone | Menu with Focus, Always on top, Pick, Zoom area, Clear, Split, Remove |
| Ctrl+drag in the preview | Draws a new zone (see *Add, split or remove zones* below) |
| **Always on top** | Keeps that window above the others. Handy for a video or chat |
| **Keep windows in place** | If a window gets moved or maximized, it goes back to its zone within about 1 second |
| **Monitor** | Which screen the panel is editing (see *Several monitors* below). Each monitor uses its own work area, so the taskbar isn't covered |
| **Bring all to front** | Brings all the tiled windows back above whatever is covering them |
| **Show zones on screen** | Flashes numbered overlays on the real monitor |
| **Restore original positions** | Puts every window back where it was before Windower moved it |
| App icons | The *Open windows* list, the zones and the drag label show each app's icon |

### Zoom views (show only part of a window)

A zone can show **just one area of a window**, for example the video of a web page, a
chart in a trading app or the log panel of an IDE. The area is scaled up to fill the zone and
stays live: videos keep playing and text keeps updating.

1. Select a zone and press **Zoom area...** (or right-click the zone > *Zoom into an area of a
   window...*). Windower uses the zone's own window, else the one selected in the list, else asks
   you to click a window on the desktop.
2. The window comes to the front, dimmed. **Drag over the part you want to see** (Esc cancels).
3. The zone now shows that area. The window itself is **not** moved into the zone. Keep it
   open anywhere, even behind other windows or tiled in another zone.

Quicker: click the window and press **Ctrl+Alt+Z**, then drag over the area. If the window is
tiled in a zone, that zone becomes the zoom of it; otherwise the selected zone of that monitor is used.

- **The zoomed window is hidden** (fully transparent and click-through, so it doesn't cover
  anything) while it's only seen through zoom views. It keeps running and the view stays live.
  Turn this off with *Hide zoomed windows* at the top. Windows that are also tiled in a zone of
  their own stay visible. Closing Windower shows them again; if Windower crashes, the next start
  does it.
- **Click a zoom view to use the window**, or Alt+Tab / click it on the taskbar. The real window
  shows up over the view, with the chosen area centred on it, and gets the focus. Once you switch
  to another app, it goes back where it was and is hidden again. If the window is tiled in another
  zone as well, clicking just focuses it there.
- **Move around inside the view**: drag the picture to pan, use the mouse wheel to scroll
  (Shift+wheel sideways), and **Ctrl+wheel** to zoom in/out around the pointer. The title bar's
  **−** / **+** zoom too, and **⤢** goes back to the area you picked. What you end up showing is what
  a workspace saves.
- **Title bar**: drag it to move the view, drag the view's thin frame (edges or corners) to resize
  it. A moved view floats off its zone until you double-click its title bar, choose *Put the view
  back in its zone*, or press Apply. **≡** opens the zone menu, **✕** clears the zone.
- Right-click a zoom view (on the desktop or in the preview) for *Change zoom area...* and
  *Show whole window (tile it)*. *Always on top* keeps the zoom view above other windows.
- Dividers, nodes, desktop handles, swapping and workspaces all work with zoom zones.
- The preview marks zoom zones with **ZOOM WxH**.
- The picture comes from Windows itself (the same live thumbnails the taskbar uses), so it
  costs almost nothing. Windows can only show a window that is open. If the window gets
  **minimized**, the view says so; click it to bring the window back. **Apply layout**
  also un-minimizes zoom windows.
- **Chrome, Edge and other Chromium apps** (Opera, Brave, Electron apps) stop painting when
  they're completely covered by other windows, and then the zoom view freezes. Leave a bit of the
  window visible, or start the browser with
  `--disable-features=CalculateNativeWinOcclusion`.
- In demo mode, zoom views show a placeholder, since there are no real windows to show.

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
- After adjusting, **Save layout as...** stores the new proportions as a custom layout.
  **Reset layout** goes back to the original proportions. Saving a *workspace* also remembers the
  adjusted sizes.

### Add, split or remove zones right in the preview

You don't need the layout editor to change the zones of a layout:

- **Ctrl+drag** anywhere on a monitor in the preview to **draw a new zone**. It goes on top of the
  others, so you can draw a small zone over a big one (picture-in-picture, then turn on *Always on
  top*). On empty space (a layout that doesn't cover the whole screen) a plain drag draws too.
  Edges snap to the screen edges, to the other zones' edges and to a 1/12 grid.
- Right-click a zone > **Split zone left | right** or **top / bottom**. Its window keeps the first
  half and the new half is empty and selected, ready for a window.
- Right-click a zone > **Remove zone**. Its window stays where it is.
- The changes apply to the real windows right away if the layout is applied. **Save layout as...**
  keeps them as a custom layout. **Reset layout** goes back to the layout as it was saved.

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
| Ctrl+Alt + S | Flash the zones on screen |
| Ctrl+Alt + Z | Zoom: drag over part of the active window to show it in its zone (the zone it's tiled in, else the selected zone) |

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

**Delete...** (next to *Edit...*) lists every layout. Select one or more (Ctrl/Shift+click) and press
*Delete selected*. Custom layouts are removed; built-in ones are only hidden and come back with
*Restore built-in layouts*. A monitor that was using a deleted layout switches to *2 columns* (or the
first layout left) and keeps its windows.

Zones can overlap. For example, you can place a small zone on top of a big one for a
picture-in-picture setup, and turn on *Always on top* for that zone.

### Workspaces

**Save current as...** remembers the layout of every monitor and *which app goes in which zone*.
Later, **Load** finds those apps again (by program and window title) and arranges them.
With **Launch missing apps** checked, it also starts apps that aren't running and places
their windows once they open. Microsoft Store apps (WhatsApp, Windows Terminal...) are started
through their app ID, since Windows doesn't let other programs run their exe directly. While it
waits for launched apps, only the windows that just opened are moved; the others stay where they are.

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
                        DWM thumbnails, move/resize event hook + global hotkeys (background thread)
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
  zoomview.py           zoom views (part of a window, live, in a zone), peek, area picker
tests/test_core.py      python -m unittest discover tests
```

## Ideas for next steps

- Live DWM thumbnails of each window inside the preview
- A tray icon and start with Windows
