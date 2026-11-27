"""Tests for template_catalog.py. No game, no Qt: `uv run python -m unittest -v`. The save test needs OpenCV."""
import tempfile
import unittest
from pathlib import Path

from template_catalog import TemplateCatalog

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None


class CatalogTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "templates"
        self.dir.mkdir()
        self.cat = TemplateCatalog(self.dir, ["special_week", "vodka"], {"legend_next_btn"}, ["home", "race"],
                                   ["sprint", "dirt"])

    def touch(self, *names):
        for n in names:
            (self.dir / f"{n}.png").write_bytes(b"x")

    def test_path_exists_and_missing(self):
        self.touch("home_btn")
        self.assertEqual(self.cat.path("home_btn"), self.dir / "home_btn.png")
        self.assertTrue(self.cat.exists("home_btn"))
        self.assertEqual(self.cat.missing(["home_btn", "race_btn", "x"]), ["race_btn", "x"])

    def test_markers_are_the_suggested_ones_then_extra_files(self):
        self.touch("screen_home", "screen_my_own")
        self.assertEqual(self.cat.markers(), ["screen_home", "screen_race", "screen_my_own"])

    def test_legends_skip_utility_race_and_item_pictures_but_add_your_own_tiles(self):
        self.touch("legend_vodka", "legend_next_btn", "legend_x_race", "legend_item_mood_boost", "legend_my_uma")
        self.assertEqual(self.cat.available_legends(), ["special_week", "vodka", "my_uma"])

    def test_agendas(self):
        self.touch("agenda_b", "agenda_a", "home_btn")
        self.assertEqual(self.cat.available_agendas(), ["a", "b"])

    def test_picker_lists_missing_first_without_duplicates(self):
        names = self.cat.picker_names(["race_btn"], ["race_btn", "home_btn"])
        self.assertEqual(names[:3], ["race_btn", "home_btn", "screen_home"])
        self.assertEqual(len(names), len(set(names)))
        for n in ("legend_vodka", "club_item_dirt_shoes", "club_request_cancel_btn", "empty_5"):
            self.assertIn(n, names)

    @unittest.skipUnless(cv2, "needs OpenCV")
    def test_save_writes_a_png_and_makes_the_folder(self):
        cat = TemplateCatalog(self.dir / "new_folder", [], [], [], [])
        self.assertTrue(cat.save("btn", np.zeros((10, 12, 3), np.uint8)))
        self.assertEqual(cv2.imread(str(cat.path("btn"))).shape, (10, 12, 3))


if __name__ == "__main__":
    unittest.main()