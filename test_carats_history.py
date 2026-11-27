"""Tests for carats_history.py: `uv run python -m unittest -v`."""
import tempfile
import unittest
from pathlib import Path

from carats_history import read_carats


class ReadCaratsTest(unittest.TestCase):
    def test_newest_first_old_rows_unknown_and_bad_lines_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "carats.csv"
            p.write_text("date,time,carats,image\n2026-11-24,10:00:00,25,a.png\n"
                         "garbage\n2026-11-25,16:00:00,?,b.png,team_trials\n", encoding="utf-8")
            rows = read_carats(p)
        self.assertEqual([(r["action"], r["carats"]) for r in rows], [("team_trials", "?"), ("", "25")])

    def test_missing_file_is_empty(self):
        self.assertEqual(read_carats(Path("nope.csv")), [])


if __name__ == "__main__":
    unittest.main()
