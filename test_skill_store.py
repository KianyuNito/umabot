"""Tests for skill_store.py. No game, no Qt, no OpenCV: `uv run python -m unittest -v`."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from skill_store import SkillStore

ROWS = [("Corner Recovery", 1, 100, "[]", 1, 1), ("Corner Recovery", 2, 150, "[]", 1, 2),
        ("Straightaway Adept", 0, 80, "[]", 2, 1)]


class SkillStoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "skills.db"
        self.store = SkillStore(self.path)

    def test_empty_file_has_no_skills_and_import_fills_it(self):
        self.assertEqual(self.store.count(), 0)
        self.store.replace_skills(ROWS)
        self.assertEqual(self.store.count(), 3)
        self.assertEqual(self.store.pairs(), {("Corner Recovery", 1), ("Corner Recovery", 2), ("Straightaway Adept", 0)})
        self.assertEqual(sorted(self.store.names()), ["Corner Recovery", "Straightaway Adept"])

    def test_reimport_updates_and_deletes_skills_no_longer_listed(self):
        self.store.replace_skills(ROWS)
        self.store.replace_skills([("Corner Recovery", 1, 999, "[]", 1, 1)])
        self.assertEqual([(r[0], r[1], r[2]) for r in self.store.items()], [("Corner Recovery", 1, 999)])

    def test_save_scan_replaces_old_costs_and_remembers_points(self):
        self.store.replace_skills(ROWS)
        self.store.save_scan({("Corner Recovery", 1): 120, ("Straightaway Adept", 0): 90}, 450)
        self.store.save_scan({("Corner Recovery", 1): 130}, 400)
        costs = {(r[0], r[1]): r[6] for r in self.store.items()}
        self.assertEqual(costs, {("Corner Recovery", 1): 130, ("Corner Recovery", 2): None, ("Straightaway Adept", 0): None})
        self.assertEqual(self.store.meta("points"), "400")

    def test_old_format_table_is_kept_and_its_costs_carried_over_on_import(self):
        with sqlite3.connect(self.path) as c:      # old format: has tier and cost, no base
            c.execute("CREATE TABLE skills(name TEXT, tier INTEGER, cost INTEGER)")
            c.execute("INSERT INTO skills VALUES('Corner Recovery', 1, 77)")
        self.assertEqual(self.store.count(), 0)    # first call renamed it to skills_old
        self.assertEqual(self.store.replace_skills(ROWS), 1)
        costs = {(r[0], r[1]): r[6] for r in self.store.items()}
        self.assertEqual(costs[("Corner Recovery", 1)], 77)
        with sqlite3.connect(self.path) as c:
            self.assertIsNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='skills_old'").fetchone())

    def test_meta_roundtrip_and_missing_key(self):
        self.assertIsNone(self.store.meta("apt"))
        self.store.set_meta("apt", "a")
        self.store.set_meta("apt", "b")
        self.assertEqual(self.store.meta("apt"), "b")


if __name__ == "__main__":
    unittest.main()