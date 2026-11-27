"""Tests for action_store.py. They need no game, no Qt and no OpenCV: `uv run python -m unittest -v`."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from action_store import ActionStore


def seed(**overrides):
    base = [
        {"name": "daily_runs", "order_idx": 1, "enabled": 1,
         "settings": {"runs": 3, "mode": "fast"},
         "info": {"description": "Daily runs", "options": {"mode": ["fast", "slow"]}}},
        {"name": "club_daily", "order_idx": 2, "enabled": 0, "settings": {}, "info": {"description": "Club"}},
    ]
    return overrides.get("seed", base)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.day = ["2026-11-22"]
        self.make()

    def make(self, seed_actions=None, old_keys=None):
        self.store = ActionStore(self.dir / "t.db", seed_actions or seed(), self.dir / "templates",
                                 old_keys, today=lambda: self.day[0])
        (self.dir / "templates").mkdir(exist_ok=True)
        self.store.init()
        return self.store

    # ---- seeding and migration ----
    def test_init_seeds_actions_in_order(self):
        self.assertEqual([a["name"] for a in self.store.actions()], ["daily_runs", "club_daily"])
        first = self.store.action("daily_runs")
        self.assertTrue(first["enabled"])
        self.assertEqual(first["settings"], {"runs": 3, "mode": "fast"})

    def test_init_twice_keeps_user_values_but_takes_new_keys_info_and_order(self):
        self.store.save("daily_runs", False, {"runs": 9, "mode": "slow"})
        newer = seed()
        newer[0]["settings"] = {"runs": 3, "mode": "fast", "extra": True}
        newer[0]["info"] = {"description": "Daily runs v2", "options": {"mode": ["fast", "slow"]}}
        newer[0]["order_idx"] = 5
        self.make(newer)
        a = self.store.action("daily_runs")
        self.assertFalse(a["enabled"])
        self.assertEqual(a["settings"], {"runs": 9, "mode": "slow", "extra": True})
        self.assertEqual(a["info"]["description"], "Daily runs v2")
        self.assertEqual([x["name"] for x in self.store.actions()], ["club_daily", "daily_runs"])

    def test_value_no_longer_in_options_goes_back_to_default(self):
        self.store.save("daily_runs", True, {"runs": 3, "mode": "turbo"})
        self.make()
        self.assertEqual(self.store.action("daily_runs")["settings"]["mode"], "fast")

    def test_removed_action_is_deleted(self):
        with sqlite3.connect(self.store.db_path) as c:
            c.execute("INSERT INTO actions VALUES('clear_popups',9,1,'{}','{}')")
        self.make()
        self.assertIsNone(self.store.action("clear_popups"))

    def test_old_item_keys_move_to_new_names_and_template_files_are_renamed(self):
        newer = seed()
        newer[0]["settings"] = {"star": False}
        newer[0]["info"] = {}
        self.make(newer)
        self.store.save("daily_runs", True, {"star": False})
        with sqlite3.connect(self.store.db_path) as c:           # what an old install stored
            c.execute("UPDATE actions SET settings=? WHERE name='daily_runs'", (json.dumps({"item_1": True}),))
        templates = self.dir / "templates"
        (templates / "legend_item_1.png").write_bytes(b"old")
        self.make(newer, old_keys={"item_1": "star"})
        self.assertEqual(self.store.action("daily_runs")["settings"], {"star": True})
        self.assertFalse((templates / "legend_item_1.png").exists())
        self.assertEqual((templates / "legend_item_star.png").read_bytes(), b"old")

    def test_rename_never_overwrites_an_existing_new_file(self):
        templates = self.dir / "templates"
        (templates / "legend_item_1.png").write_bytes(b"old")
        (templates / "legend_item_star.png").write_bytes(b"new")
        self.make(old_keys={"item_1": "star"})
        self.assertEqual((templates / "legend_item_star.png").read_bytes(), b"new")
        self.assertTrue((templates / "legend_item_1.png").exists())

    # ---- actions ----
    def test_save_and_read_back_one_action(self):
        self.store.save("club_daily", True, {"x": 1})
        a = self.store.action("club_daily")
        self.assertTrue(a["enabled"])
        self.assertEqual(a["settings"], {"x": 1})

    def test_unknown_action_is_none(self):
        self.assertIsNone(self.store.action("nope"))

    # ---- today's progress ----
    def test_status_defaults_to_pending_and_can_be_set_and_reset(self):
        self.assertEqual(self.store.status("daily_runs"), "pending")
        self.store.set_status("daily_runs", "done", "ok")
        self.assertEqual(self.store.status("daily_runs"), "done")
        self.store.reset_today()
        self.assertEqual(self.store.status("daily_runs"), "pending")

    def test_status_belongs_to_the_day(self):
        self.store.set_status("daily_runs", "done")
        self.day[0] = "2026-11-23"
        self.assertEqual(self.store.status("daily_runs"), "pending")
        self.store.reset_today()                                  # resets the new day only
        self.day[0] = "2026-11-22"
        self.assertEqual(self.store.status("daily_runs"), "done")

    # ---- snapshot ----
    def test_snapshot_is_actions_plus_status(self):
        self.store.set_status("club_daily", "failed")
        snap = self.store.snapshot()
        self.assertEqual([(a["name"], a["status"]) for a in snap],
                         [("daily_runs", "pending"), ("club_daily", "failed")])
        for a, plain in zip(snap, self.store.actions()):
            self.assertEqual({k: v for k, v in a.items() if k != "status"}, plain)

    def test_snapshot_opens_one_connection(self):
        with mock.patch("action_store.sqlite3.connect", wraps=sqlite3.connect) as connect:
            self.store.snapshot()
        self.assertEqual(connect.call_count, 1)

    # ---- app settings ----
    def test_app_setting_default_set_and_replace(self):
        self.assertEqual(self.store.app_setting("window_title", "Game"), "Game")
        self.store.set_app_setting("window_title", "A")
        self.store.set_app_setting("window_title", "B")
        self.assertEqual(self.store.app_setting("window_title", "Game"), "B")


if __name__ == "__main__":
    unittest.main()
