"""Run with:  python -m unittest discover tests"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from windower_app.model import (MIN_ZONE, Layout, Rect, WindowInfo, Zone, dividers, edge_group,  # noqa: E402
                                 match_window, move_edges, node_edges, nodes)
from windower_app.presets import PRESETS  # noqa: E402
from windower_app.storage import Store  # noqa: E402

AREA = Rect(0, 0, 1920, 1040)


class ZoneTests(unittest.TestCase):
    def test_halves_tile_exactly(self):
        a, b = Zone(0, 0, 0.5, 1).to_rect(AREA), Zone(0.5, 0, 0.5, 1).to_rect(AREA)
        self.assertEqual(a, Rect(0, 0, 960, 1040))
        self.assertEqual(b, Rect(960, 0, 960, 1040))

    def test_gap_is_uniform(self):
        g = 10
        a, b = Zone(0, 0, 0.5, 1).to_rect(AREA, g), Zone(0.5, 0, 0.5, 1).to_rect(AREA, g)
        self.assertEqual(a.x, 10)                     # outer edge = full gap
        self.assertEqual(b.x - (a.x + a.w), 10)       # between zones = full gap
        self.assertEqual(AREA.w - (b.x + b.w), 10)

    def test_offset_monitor(self):
        r = Zone(0, 0, 1, 1).to_rect(Rect(-1920, 0, 1920, 1080))
        self.assertEqual(r, Rect(-1920, 0, 1920, 1080))

    def test_thirds_cover_screen(self):
        rects = [z.to_rect(AREA) for z in next(p for p in PRESETS if p.name == "Grid 3x2").zones[:3]]
        self.assertEqual(rects[0].x, 0)
        self.assertEqual(rects[-1].x + rects[-1].w, 1920)
        for r1, r2 in zip(rects, rects[1:]):
            self.assertEqual(r1.x + r1.w, r2.x)

    def test_split_and_clamp(self):
        a, b = Zone(0, 0, 1, 1).split(True)
        self.assertEqual((a.w, b.x), (0.5, 0.5))
        c, d = a.split(False)
        self.assertEqual((c.h, d.y), (0.5, 0.5))
        z = Zone(0.9, 0.9, 0.5, 0.5).clamp()
        self.assertLessEqual(z.x + z.w, 1.0)
        self.assertLessEqual(z.y + z.h, 1.0)

    def test_presets_valid(self):
        for p in PRESETS:
            self.assertTrue(p.zones, p.name)
            for z in p.zones:
                self.assertGreaterEqual(z.x, 0)
                self.assertLessEqual(z.x + z.w, 1.0001)
                self.assertLessEqual(z.y + z.h, 1.0001)


class DividerTests(unittest.TestCase):
    def grid(self):
        return [z for z in next(p for p in PRESETS if p.name == "Grid 2x2").copy().zones]

    def test_grid_has_four_dividers_and_one_node(self):
        zones = self.grid()
        divs = dividers(zones)
        self.assertEqual(len(divs), 4)          # top/bottom half of the "|", left/right half of the "-"
        ns = nodes(zones, divs)
        self.assertEqual(len(ns), 1)
        self.assertAlmostEqual(ns[0].x, 0.5)
        self.assertEqual((len(ns[0].v), len(ns[0].h)), (2, 2))

    def test_segment_move_keeps_neighbours_glued(self):
        zones = self.grid()
        d = edge_group(zones, 0, "R")            # top-left's right edge
        self.assertEqual(sorted(d.edges), [(0, "R"), (1, "L")])
        move_edges(zones, d.edges, 0.7)
        self.assertAlmostEqual(zones[0].w, 0.7)
        self.assertAlmostEqual(zones[1].x, 0.7)
        self.assertAlmostEqual(zones[1].x + zones[1].w, 1.0)
        self.assertAlmostEqual(zones[2].w, 0.5)  # bottom row untouched

    def test_node_moves_everything(self):
        zones = self.grid()
        n = nodes(zones)[0]
        v, h = node_edges(n)
        move_edges(zones, v, 0.3)
        move_edges(zones, h, 0.6)
        self.assertEqual([round(z.w, 3) for z in zones], [0.3, 0.7, 0.3, 0.7])
        self.assertEqual([round(z.h, 3) for z in zones], [0.6, 0.6, 0.4, 0.4])

    def test_t_junction_moves_whole_line(self):
        zones = next(p for p in PRESETS if p.name == "Big left + 2 stacked").copy().zones
        d = edge_group(zones, 1, "L")            # top-right's left edge
        self.assertEqual(sorted(d.edges), [(0, "R"), (1, "L"), (2, "L")])
        self.assertEqual(len(nodes(zones)), 1)

    def test_clamped_to_min_size(self):
        zones = self.grid()
        d = edge_group(zones, 0, "R")
        used = move_edges(zones, d.edges, 0.999)
        self.assertAlmostEqual(used, 1 - MIN_ZONE)
        self.assertGreaterEqual(zones[1].w, MIN_ZONE - 1e-9)

    def test_outer_edges_are_not_dividers(self):
        zones = [Zone(0, 0, 1, 1)]
        self.assertEqual(dividers(zones), [])
        self.assertFalse(edge_group(zones, 0, "R").interior)


class MatchTests(unittest.TestCase):
    def test_prefers_exact_title(self):
        wins = [
            WindowInfo(1, "Inbox - Google Chrome", "chrome.exe", "", "Chrome_WidgetWin_1", 1),
            WindowInfo(2, "YouTube - Google Chrome", "chrome.exe", "", "Chrome_WidgetWin_1", 1),
            WindowInfo(3, "YouTube", "Code.exe", "", "Chrome_WidgetWin_1", 2),
        ]
        sig = {"exe": "chrome.exe", "title": "YouTube - Google Chrome", "class_name": "Chrome_WidgetWin_1"}
        self.assertEqual(match_window(sig, wins, set()).hwnd, 2)
        self.assertEqual(match_window(sig, wins, {2}).hwnd, 1)   # falls back to same app
        self.assertIsNone(match_window({"exe": "spotify.exe"}, wins, set()))


class StoreTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            s = Store(p)
            s.put_layout(Layout("Mine", [Zone(0, 0, 0.7, 1), Zone(0.7, 0, 0.3, 1)]))
            s.put_workspace("Coding", {"layout": s.layouts[0].to_dict(), "slots": [None, None]})
            s.settings["gap"] = 8
            s.save()
            s2 = Store(p)
            self.assertEqual(s2.layouts[0].name, "Mine")
            self.assertAlmostEqual(s2.layouts[0].zones[0].w, 0.7)
            self.assertIn("Coding", s2.workspaces)
            self.assertEqual(s2.settings["gap"], 8)

    def test_corrupt_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            p.write_text("{not json")
            self.assertEqual(Store(p).layouts, [])


if __name__ == "__main__":
    unittest.main()
