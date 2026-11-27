"""Tests for the must-buy part of skill_planner.py. No game and no database: `uv run python -m unittest -v`."""
import unittest

from skill_planner import take_must_buy

A = [(5, 3, [("A", 1, 0, 0, 5, 3)])]
W_AND_G = [(8, 4, [("W", 1, 0, 0, 8, 4)]),
           (20, 9, [("W", 1, 0, 0, 8, 0), ("G", 0, 0, 0, 20, 9)])]


class MustBuyTest(unittest.TestCase):
    def test_takes_the_option_that_includes_the_name_and_skips_the_unknown(self):
        forced, groups, left, skipped = take_must_buy([A, W_AND_G], 10, ["G", "X"])
        self.assertEqual(forced, [W_AND_G[1]])
        self.assertEqual((groups, left), ([A], 1))
        self.assertEqual(len(skipped), 1)
        self.assertTrue(skipped[0].startswith("X:"))

    def test_too_expensive_is_skipped_and_the_next_name_is_tried(self):
        forced, groups, left, skipped = take_must_buy([A, W_AND_G], 8, ["G", "A"])
        self.assertEqual((forced, left), ([A[0]], 5))
        self.assertTrue(skipped[0].startswith("G:"))

    def test_second_name_of_a_taken_chain_is_skipped(self):
        forced, _, left, skipped = take_must_buy([W_AND_G], 20, ["W", "G"])
        self.assertEqual((forced, left), ([W_AND_G[0]], 16))
        self.assertTrue(skipped[0].startswith("G:"))


if __name__ == "__main__":
    unittest.main()
