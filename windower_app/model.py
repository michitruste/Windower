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
class Placement:
    """Where a window was before Windower first moved it (see backend save_placement)."""
    rect: Rect | None         # visible frame of a normal window; None if minimized/maximized
    maximized: bool = False   # put it back maximized
    native: object = None     # backend data that undoes a minimized/maximized state exactly


def fit_on_screen(rect: Rect, monitors: list[Monitor], grip: int = 60) -> Rect:
    """rect as is if a grip-sized piece of it is on some monitor; otherwise moved (and shrunk
    if needed) onto the primary monitor, so a window can never end up unreachable."""
    for m in monitors:
        a = m.work
        iw = min(rect.x + rect.w, a.x + a.w) - max(rect.x, a.x)
        ih = min(rect.y + rect.h, a.y + a.h) - max(rect.y, a.y)
        if iw >= min(grip, rect.w) and ih >= min(grip, rect.h):
            return rect
    if not monitors:
        return rect
    a = next((m for m in monitors if m.primary), monitors[0]).work
    w, h = min(rect.w, a.w), min(rect.h, a.h)
    return Rect(a.x + (a.w - w) // 2, a.y + (a.h - h) // 2, w, h)


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


# ==========================================================================
# Linked edges: dividers and intersection nodes
# ==========================================================================
# An "edge" is (zone_index, side) with side in "LRTB".  Edges on the same line
# that touch each other along a real length form a *divider*.  Moving a divider
# resizes every zone on both sides of it at once, so no gaps/overlaps appear.
# A *node* is a point where vertical and horizontal dividers meet (the "+" of a
# 2x2 grid, the "T" of "big left + 2 stacked"); dragging it moves all of them.

EPS = 1e-4
MIN_ZONE = 0.05          # smallest zone size (fraction of the monitor) when dragging
VERTICAL = "LR"          # sides that are vertical lines (they move along x)


def edge_coord(z: Zone, side: str) -> float:
    return {"L": z.x, "R": z.x + z.w, "T": z.y, "B": z.y + z.h}[side]


def edge_span(z: Zone, side: str) -> tuple[float, float]:
    return (z.y, z.y + z.h) if side in VERTICAL else (z.x, z.x + z.w)


@dataclass
class Divider:
    axis: str                        # "v" (moves along x) or "h" (moves along y)
    coord: float
    edges: list[tuple[int, str]]
    span: tuple[float, float]

    @property
    def interior(self) -> bool:
        return EPS < self.coord < 1 - EPS

    @property
    def key(self) -> tuple:
        return (self.axis, tuple(sorted(self.edges)))


def edge_group(zones: list[Zone], i: int, side: str) -> Divider:
    """All edges linked to (i, side): same line and touching along a real length."""
    vertical = side in VERTICAL
    sides = VERTICAL if vertical else "TB"
    c = edge_coord(zones[i], side)
    group = [(i, side)]
    lo, hi = edge_span(zones[i], side)
    queue = [(i, side)]
    while queue:
        a, sa = queue.pop()
        alo, ahi = edge_span(zones[a], sa)
        for j, z in enumerate(zones):
            for s in sides:
                if (j, s) in group or abs(edge_coord(z, s) - c) > EPS:
                    continue
                blo, bhi = edge_span(z, s)
                if min(ahi, bhi) - max(alo, blo) > EPS:   # overlap with real length
                    group.append((j, s))
                    queue.append((j, s))
                    lo, hi = min(lo, blo), max(hi, bhi)
    return Divider("v" if vertical else "h", c, group, (lo, hi))


def dividers(zones: list[Zone]) -> list[Divider]:
    """Every interior divider that has zones on both sides (i.e. is shared)."""
    seen, out = set(), []
    for i in range(len(zones)):
        for side in "LRTB":
            if (i, side) in seen:
                continue
            d = edge_group(zones, i, side)
            seen.update(d.edges)
            sides = {s for _, s in d.edges}
            if d.interior and len(sides) == 2:
                out.append(d)
    return out


@dataclass
class Node:
    x: float
    y: float
    v: list[Divider]
    h: list[Divider]


def nodes(zones: list[Zone], divs: list[Divider] | None = None) -> list[Node]:
    """Points where at least one vertical and one horizontal divider meet."""
    divs = dividers(zones) if divs is None else divs
    vs = [d for d in divs if d.axis == "v"]
    hs = [d for d in divs if d.axis == "h"]
    found: list[Node] = []
    for v in vs:
        for h in hs:
            if v.span[0] - EPS <= h.coord <= v.span[1] + EPS and h.span[0] - EPS <= v.coord <= h.span[1] + EPS:
                node = next((n for n in found if abs(n.x - v.coord) < EPS and abs(n.y - h.coord) < EPS), None)
                if node is None:
                    node = Node(v.coord, h.coord, [], [])
                    found.append(node)
                if all(d.key != v.key for d in node.v):
                    node.v.append(v)
                if all(d.key != h.key for d in node.h):
                    node.h.append(h)
    return found


def divider_range(zones: list[Zone], edges: list[tuple[int, str]], min_size: float = MIN_ZONE) -> tuple[float, float]:
    """How far a set of edges on one line may move without squashing a zone."""
    lo, hi = 0.0 + min_size, 1.0 - min_size
    for i, s in edges:
        z = zones[i]
        if s == "L":
            hi = min(hi, z.x + z.w - min_size)
        elif s == "R":
            lo = max(lo, z.x + min_size)
        elif s == "T":
            hi = min(hi, z.y + z.h - min_size)
        else:
            lo = max(lo, z.y + min_size)
    return lo, hi


def move_edges(zones: list[Zone], edges: list[tuple[int, str]], new: float,
               min_size: float = MIN_ZONE) -> float:
    """Move edges that lie on one line to `new` (clamped). Mutates zones, returns the used value."""
    if not edges:
        return new
    lo, hi = divider_range(zones, edges, min_size)
    if lo > hi:          # already at minimum on both sides
        return edge_coord(zones[edges[0][0]], edges[0][1])
    new = round(min(max(new, lo), hi), 5)
    for i, s in edges:
        z = zones[i]
        if s == "L":
            zones[i] = Zone(new, z.y, round(z.x + z.w - new, 5), z.h)
        elif s == "R":
            zones[i] = Zone(z.x, z.y, round(new - z.x, 5), z.h)
        elif s == "T":
            zones[i] = Zone(z.x, new, z.w, round(z.y + z.h - new, 5))
        else:
            zones[i] = Zone(z.x, z.y, z.w, round(new - z.y, 5))
    return new


def node_edges(node: Node) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    v = [e for d in node.v for e in d.edges]
    h = [e for d in node.h for e in d.edges]
    return list(dict.fromkeys(v)), list(dict.fromkeys(h))
