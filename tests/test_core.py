"""Run with:  python -m unittest discover tests"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from windower_app.model import Layout, Rect, WindowInfo, Zone, match_window  # noqa: E402
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
        rects = [z.to_rect(AREA) for z in PRESETS[4].zones]  # 3 columns
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
