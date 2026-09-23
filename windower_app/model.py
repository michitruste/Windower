"""Plain data types shared by every module (no OS / GUI dependencies)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def close_to(self, other: "Rect", tol: int = 3) -> bool:
        return (abs(self.x - other.x) <= tol and abs(self.y - other.y) <= tol
                and abs(self.w - other.w) <= tol and abs(self.h - other.h) <= tol)


@dataclass(frozen=True)
class Monitor:
    name: str
    full: Rect        # whole screen
    work: Rect        # screen minus the taskbar
    primary: bool = False

    def label(self, index: int) -> str:
        tag = " (primary)" if self.primary else ""
        return f"{index + 1}: {self.full.w}x{self.full.h}{tag}"


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    exe: str          # e.g. "chrome.exe"
    exe_path: str     # full path, used to relaunch apps from a workspace
    class_name: str
    pid: int

    @property
    def app(self) -> str:
        return self.exe[:-4] if self.exe.lower().endswith(".exe") else self.exe


@dataclass
class Zone:
    """A slot of a layout in fractions (0..1) of the monitor work area."""
    x: float
    y: float
    w: float
    h: float

    def to_rect(self, area: Rect, gap: int = 0) -> Rect:
        """Pixel rectangle inside `area`, with `gap` pixels between neighbours/edges."""
        x1 = area.x + round(self.x * area.w)
        y1 = area.y + round(self.y * area.h)
        x2 = area.x + round((self.x + self.w) * area.w)
        y2 = area.y + round((self.y + self.h) * area.h)
        half = gap / 2
        # outer edges get a full gap, shared inner edges get half from each side
        left = gap if self.x <= 0.0005 else half
        top = gap if self.y <= 0.0005 else half
        right = gap if self.x + self.w >= 0.9995 else half
        bottom = gap if self.y + self.h >= 0.9995 else half
        rx, ry = round(x1 + left), round(y1 + top)
        rw, rh = round(x2 - right) - rx, round(y2 - bottom) - ry
        return Rect(rx, ry, max(rw, 50), max(rh, 50))

    def contains(self, fx: float, fy: float) -> bool:
        return self.x <= fx < self.x + self.w and self.y <= fy < self.y + self.h

    def clamp(self) -> "Zone":
        w = min(max(self.w, 0.02), 1.0)
        h = min(max(self.h, 0.02), 1.0)
        x = min(max(self.x, 0.0), 1.0 - w)
        y = min(max(self.y, 0.0), 1.0 - h)
        return Zone(round(x, 5), round(y, 5), round(w, 5), round(h, 5))

    def split(self, vertical: bool) -> tuple["Zone", "Zone"]:
        """vertical=True -> left | right, False -> top / bottom."""
        if vertical:
            hw = self.w / 2
            return Zone(self.x, self.y, hw, self.h), Zone(self.x + hw, self.y, self.w - hw, self.h)
        hh = self.h / 2
        return Zone(self.x, self.y, self.w, hh), Zone(self.x, self.y + hh, self.w, self.h - hh)


@dataclass
class Layout:
    name: str
    zones: list[Zone] = field(default_factory=list)
    builtin: bool = False

    def to_dict(self) -> dict:
        return {"name": self.name, "zones": [asdict(z) for z in self.zones]}

    @staticmethod
    def from_dict(d: dict) -> "Layout":
        return Layout(d["name"], [Zone(**z).clamp() for z in d.get("zones", [])])

    def copy(self, name: str | None = None) -> "Layout":
        return Layout(name or self.name, [Zone(z.x, z.y, z.w, z.h) for z in self.zones])


@dataclass
class Slot:
    """A window assigned to a zone, plus per-slot options."""
    hwnd: int = 0
    title: str = ""
    exe: str = ""
    exe_path: str = ""
    class_name: str = ""
    topmost: bool = False

    @staticmethod
    def from_window(w: WindowInfo) -> "Slot":
        return Slot(w.hwnd, w.title, w.exe, w.exe_path, w.class_name)

    def signature(self) -> dict:
        """What is saved in a workspace (hwnds don't survive a reboot)."""
        return {"title": self.title, "exe": self.exe, "exe_path": self.exe_path,
                "class_name": self.class_name, "topmost": self.topmost}


def match_window(sig: dict, windows: list[WindowInfo], taken: set[int]) -> WindowInfo | None:
    """Find the open window that best matches a saved slot signature."""
    best, best_score = None, 0
    exe = (sig.get("exe") or "").lower()
    title = sig.get("title") or ""
    cls = sig.get("class_name") or ""
    for w in windows:
        if w.hwnd in taken or not exe or w.exe.lower() != exe:
            continue
        score = 1
        if cls and w.class_name == cls:
            score += 1
        if title and w.title == title:
            score += 4
        elif title and _common_words(title, w.title):
            score += 2
        if score > best_score:
            best, best_score = w, score
    return best


def _common_words(a: str, b: str) -> bool:
    wa = {t for t in a.lower().replace("-", " ").split() if len(t) > 3}
    wb = {t for t in b.lower().replace("-", " ").split() if len(t) > 3}
    return bool(wa & wb)
