"""Run with:  python -m unittest discover tests"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from windower_app import fakewin, hotkeys  # noqa: E402
from windower_app.icons import png_bytes, rgba_from_black_white  # noqa: E402
from windower_app.model import (MIN_ZONE, Layout, Monitor, Rect, Screen, Slot, WindowInfo, Zone,  # noqa: E402
                                 clamp_crop, crop_from, dividers, edge_group, fit_aspect, fit_on_screen,
                                 match_window, monitor_at, move_edges, neighbour, node_edges, nodes,
                                 peek_rect, snap_value)
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


class HotkeyTests(unittest.TestCase):
    def test_off_registers_nothing(self):
        self.assertEqual(hotkeys.build("Off"), [])
        self.assertEqual(hotkeys.build("no such modifier"), [])

    def test_every_modifier_gives_unique_combinations(self):
        for name, mods in hotkeys.MODIFIER_CHOICES.items():
            if not mods:
                continue
            table = hotkeys.build(name)
            self.assertEqual(len(table), len(hotkeys.ACTIONS), name)
            combos = [(m, vk) for _hid, m, vk in table]
            self.assertEqual(len(set(combos)), len(combos), name)   # RegisterHotKey rejects duplicates
            for _hid, m, _vk in table:
                self.assertEqual(m & mods, mods, name)

    def test_move_and_swap_need_shift(self):
        table = {hid: m for hid, m, _vk in hotkeys.build("Ctrl+Alt")}
        for hid, (action, _arg, _shift, _vk) in hotkeys.ACTIONS.items():
            has_shift = bool(table[hid] & hotkeys.MOD_SHIFT)
            self.assertEqual(has_shift, action in ("move_to_zone", "swap_dir"), action)

    def test_describe(self):
        self.assertEqual(hotkeys.describe(1, "Ctrl+Alt"), "Ctrl+Alt+1")
        self.assertEqual(hotkeys.describe(19, "Ctrl+Alt"), "Ctrl+Alt+Shift+9")
        self.assertEqual(hotkeys.describe(20, "Win+Alt"), "Win+Alt+Left")
        self.assertEqual(hotkeys.describe(30, "Ctrl+Alt"), "Ctrl+Alt+Enter")
        self.assertEqual(hotkeys.describe(31, "Ctrl+Alt"), "Ctrl+Alt+W")


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


class RestoreTests(unittest.TestCase):
    MONITORS = [Monitor("A", Rect(0, 0, 1920, 1080), AREA, True),
                Monitor("B", Rect(1920, 0, 2560, 1440), Rect(1920, 0, 2560, 1400))]

    def test_on_screen_rect_is_kept(self):
        for r in (Rect(100, 100, 800, 600), Rect(1800, 50, 900, 700), Rect(-700, 10, 800, 600)):
            self.assertEqual(fit_on_screen(r, self.MONITORS), r)

    def test_off_screen_rect_comes_back(self):
        for r in (Rect(-32000, -32000, 160, 28), Rect(9000, 200, 800, 600), Rect(0, 5000, 3000, 2000)):
            f = fit_on_screen(r, self.MONITORS)
            self.assertTrue(AREA.x <= f.x and f.x + f.w <= AREA.x + AREA.w, r)
            self.assertTrue(AREA.y <= f.y and f.y + f.h <= AREA.y + AREA.h, r)

    def test_minimized_window_is_not_restored_to_parking_spot(self):
        hwnd, before = 1030, fakewin.get_rect(1030)
        fakewin.minimize(hwnd)
        saved = fakewin.save_placement(hwnd)
        self.assertIsNone(saved.rect)
        fakewin.place(hwnd, Rect(0, 0, 960, 1040))          # tiled by Windower
        fakewin.restore_placement(hwnd, saved)
        self.assertEqual(fakewin.get_rect(hwnd), before)
        self.assertFalse(fakewin.is_minimized(hwnd))


class IconTests(unittest.TestCase):
    def test_icon_alpha_recovered_from_black_and_white(self):
        # BGRA pixels: opaque red, 50% blue, fully transparent
        on_black = bytes([0, 0, 255, 0, 128, 0, 0, 0, 0, 0, 0, 0])
        on_white = bytes([0, 0, 255, 0, 255, 127, 127, 0, 255, 255, 255, 0])
        rgba = rgba_from_black_white(on_black, on_white)
        self.assertEqual(rgba[0:4], bytes([255, 0, 0, 255]))
        self.assertEqual(rgba[4:8], bytes([0, 0, 255, 128]))
        self.assertEqual(rgba[8:12], bytes(4))

    def test_png_is_well_formed(self):
        data = png_bytes(2, 1, bytes([255, 0, 0, 255, 0, 255, 0, 128]))
        self.assertTrue(data.startswith(bytes.fromhex("89504e470d0a1a0a")))
        self.assertEqual(data[12:16], b"IHDR")
        self.assertEqual(data[-8:-4], b"IEND")

    def test_demo_backend_has_icons(self):
        self.assertEqual(len(fakewin.window_icon(1010, 20)), 20 * 20 * 4)
        self.assertIsNone(fakewin.window_icon(4242, 20))


class MultiMonitorTests(unittest.TestCase):
    MONITORS = [Monitor("A", Rect(0, 0, 1920, 1080), AREA, True),
                Monitor("B", Rect(1920, 0, 2560, 1440), Rect(1920, 0, 2560, 1400))]

    def test_screen_starts_with_one_empty_slot_per_zone(self):
        scr = Screen(next(p for p in PRESETS if p.name == "Grid 2x2").copy())
        self.assertEqual(scr.slots, [None] * 4)
        self.assertFalse(scr.adjusted)

    def test_monitor_at(self):
        self.assertEqual(monitor_at(self.MONITORS, 10, 10), 0)
        self.assertEqual(monitor_at(self.MONITORS, 1920, 1200), 1)
        self.assertIsNone(monitor_at(self.MONITORS, 100, 1200))     # below the smaller monitor

    def test_neighbour_crosses_monitors(self):
        left = [z.to_rect(self.MONITORS[0].work) for z in (Zone(0, 0, 0.5, 1), Zone(0.5, 0, 0.5, 1))]
        right = [z.to_rect(self.MONITORS[1].work) for z in (Zone(0, 0, 1, 0.5), Zone(0, 0.5, 1, 0.5))]
        rects = left + right
        self.assertEqual(neighbour(rects, 1, "right"), 2)   # onto monitor B, top zone overlaps most
        self.assertEqual(neighbour(rects, 3, "left"), 1)
        self.assertEqual(neighbour(rects, 2, "down"), 3)
        self.assertIsNone(neighbour(rects, 0, "left"))


class ZoneEditTests(unittest.TestCase):
    """Adding, splitting and removing zones from the preview keeps each window in its zone."""

    def setUp(self):
        self.scr = Screen(Layout("2 columns", [Zone(0, 0, 0.5, 1), Zone(0.5, 0, 0.5, 1)]))
        self.a, self.b = Slot(hwnd=1, exe="a.exe"), Slot(hwnd=2, exe="b.exe")
        self.scr.slots = [self.a, self.b]

    def test_add_zone_goes_on_top_and_empty(self):
        i = self.scr.add_zone(Zone(0.6, 0.6, 0.3, 0.3))
        self.assertEqual(i, 2)
        self.assertEqual(self.scr.slots, [self.a, self.b, None])
        self.assertTrue(self.scr.adjusted)
        self.assertEqual(self.scr.layout.zones[-1], Zone(0.6, 0.6, 0.3, 0.3))

    def test_split_keeps_window_in_first_half(self):
        n = self.scr.split_zone(1, vertical=False)
        self.assertEqual(n, 2)
        self.assertEqual(self.scr.slots, [self.a, self.b, None])
        self.assertEqual(self.scr.layout.zones[1:], [Zone(0.5, 0, 0.5, 0.5), Zone(0.5, 0.5, 0.5, 0.5)])

    def test_split_first_zone_shifts_the_rest(self):
        self.scr.split_zone(0, vertical=True)
        self.assertEqual(self.scr.slots, [self.a, None, self.b])
        self.assertEqual(len(self.scr.layout.zones), 3)

    def test_remove_zone_returns_its_window(self):
        self.scr.add_zone(Zone(0.1, 0.1, 0.2, 0.2))
        self.scr.selected = 2
        self.assertIs(self.scr.remove_zone(0), self.a)
        self.assertEqual(self.scr.slots, [self.b, None])
        self.assertEqual(len(self.scr.layout.zones), 2)
        self.assertEqual(self.scr.selected, 1)        # still the same (drawn) zone

    def test_snap_value(self):
        self.assertEqual(snap_value(0.49, [0.0, 0.5, 1.0], 0.02), 0.5)
        self.assertEqual(snap_value(0.45, [0.0, 0.5, 1.0], 0.02), 0.45)
        self.assertEqual(snap_value(0.3, [], 0.1), 0.3)


class ZoomTests(unittest.TestCase):
    def test_fit_aspect_centres_and_keeps_proportions(self):
        self.assertEqual(fit_aspect(Rect(0, 0, 400, 400), 200, 100), Rect(0, 100, 400, 200))
        self.assertEqual(fit_aspect(Rect(10, 0, 400, 100), 100, 100), Rect(160, 0, 100, 100))

    def test_clamp_crop_to_a_smaller_window(self):
        self.assertEqual(clamp_crop(Rect(50, 50, 100, 100), 800, 600), Rect(50, 50, 100, 100))
        self.assertEqual(clamp_crop(Rect(700, 500, 200, 200), 800, 600), Rect(700, 500, 100, 100))
        self.assertIsNone(clamp_crop(Rect(900, 50, 100, 100), 800, 600))

    def test_crop_saved_in_workspace(self):
        s = Slot(1, "YouTube", "chrome.exe", crop=Rect(10, 20, 640, 360))
        sig = s.signature()
        self.assertEqual(sig["crop"], [10, 20, 640, 360])
        self.assertEqual(crop_from(sig["crop"]), Rect(10, 20, 640, 360))
        self.assertNotIn("crop", Slot(1, "x", "a.exe").signature())      # old format unchanged
        for bad in (None, [1, 2, 3], ["a", 1, 2, 3], [0, 0, 2, 2]):
            self.assertIsNone(crop_from(bad), bad)

    def test_peek_centres_the_area_on_the_view(self):
        frame, client = Rect(100, 100, 800, 600), Rect(100, 130, 800, 570)
        crop, view = Rect(200, 100, 100, 50), Rect(1000, 500, 400, 200)
        r = peek_rect(frame, client, crop, view, Rect(0, 0, 1920, 1040))
        self.assertEqual((r.w, r.h), (800, 600))                     # moved, not resized
        cx = r.x + (client.x - frame.x) + crop.x + crop.w / 2
        cy = r.y + (client.y - frame.y) + crop.y + crop.h / 2
        self.assertEqual((cx, cy), (1200, 600))

    def test_peek_keeps_the_area_on_the_monitor(self):
        frame, client = Rect(0, 0, 800, 600), Rect(0, 30, 800, 570)
        crop = Rect(0, 0, 300, 100)
        view = Rect(1800, 0, 120, 60)                                # tiny view in the top-right corner
        r = peek_rect(frame, client, crop, view, Rect(0, 0, 1920, 1040))
        left = r.x + crop.x
        top = r.y + 30 + crop.y
        self.assertEqual(left + crop.w, 1920)                        # pushed back inside
        self.assertEqual(top, 0)


if __name__ == "__main__":
    unittest.main()
