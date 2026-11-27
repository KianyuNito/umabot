"""do_steps retries a failing step, but not a block whose inner steps were already retried."""
import threading
import unittest

from engine import Runner, StepFailed


class FailingRunner(Runner):
    def __init__(self):
        super().__init__(None, lambda *_: None, threading.Event())
        self.calls = 0

    def do_step(self, step, settings):
        self.calls += 1
        raise StepFailed("nope")

    def sleep(self, seconds):
        pass


class RetryTest(unittest.TestCase):
    def tries(self, kind):
        runner = FailingRunner()
        with self.assertRaises(StepFailed):
            runner.do_steps([{"type": kind, "template": "x"}], {})
        return runner.calls

    def test_a_plain_step_is_tried_three_times(self):
        self.assertEqual(self.tries("tap"), 3)

    def test_a_block_is_not_run_again_after_its_inner_steps_failed(self):
        self.assertEqual(self.tries("if_visible"), 1)
        self.assertEqual(self.tries("popup_watch"), 1)