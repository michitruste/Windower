"""Global hotkey table (registered by the backend's EventSource)."""
from __future__ import annotations

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8

MODIFIER_CHOICES = {
    "Ctrl+Alt": MOD_CONTROL | MOD_ALT,
    "Win+Alt": MOD_WIN | MOD_ALT,
    "Ctrl+Win": MOD_CONTROL | MOD_WIN,
    "Ctrl+Alt+Win": MOD_CONTROL | MOD_ALT | MOD_WIN,
    "Off": 0,
}

VK_RETURN, VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN = 0x0D, 0x25, 0x26, 0x27, 0x28
DIRS = {VK_LEFT: ("left", "←"), VK_UP: ("up", "↑"), VK_RIGHT: ("right", "→"),
        VK_DOWN: ("down", "↓")}

# id -> (action, argument, needs extra Shift, virtual key)
ACTIONS: dict[int, tuple[str, object, bool, int]] = {}
for _n in range(1, 10):
    ACTIONS[_n] = ("focus_zone", _n - 1, False, 0x30 + _n)          # 1..9
    ACTIONS[10 + _n] = ("move_to_zone", _n - 1, True, 0x30 + _n)    # Shift+1..9
for _k, (_vk, (_name, _)) in enumerate(DIRS.items()):
    ACTIONS[20 + _k] = ("focus_dir", _name, False, _vk)
    ACTIONS[24 + _k] = ("swap_dir", _name, True, _vk)
ACTIONS[30] = ("apply", None, False, VK_RETURN)
ACTIONS[31] = ("toggle_panel", None, False, ord("W"))
ACTIONS[32] = ("toggle_handles", None, False, ord("H"))
ACTIONS[33] = ("show_zones", None, False, ord("S"))
ACTIONS[34] = ("zoom_window", None, False, ord("Z"))


def build(modifier_name: str) -> list[tuple[int, int, int]]:
    mods = MODIFIER_CHOICES.get(modifier_name, 0)
    if not mods:
        return []
    return [(hid, mods | (MOD_SHIFT if shift else 0), vk) for hid, (_a, _arg, shift, vk) in ACTIONS.items()]


def help_rows(modifier_name: str) -> list[tuple[str, str]]:
    m = modifier_name
    return [
        (f"{m} + 1 ... 9", "Focus the window in zone 1-9"),
        (f"{m} + Shift + 1 ... 9", "Move the active window into zone 1-9 (swaps if taken)"),
        (f"{m} + Arrow", "Focus the neighbouring zone in that direction"),
        (f"{m} + Shift + Arrow", "Swap the active window with its neighbour"),
        (f"{m} + Enter", "Apply / re-tile the layout"),
        (f"{m} + W", "Show / hide the Windower panel"),
        (f"{m} + H", "Show / hide the resize handles on the desktop"),
        (f"{m} + S", "Flash the zones on screen"),
        (f"{m} + Z", "Zoom: drag over part of the active window to show it in its zone"
                     " (the zone it's tiled in, else the selected zone)"),
        ("Shift while dragging a window", "Show the zones - drop the window into one to snap it"),
    ]


def describe(hid: int, modifier_name: str) -> str:
    action, arg, shift, vk = ACTIONS[hid]
    key = {VK_RETURN: "Enter"}.get(vk) or (DIRS[vk][0].title() if vk in DIRS else chr(vk))
    return f"{modifier_name}{'+Shift' if shift else ''}+{key}"
