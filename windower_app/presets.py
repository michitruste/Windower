"""Built-in layouts (think: phone split-screen, but more flexible)."""
from __future__ import annotations

from .model import Layout, Zone

T = 1 / 3


def _grid(cols: int, rows: int) -> list[Zone]:
    return [Zone(c / cols, r / rows, 1 / cols, 1 / rows) for r in range(rows) for c in range(cols)]


PRESETS: list[Layout] = [
    Layout("Full screen", [Zone(0, 0, 1, 1)]),
    Layout("2 columns", _grid(2, 1)),
    Layout("2 rows", _grid(1, 2)),
    Layout("Main 2/3 + side", [Zone(0, 0, 2 * T, 1), Zone(2 * T, 0, T, 1)]),
    Layout("3 columns", _grid(3, 1)),
    Layout("Big left + 2 stacked", [Zone(0, 0, 0.5, 1), Zone(0.5, 0, 0.5, 0.5), Zone(0.5, 0.5, 0.5, 0.5)]),
    Layout("2 stacked + big right", [Zone(0, 0, 0.5, 0.5), Zone(0, 0.5, 0.5, 0.5), Zone(0.5, 0, 0.5, 1)]),
    Layout("Grid 2x2", _grid(2, 2)),
    Layout("Focus center + 2 sides", [Zone(0, 0, 0.25, 1), Zone(0.25, 0, 0.5, 1), Zone(0.75, 0, 0.25, 1)]),
    Layout("Main + 3 bottom", [Zone(0, 0, 1, 0.65)] + [Zone(i * T, 0.65, T, 0.35) for i in range(3)]),
    Layout("Grid 3x2", _grid(3, 2)),
    Layout("Grid 3x3", _grid(3, 3)),
]
for _p in PRESETS:
    _p.builtin = True
