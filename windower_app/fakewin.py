"""
Simulated desktop used for `python main.py --demo` and for automated tests
on machines that are not Windows. Same functions as win32.py.
"""
from __future__ import annotations

from .model import Monitor, Placement, Rect, WindowInfo

NAME = "demo"

_MONITORS = [
    Monitor("DISPLAY1", Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1040), True),
    Monitor("DISPLAY2", Rect(1920, 0, 2560, 1440), Rect(1920, 0, 2560, 1400), False),
]

_windows: dict[int, dict] = {}
_z: list[int] = []
_fg = 0


def _add(hwnd, title, exe, cls):
    _windows[hwnd] = {"info": WindowInfo(hwnd, title, exe, rf"C:\Apps\{exe}", cls, hwnd // 10),
                      "rect": Rect(100 + hwnd % 7 * 40, 80 + hwnd % 5 * 30, 900, 650),
                      "min": False, "top": False}
    _z.append(hwnd)


for _h, _t, _e, _c in [
    (1010, "YouTube - Lo-fi beats - Google Chrome", "chrome.exe", "Chrome_WidgetWin_1"),
    (1020, "main.py - windower - Visual Studio Code", "Code.exe", "Chrome_WidgetWin_1"),
    (1030, "Command Prompt", "cmd.exe", "ConsoleWindowClass"),
    (1040, "Spotify Premium", "Spotify.exe", "Chrome_WidgetWin_0"),
    (1050, "Calculator", "CalculatorApp.exe", "ApplicationFrameWindow"),
    (1060, "Document1 - Word", "WINWORD.EXE", "OpusApp"),
    (1070, "Discord", "Discord.exe", "Chrome_WidgetWin_1"),
    (1080, "File Explorer - Downloads", "explorer.exe", "CabinetWClass"),
]:
    _add(_h, _t, _e, _c)


def enable_dpi_awareness() -> None:
    pass


def list_windows() -> list[WindowInfo]:
    return [_windows[h]["info"] for h in _z if h in _windows]


def get_monitors() -> list[Monitor]:
    return list(_MONITORS)


def is_window(hwnd: int) -> bool:
    return hwnd in _windows


def get_title(hwnd: int) -> str:
    return _windows[hwnd]["info"].title if hwnd in _windows else ""


def get_rect(hwnd: int) -> Rect:
    return _windows[hwnd]["rect"]


def is_minimized(hwnd: int) -> bool:
    return _windows.get(hwnd, {}).get("min", False)


def is_topmost(hwnd: int) -> bool:
    return _windows.get(hwnd, {}).get("top", False)


def place(hwnd: int, target: Rect, fast: bool = False) -> bool:
    if hwnd not in _windows:
        return False
    _windows[hwnd]["rect"] = target
    _windows[hwnd]["min"] = False
    return True


def save_placement(hwnd: int) -> Placement:
    w = _windows[hwnd]
    if w["min"]:
        return Placement(None, native=w["rect"])
    return Placement(w["rect"])


def restore_placement(hwnd: int, p: Placement) -> bool:
    if hwnd not in _windows:
        return False
    if p.native is None:
        return place(hwnd, p.rect) if p.rect else False
    return place(hwnd, p.native)


def _front(hwnd):
    if hwnd in _z:
        _z.remove(hwnd)
        _z.insert(0, hwnd)


def focus(hwnd: int) -> None:
    global _fg
    if hwnd in _windows:
        _windows[hwnd]["min"] = False
        _front(hwnd)
        _fg = hwnd


def raise_no_focus(hwnd: int) -> None:
    if hwnd in _windows:
        _windows[hwnd]["min"] = False
        _front(hwnd)


def set_topmost(hwnd: int, on: bool) -> None:
    if hwnd in _windows:
        _windows[hwnd]["top"] = on


def minimize(hwnd: int) -> None:
    if hwnd in _windows:
        _windows[hwnd]["min"] = True


def foreground() -> int:
    return _fg


def root_window(hwnd: int) -> int:
    return hwnd


_input = {"cursor": (0, 0), "shift": False, "button": False}


def mouse_button_down() -> bool:
    return _input["button"]


def cursor_pos() -> tuple[int, int]:
    return _input["cursor"]


def shift_down() -> bool:
    return _input["shift"]


def style_overlay(tk_hwnd: int, click_through: bool) -> None:
    pass


class EventSource:
    """Fake event thread: tests push events with fire()."""

    def __init__(self):
        self.events: list[tuple] = []
        self.hotkeys: list[tuple[int, int, int]] = []

    def poll(self) -> list[tuple]:
        out, self.events = self.events, []
        return out

    def set_hotkeys(self, hotkeys) -> None:
        self.hotkeys = list(hotkeys)

    def stop(self) -> None:
        pass

    def fire(self, *event) -> None:
        self.events.append(tuple(event))


def launch(exe_path: str) -> bool:
    return False


# test helpers ---------------------------------------------------------------
def close(hwnd: int) -> None:
    _windows.pop(hwnd, None)
    if hwnd in _z:
        _z.remove(hwnd)


def move_by_user(hwnd: int, rect: Rect) -> None:
    _windows[hwnd]["rect"] = rect


def set_foreground(hwnd: int) -> None:
    global _fg
    _fg = hwnd


def set_input(cursor=None, shift=None, button=None) -> None:
    if cursor is not None:
        _input["cursor"] = cursor
    if shift is not None:
        _input["shift"] = shift
    if button is not None:
        _input["button"] = button
