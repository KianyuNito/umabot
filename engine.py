"""
umabot engine (PC version, Windows only)

- Captures the game window straight from the screen (no emulator / ADB needed)
- Finds buttons with template matching and clicks them with the real mouse
- Stores actions (info = how, settings = user choices) and a daily checklist in SQLite
"""
import datetime
import json
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from config import (
    BASE, TEMPLATE_DIR, DEBUG_DIR, RECORD_DIR, CARATS_CSV,
    REF_HEIGHT, DONE_THRESHOLD, DEFAULT_WINDOW_TITLE,
    POPUP_TEMPLATES, POPUP_GRACE, CLICK_DELAY, STOP_KEY,
    ITEM_KEYS, MAX_ITEMS,
)
from vision import (load_template, best_score, find,
                    find_all, detect_screen, read_count, screen_label)
from app_store import store, catalog
from window import GameWindow, GameNotFound, FocusFailed


class StepFailed(Exception):
    pass


class Stopped(Exception):
    pass


class StepSkipped(Exception):
    """Raised inside a running step when the user presses 'Skip current step'."""


class AlreadyDone(Exception):
    """Raised by a 'finish_if_visible' step: the game already shows the action as complete, so stop it here as done."""


def step_enabled(step, settings):
    """A step with only_if (one setting name or a list) runs only when all of those settings are on."""
    cond = step.get("only_if")
    if cond:
        keys = [cond] if isinstance(cond, str) else cond
        if not all(settings.get(k) for k in keys):
            return False
    skip = step.get("unless")          # runs only when this setting (or list of settings) is OFF
    if skip:
        keys = [skip] if isinstance(skip, str) else skip
        if any(settings.get(k) for k in keys):
            return False
    return True


def _enabled_count(steps, settings, first=0, upto=None):
    """How many of these steps the runner would show as enabled."""
    return sum(1 for s in steps[first:upto] if step_enabled(s, settings))


def action_total(name, settings=None, action=None):
    """Expected number of top-level steps for the Tasks bar. Loops and shortcuts make it an estimate.
    Pass `action` (an entry from snapshot()) to skip the database read."""
    act = action or store.action(name)
    if not act:
        return 0
    info, settings = act["info"], settings or act["settings"]
    total = 0
    for phase in ("navigate", "enter", "run_steps", "back", "exit"):
        steps = info.get(phase, [])
        if phase == "run_steps" and "repeat_from" in info:       # team trials: the repeated part runs once per race
            k = info["repeat_from"]
            races = max(1, min(5, int(settings.get("races", 1))))
            total += _enabled_count(steps, settings, 0, k) + races * _enabled_count(steps, settings, k)
        else:
            total += _enabled_count(steps, settings)
    return total


# --------------------------------------------------------------------------
# DATABASE
# --------------------------------------------------------------------------


def init_db():
    TEMPLATE_DIR.mkdir(exist_ok=True)
    store.init()


def _step_templates(steps, settings, names, include_off=False):
    for st in steps:
        if not include_off and not step_enabled(st, settings):
            continue
        for key in ("template", "anchor", "checkbox", "stop_template"):
            t = st.get(key)
            if t:
                try:
                    names.add(t.format(**settings))
                except KeyError:
                    names.add(t)
        for key, t in st.get("anchors", {}).items():             # only the items ticked in Settings
            if include_off or settings.get(key):
                names.add(t)
        _step_templates(st.get("steps", []), settings, names, include_off)      # steps nested inside if_visible
        _step_templates(st.get("else_steps", []), settings, names, include_off)


def required_templates():
    names = set()
    for a in store.actions():
        for key in ("done_marker", "home_marker"):
            if a["info"].get(key):
                names.add(a["info"][key])
        names.update(a["info"].get("suggested", []))
        for phase in ("navigate", "enter", "run_steps", "back", "exit"):
            _step_templates(a["info"].get(phase, []), a["settings"], names)
    return sorted(names)


def capturable_templates():
    """Every template name the capture dialog should offer: the ones the current settings need, plus those of
    steps that are switched off by a checkbox (e.g. the skill-learning pictures while 'learn_skills' is unticked)."""
    names = set(required_templates())
    for a in store.actions():
        for phase in ("navigate", "enter", "run_steps", "back", "exit"):
            _step_templates(a["info"].get(phase, []), a["settings"], names, include_off=True)
    return sorted(names)


def missing_templates():
    return catalog.missing(required_templates())


# --------------------------------------------------------------------------
# STEP ENGINE
# --------------------------------------------------------------------------


STILL_MEAN_DIFF = 0.5   # mean pixel change below this means the list did not move

def screens_still(before, after):
    return before.shape == after.shape and float(cv2.absdiff(before, after).mean()) < STILL_MEAN_DIFF

def list_moved(before, after):
    return not screens_still(before, after)


class Runner:
    def __init__(self, game, log, stop_event, skip_event=None, pause_event=None):
        self.game, self.log, self.stop_event = game, log, stop_event
        self.skip_event = skip_event or threading.Event()
        self.pause_event = pause_event or threading.Event()
        self.paused_total = 0.0   # seconds spent paused, so timeouts don't count them
        self._warned = set()
        self.start_at = None     # (phase, step index) to resume from; earlier phases are skipped.
                                 # the index may be a path like (1, 0) = step 2.1, i.e. inside an if_visible block
        self.nested_start = ()   # rest of that path, handed down to the if_visible block being entered
        self.popup_watch = False  # True between the end of a race and getting back home (see POPUP_TEMPLATES)
        self.titles = {}          # phase -> title, same names as the "start at" list
        self.notes = []           # things recorded during the action (e.g. carats earned), added to its result
        self.action = ""          # name of the action running now, written to carats.csv
        self.apt = None          # aptitude letters read on the Complete Career screen (skill plan)
        self._path, self._title = [], ""   # step number(s) being run, for the log
        self.step_done, self.step_total, self.on_step = 0, 0, None   # Tasks card: finished steps of this action

    def _emit(self):
        if self.on_step:
            self.on_step(self.step_done, self.step_total)

    def check_stop(self):
        if self.pause_event.is_set():
            self.log("    paused: waiting for Resume")
            t0 = time.time()
            while self.pause_event.is_set() and not self.stop_event.is_set() and not self.skip_event.is_set():
                time.sleep(0.2)
            self.paused_total += time.time() - t0
            if self.pause_event.is_set() and not self.stop_event.is_set():
                self.log("    skip pressed while paused: skipping this step, still paused")
            else:
                self.log("    resumed")
        if self.stop_event.is_set():
            raise Stopped()
        if self.skip_event.is_set():
            raise StepSkipped()

    def now(self):
        """Clock that ignores time spent paused."""
        return time.time() - self.paused_total

    def sleep(self, seconds):
        end = self.now() + seconds
        while self.now() < end:
            self.check_stop()
            time.sleep(max(0, min(0.1, end - self.now())))

    def wait_for(self, template, timeout, poll=0.2):
        start = self.now()
        end = start + timeout
        while self.now() < end:
            self.check_stop()
            shot = self.game.screenshot()
            hit = find(shot, template)
            if hit:
                return hit
            # what we want isn't there yet: if it has been a while, a known popup may be covering it
            if self.popup_watch and self.now() - start >= POPUP_GRACE and self.dismiss_popup(shot, template):
                continue
            self.sleep(poll)
        return None

    def any_visible(self, names, wait=0, poll=0.7):
        """True when ANY of the pictures is on screen (looks for up to `wait` seconds). Pictures that haven't been
        captured yet are ignored; if none of them exists, that is an error like for a single picture."""
        have = [n for n in names if catalog.exists(n)]
        if not have:
            raise FileNotFoundError(f"Missing template: templates\\{names[0]}.png")
        end = self.now() + wait
        while True:
            self.check_stop()
            shot = self.game.screenshot()
            if any(find(shot, n) for n in have):
                return True
            if self.now() >= end:
                return False
            self.sleep(poll)

    def dismiss_popup(self, shot, wanted):
        """Close a popup that can appear at any moment (e.g. the Daily Sale) when it is blocking the screen."""
        for name in POPUP_TEMPLATES:
            if name == wanted or not catalog.exists(name):
                continue
            hit = find(shot, name)
            if hit:
                self.log(f"    popup in the way ('{name}'), closing it")
                self.game.tap(hit[0], hit[1])
                self.sleep(1.0)
                return True
        return False

    def save_debug(self, label):
        DEBUG_DIR.mkdir(exist_ok=True)
        path = DEBUG_DIR / f"{int(time.time())}_{label}.png"
        cv2.imwrite(str(path), self.game.screenshot())
        self.log(f"    debug screenshot saved: debug\\{path.name}")

    def scrollbar_state(self, bar_x, y1=200, y2=812):
        """Find the list's scroll bar around x=bar_x. Returns (x, thumb_top, thumb_bottom, track_top, track_bottom)
        or None when there is no scroll bar on screen (list shorter than the box, or a different screen)."""
        screen = self.game.screenshot()
        x0 = max(0, bar_x - 16)
        strip = screen[y1:y2, x0:bar_x + 17].astype(int)             # BGR
        thumb = (np.abs(strip - np.array([140, 121, 123])).max(axis=2) <= 22)   # the dark grey handle
        track = (np.abs(strip - np.array([217, 210, 211])).max(axis=2) <= 22)   # the light grey groove
        counts = thumb.sum(axis=0)
        if counts.max() < 15:
            return None
        col = int(counts.argmax())
        rows_thumb = np.where(thumb[:, max(0, col - 1):col + 2].sum(axis=1) >= 2)[0]
        rows_track = np.where((thumb | track)[:, max(0, col - 1):col + 2].sum(axis=1) >= 2)[0]
        if len(rows_thumb) < 15 or len(rows_track) < 100:
            return None
        return (x0 + col, y1 + int(rows_thumb.min()), y1 + int(rows_thumb.max()),
                y1 + int(rows_track.min()), y1 + int(rows_track.max()))

    def drag_scrollbar_to_bottom(self, bar_x, tries=4):
        """Grab the scroll bar's handle and pull it to the end of its groove. Nothing in the list is pressed, so
        item icons / info buttons can't be tapped by accident. False = no scroll bar found (caller falls back)."""
        for i in range(tries):
            st = self.scrollbar_state(bar_x)
            if st is None:
                return False
            x, t0, t1, k0, k1 = st
            if k1 - t1 <= 6:
                self.log(f"    reached the bottom of the list (scroll bar is at the end)")
                return True
            self.log(f"    dragging the scroll bar down ({i + 1}/{tries})")
            self.game.drag(x, (t0 + t1) // 2, x, k1 + 20, duration=0.5)
            self.sleep(0.7)
        return False

    def scroll_find(self, template, sc):
        """Look for a template by scrolling the list: up first (to the top), then down (to the bottom).

        Stops a direction when the screen stops changing, i.e. the end of the list was reached.
        """
        tries = int(sc.get("tries", 6)) * 2
        x, a, b = sc["x"], sc["from_y"], sc["to_y"]          # dragging a -> b scrolls DOWN, b -> a scrolls UP
        for label, y1, y2 in (("up", b, a), ("down", a, b)):
            for i in range(tries):
                before = self.game.screenshot()
                self.log(f"    '{template}' not visible, scrolling {label} ({i + 1}/{tries})")
                self.game.drag(x, y1, x, y2)
                self.sleep(0.8)
                after = self.game.screenshot()
                hit = find(after, template)
                if hit:
                    return hit
                if screens_still(before, after):
                    self.log(f"    reached the {'top' if label == 'up' else 'bottom'} of the list")
                    break
        return None

    def do_step(self, step, settings):
        if not step_enabled(step, settings):
            return
        if step["type"] not in ("tick_rows", "tap_all"):   # these re-read the screen after each tap, so they keep their own wait
            step = dict(step, after=0, delay=CLICK_DELAY)   # no pause after clicks; every button waits CLICK_DELAY before its click
        template = step.get("template", "").format(**settings)
        optional, timeout, kind = step.get("optional", False), step.get("timeout", 10), step["type"]

        if kind == "sleep":
            self.sleep(step.get("seconds", 1))
        elif kind == "popup_watch":
            self.popup_watch = bool(step.get("on", True))
            if step.get("steps"):                       # steps nested under the watch step (e.g. 17.1)
                if self.nested_start:
                    sub, self.nested_start = self.nested_start, ()
                    self.nested_start = sub[1:]
                    self.do_steps(step["steps"], settings, first=sub[0])
                    self.nested_start = ()
                else:
                    self.do_steps(step["steps"], settings)
        elif kind == "tap_xy":
            y = step["y"]
            by = step.get("y_by")             # y picked by a setting, e.g. which opponent card to tap
            if by:
                y = by["values"].get(str(settings.get(by["setting"])), y)
            self.sleep(2.0)   # wait before a fixed-spot click (no picture to re-check, so give the screen time)
            self.game.tap(step["x"], y)
            self.sleep(step.get("after", 0.4))
        elif kind == "scroll_bottom":
            # drag the list up until it stops moving (= bottom reached). "region" = [top_y, bottom_y] of the list,
            # so animations elsewhere on the screen don't count as movement
            sc = step["scroll"]
            y1, y2 = step.get("region", [0, REF_HEIGHT])
            if sc.get("bar_x") and self.drag_scrollbar_to_bottom(sc["bar_x"]):
                return
            if sc.get("bar_x"):
                self.log("    scroll bar not found: dragging the list instead")
            drag_time, settle = sc.get("duration", 0.25), sc.get("settle", 0.5)   # faster than before (0.5s / 0.8s)
            prev = None
            reached = False
            for i in range(sc.get("tries", 30)):
                screen = self.game.screenshot()[y1:y2]
                if prev is not None and screens_still(prev, screen):
                    self.log(f"    reached the bottom of the list (after {i} scrolls)")
                    reached = True
                    break
                prev = screen
                self.game.drag(sc["x"], sc["from_y"], sc["x"], sc["to_y"], duration=drag_time)
                self.sleep(settle)
            if not reached:
                self.log(f"    scrolled {sc.get('tries', 30)} times without hitting the bottom; carrying on")
        elif kind == "read_aptitudes":
            from skill_plan_step import read_aptitudes
            self.apt = read_aptitudes(self.game.screenshot())
            self.log(f"    aptitudes: {self.apt}")
        elif kind == "plan_skills":
            from skill_plan_step import plan_skills
            plan_skills(self.game, self.log, self.check_stop, self.sleep,
                        self.apt, str(BASE / "skills.db"), self.notes,
                        store.app_setting("must_buy", "").splitlines())
        elif kind == "record_carats":
            self.record_carats(template, step.get("crop"), step.get("label", "the finished run"))
        elif kind == "tick_rows":
            self.tick_rows(step, settings)
        elif kind == "tap_all":
            self.tap_all(step, settings)
        elif kind == "tap_times":
            # tap one button several times in a row (the + / - in the Multi-Race window). The count is fixed
            # ("times") or comes from a setting ("times_setting") minus "minus".
            n = step.get("times")
            if n is None:
                n = int(settings.get(step["times_setting"], 1)) - step.get("minus", 0)
            n = max(0, int(n))
            if n == 0:
                return
            hit = self.wait_for(template, timeout)
            if not hit:
                if optional:
                    self.log(f"    '{template}' not on screen: not tapping it")
                    return
                self.save_debug(f"fail_{template}")
                raise StepFailed(f"'{template}' not found within {timeout}s")
            self.sleep(step.get("delay", CLICK_DELAY))
            for _ in range(n):
                self.check_stop()
                self.game.tap(hit[0], hit[1])
                self.sleep(step.get("after", 0.4))
        elif kind in ("tap", "wait"):
            hit = self.wait_for(template, timeout)
            sc = step.get("scroll")
            if not hit and sc:
                hit = self.scroll_find(template, sc)
            if not hit and kind == "tap" and step.get("fallback_xy"):
                # picture not found: tap a fixed spot instead
                fx, fy = step["fallback_xy"]
                self.save_debug(f"fallback_{template}")      # keep what the bot saw, to find out why it didn't match
                self.log(f"    '{template}' not found, tapping its usual spot ({fx}, {fy}) instead")
                self.game.tap(fx, fy)
                self.sleep(step.get("after", 0.4))
                return
            if not hit:
                if optional:
                    return
                self.save_debug(f"fail_{template}")
                raise StepFailed(f"'{template}' not found within {timeout}s"
                                 + (" (even after scrolling up and down)" if sc else ""))
            if kind == "tap":
                # button spotted: give the screen a moment to settle, then look again (it may have slid a little)
                # and click where it is now. "delay" on a step overrides CLICK_DELAY.
                self.sleep(step.get("delay", CLICK_DELAY))
                hit = find(self.game.screenshot(), template) or hit
                self.game.tap(hit[0], hit[1])
                self.sleep(step.get("after", 0.4))
                if step.get("repeat_until_gone"):
                    for _ in range(10):
                        h = find(self.game.screenshot(), template)
                        if not h:
                            break
                        self.game.tap(h[0], h[1])
                        self.sleep(step.get("after", 0.4))
        elif kind == "finish_if_visible":
            # the template is on screen right now = the game already shows this action as complete: end it as "done"
            wait = step.get("wait", 0)
            try:
                seen = bool(self.wait_for(template, wait) if wait else find(self.game.screenshot(), template))
            except FileNotFoundError as e:
                if not step.get("skip_if_missing"):
                    raise
                self.log(f"    ({e}: not checking this until it is captured)")
                return
            if seen:
                raise AlreadyDone(step.get("detail", "already completed"))
            self.log(f"    ('{template}' not on screen: carrying on)")
        elif kind == "if_visible":
            # run the nested steps only when the template is on screen right now (e.g. an empty slot to fill).
            # negate=True flips it: run them only when it is NOT on screen (e.g. a tab that isn't selected yet).
            # wait=N looks for up to N seconds before deciding, in case the screen is still loading.
            negate, wait = step.get("negate", False), step.get("wait", 0)
            if self.nested_start:
                # "start at" points at a step inside this block: skip the check and go straight in
                sub, self.nested_start = self.nested_start, ()
                self.nested_start = sub[1:]
                self.log("    (starting inside this block: its on-screen check is skipped)")
                self.do_steps(step["steps"], settings, first=sub[0])
                self.nested_start = ()
                return
            try:
                if step.get("also"):
                    seen = self.any_visible([template] + list(step["also"]), wait)
                else:
                    seen = bool(self.wait_for(template, wait) if wait else find(self.game.screenshot(), template))
            except FileNotFoundError as e:
                if not step.get("skip_if_missing"):
                    raise
                # optional check whose picture hasn't been captured yet: treat it as "not on screen"
                self.log(f"    ({e}: skipping those steps until it is captured)")
                return
            if seen != negate:
                self.do_steps(step["steps"], settings)
            elif step.get("else_steps"):
                # optional "else" branch: runs only when the condition above was NOT met
                self.log(f"    ('{template}' {'is on screen' if negate else 'not on screen'}, running the else steps)")
                self.do_steps(step["else_steps"], settings)
            elif negate:
                self.log(f"    ('{template}' is already on screen, skipping those steps)")
            else:
                self.log(f"    ('{template}' not on screen, skipping those steps)")
        elif kind == "tap_below":
            # find the anchor (e.g. an agenda's name), then tap the nearest `template` button just below it
            anchor = step["anchor"].format(**settings)
            sc, max_dy = step.get("scroll"), step.get("max_dy", 200)
            hit = self.wait_for(anchor, timeout)
            if not hit and sc:
                hit = self.scroll_find(anchor, sc)
            target = None
            if hit:
                nudges, prev, lost_retry = 0, None, False
                for _ in range(10):                     # re-check: the list may still be settling or need more scrolling
                    screen = self.game.screenshot()
                    if nudges and prev is not None and screens_still(prev, screen):
                        self.log("    reached the bottom of the list")
                        break
                    a = find(screen, anchor)
                    if a:
                        below = [b for b in find_all(screen, template) if 0 < b[1] - a[1] <= max_dy]
                        if below:
                            target = min(below, key=lambda b: b[1] - a[1])
                            break
                        if sc and nudges < 5:
                            # the name is visible but its button is cut off at the bottom edge: scroll a little further
                            nudges += 1
                            prev = screen
                            self.log(f"    '{anchor}' found, but its '{template}' is cut off, scrolling down a little ({nudges}/5)")
                            self.game.drag(sc["x"], sc["from_y"], sc["x"], sc["from_y"] - (sc["from_y"] - sc["to_y"]) // 2)
                            self.sleep(0.8)
                            continue
                    elif sc and not lost_retry:
                        lost_retry = True                # the name scrolled out of view: find it again
                        if not self.scroll_find(anchor, sc):
                            break
                        continue
                    self.sleep(0.6)
            if not target:
                if optional:
                    return
                self.save_debug(f"fail_{anchor}")
                raise StepFailed(f"no '{template}' found below '{anchor}'")
            self.game.tap(target[0], target[1])
            self.sleep(step.get("after", 0.4))
        elif kind == "expect_screen":
            # verify we are on a given screen; skipped until that marker has been captured
            marker = f"screen_{step['screen']}"
            if not catalog.exists(marker):
                if marker not in self._warned:
                    self._warned.add(marker)
                    self.log(f"    ({screen_label(step['screen'])} marker check skipped: templates\\{marker}.png not captured yet)")
                return
            if not self.wait_for(marker, timeout):
                name, score, _ = detect_screen(self.game.screenshot())
                self.save_debug(f"wrong_screen_{step['screen']}")
                raise StepFailed(f"{screen_label(step['screen'])} marker not found, the bot sees: "
                                 f"{name or 'an unrecognised screen'}")
        else:
            raise ValueError(f"Unknown step type: {kind}")

    def tick_rows(self, step, settings):
        """Tick the checkbox of every list row that shows the `anchor` picture (e.g. the words "Star Piece").

        The empty-checkbox picture only matches an UNTICKED box, so a row that is already ticked is never
        tapped twice. Scrolls to the top first, then down page by page until the list stops moving."""
        box = step["checkbox"].format(**settings)
        top = next(iter(step["anchors"].values()))            # the first picture: its rows sit at the top of the list
        anchors = [t for key, t in step["anchors"].items() if settings.get(key)]    # only what is ticked in Settings
        if not anchors:
            raise AlreadyDone("no shop items ticked in Settings")
        dy_min, dy_max = step.get("dy", [-25, 80])           # where the box sits relative to the anchor
        y1, y2 = step.get("region", [0, REF_HEIGHT])         # list area, so animations elsewhere don't count
        sc = step["scroll"]
        x, a, b = sc["x"], sc["from_y"], sc["to_y"]          # a -> b scrolls DOWN, b -> a scrolls UP
        tries = int(sc.get("tries", 12))

        for _ in range(tries):                                # back to the top of the list
            before = self.game.screenshot()[y1:y2]
            self.game.drag(x, b, x, a)
            self.sleep(0.8)
            if not list_moved(before, self.game.screenshot()[y1:y2]):
                break
        ticked = 0
        for page in range(tries):
            for _ in range(3):                                # a tap can miss: look again before scrolling on
                screen = self.game.screenshot()
                boxes = find_all(screen, box)
                todo = {}                                     # checkbox position -> picture of the row it belongs to
                for name in anchors:
                    for ax, ay, _s in find_all(screen, name):
                        near = [c for c in boxes if dy_min <= c[1] - ay <= dy_max]
                        if near:
                            pick = min(near, key=lambda c: abs(c[1] - ay))
                            todo.setdefault((pick[0], pick[1]), name)
                if not todo:
                    break
                for (bx, by), name in todo.items():
                    self.check_stop()
                    self.log(f"    ticking a '{name}' row")
                    self.game.tap(bx, by)
                    self.sleep(step.get("after", 0.6))
                    ticked += 1
            # the wanted rows are always at the top of the list, with other items below them: once something was
            # ticked and either none of them is left on screen, or there is room below the last one for another
            # row (= that row is a different item), there is nothing more to tick further down, so stop scrolling
            stop_gap = step.get("stop_gap") if anchors == [top] else None    # only the top item ticked: stop early; others sit further down
            if stop_gap and ticked:
                ys = [ay for _x, ay, _s in find_all(self.game.screenshot(), top)]
                if not ys or max(ys) + stop_gap < y2:
                    self.log(f"    no more '{top}' rows further down: not scrolling on")
                    break
            before = self.game.screenshot()[y1:y2]
            self.game.drag(x, a, x, b)
            self.sleep(0.8)
            if not list_moved(before, self.game.screenshot()[y1:y2]):
                self.log("    reached the bottom of the list")
                break
        self.log(f"    ticked {ticked} row(s)")
        self.notes.append(f"{ticked} item(s) ticked")
        if ticked == 0:
            raise AlreadyDone(step.get("detail", "nothing to tick"))

    def tap_all(self, step, settings):
        """Tap every `template` button (e.g. the green + of each skill row) in a scrolling list, top to bottom.

        Only buttons that match are tapped, so greyed-out ones (not enough points) are left alone. After every tap
        the screen is looked at again, because spending points greys out the rest. The list is scrolled to the top
        first, then down page by page until it stops moving. Positions are fractions of the screen so it follows
        the window size; change them in the step ("region", "scroll") if the list sits elsewhere."""
        tpl = step["template"].format(**settings)
        shot = self.game.screenshot()
        h, w = shot.shape[:2]
        fy1, fy2 = step.get("region", [0.38, 0.84])                # list area (fractions of the screen height)
        y1, y2 = int(fy1 * h), int(fy2 * h)
        sc = step.get("scroll", {})
        x = int(sc.get("x", 0.40) * w)                              # drag on the description text, away from the buttons
        a, b = int(sc.get("from_y", 0.78) * h), int(sc.get("to_y", 0.50) * h)   # a -> b scrolls DOWN
        tries = int(sc.get("tries", 15))

        def strip():
            return self.game.screenshot()[y1:y2]

        for _ in range(tries):                                      # back to the top of the list
            before = strip()
            self.game.drag(x, b, x, a)
            self.sleep(0.8)
            if not list_moved(before, strip()):
                break
        tapped = 0
        for page in range(tries):
            for _ in range(15):                                     # look again after each tap
                self.check_stop()
                hits = [c for c in find_all(self.game.screenshot(), tpl) if y1 <= c[1] <= y2]
                if not hits:
                    break
                bx, by, _s = min(hits, key=lambda c: c[1])
                self.log(f"    picking row {tapped + 1} (page {page + 1})")
                self.game.tap(bx, by)
                tapped += 1
                self.sleep(step.get("after", 0.6))
                stop = step.get("stop_template")
                if stop and find(self.game.screenshot(), stop):
                    self.log("    'Not enough skill points' is showing: stopping here")
                    self.log(f"    picked {tapped - 1} row(s)")
                    self.notes.append(f"{tapped - 1} skill(s) picked")
                    return
            before = strip()
            self.game.drag(x, a, x, b)
            self.sleep(0.8)
            if not list_moved(before, strip()):
                self.log("    reached the bottom of the list")
                break
        self.log(f"    picked {tapped} row(s)")
        self.notes.append(f"{tapped} skill(s) picked")

    def record_carats(self, template, crop_box=None, label="the finished run"):
        """Training Log, items list scrolled to the bottom: read how many carats (the rainbow carrot) this run
        earned. No carrot on screen = 0. Saves a crop of the count, appends to carats.csv, and notes it."""
        try:
            screen = self.game.screenshot()
            hit = find(screen, template)
        except FileNotFoundError as e:
            self.log(f"    carats not recorded: {e} (capture it with 'Capture template')")
            return
        stamp = datetime.datetime.now()
        crop_name, amount = "", 0
        if hit:
            x, y = hit[0], hit[1]
            dx1, dy1, dx2, dy2 = crop_box or (-8, 10, 60, 52)     # default: the "x10" under the carrot icon
            crop = screen[max(0, y + dy1):y + dy2, max(0, x + dx1):x + dx2]
            RECORD_DIR.mkdir(exist_ok=True)
            crop_name = f"carats_{stamp:%Y%m%d_%H%M%S}.png"
            cv2.imwrite(str(RECORD_DIR / crop_name), crop)
            amount = read_count(crop)
            if amount is None:
                self.log(f"    carats earned: couldn't read the number, see records\\{crop_name}")
        else:
            self.log("    no carrot in the items list: 0 carats earned")
        text = "?" if amount is None else str(amount)
        if amount is not None:
            self.log(f"    carats earned this run: {amount}")
        try:
            new = not CARATS_CSV.exists()
            with open(CARATS_CSV, "a", encoding="utf-8") as f:
                if new:
                    f.write("date,time,carats,image,action\n")
                f.write(f"{stamp:%Y-%m-%d},{stamp:%H:%M:%S},{text},{crop_name},{self.action}\n")
        except OSError as e:
            self.log(f"    couldn't write carats.csv: {e}")
        self.notes.append(f"{text} carats earned from {label}")

    def do_steps(self, steps, settings, retries=2, phase=None, first=0, upto=None):
        offset = first                              # numbering continues from the chosen start step
        steps = steps[first:upto]                   # upto = stop before this step index (None = run to the end)
        if self.start_at is not None:               # resuming mid-action: skip until the chosen phase
            sphase, sidx = self.start_at
            if phase != sphase:
                self.step_done += _enabled_count(steps, settings)   # phases before the start point count as done
                self._emit()
                return
            self.start_at = None
            path = tuple(sidx) if isinstance(sidx, (tuple, list)) else (sidx,)
            self.step_done += _enabled_count(steps, settings, 0, path[0])
            self._emit()
            steps = steps[path[0]:]
            offset = path[0]
            self.nested_start = path[1:]            # non-empty = start inside the if_visible block of that step
            if any(path):
                self.log(f"    starting at {phase} step {'.'.join(str(x + 1) for x in path)}")
        top = not self._path                              # top-level phase vs steps nested in if_visible
        if top and phase:
            self._title = self.titles.get(phase, phase)
        for n, step in enumerate(steps):
            shown = step_enabled(step, settings)
            if shown:
                self._path.append(n + offset + 1)
                num = ".".join(str(x) for x in self._path)
                self.log(f"{'  ' if top else '      '}[{self._title}: {num}. {step_what(step, settings)}]")
            try:
                for attempt in range(retries + 1):
                    try:
                        self.do_step(step, settings)
                        break
                    except StepSkipped:
                        self.skip_event.clear()
                        what = step.get("template", "").format(**settings) or step["type"]
                        self.log(f"    [skipped step] {what}: moving on to the next step")
                        break
                    except StepFailed as e:
                        if attempt == retries or step["type"] in ("if_visible", "popup_watch"):
                            raise      # inner steps were already retried; running the block again would skip it
                        self.log(f"    retrying ({e})")
                        self.sleep(1.5)
                if shown and top:                  # a top-level step finished (or was skipped)
                    self.step_done += 1
                    self._emit()
            finally:
                if shown:
                    self._path.pop()

    def is_done(self, info):
        if self.start_at is not None:               # still skipping ahead to the chosen start point
            return False
        screen = self.game.screenshot()
        name = info["done_marker"]
        score = best_score(screen, name)
        need = info.get("done_threshold", DONE_THRESHOLD)   # stricter than normal: a wrong "done" skips the action
        done = score >= need
        self.log(f"    done check '{name}': score {score:.2f} (needs {need}) -> "
                 f"{'DONE' if done else 'not done'}")
        if done:
            DEBUG_DIR.mkdir(exist_ok=True)
            path = DEBUG_DIR / f"{int(time.time())}_done_check_{name}.png"
            cv2.imwrite(str(path), screen)
            self.log(f"    screenshot used for this check: debug\\{path.name}")
        return done


# --------------------------------------------------------------------------
# ACTION 1: DAILY RUNS
# --------------------------------------------------------------------------
def run_daily_runs(runner, settings, info):
    runner.do_steps(info["navigate"], settings, phase="navigate")   # -> Daily Programs screen

    if runner.is_done(info):                      # already completed -> just tick it off
        runner.do_steps(info["exit"], settings, phase="exit")
        return "done", "already completed before run"

    runner.do_steps(info["enter"], settings, phase="enter")      # Daily Programs -> race list
    runner.do_steps(info["run_steps"], settings, phase="run_steps")  # pick race ... results ... close -> race list
    runner.log("    run 1 finished")
    runner.do_steps(info["back"], settings, phase="back")       # race list -> home screen (Home tab)
    return "done", f"1 run finished, Multi-Race set to {settings.get('races_at_once')}"   # no counter check


def cap_items(runner, settings):
    """Keep at most MAX_ITEMS of the ticked race items."""
    ticked = [k for k in ITEM_KEYS if settings.get(k)]
    if len(ticked) > MAX_ITEMS:
        runner.log(f"    only {MAX_ITEMS} items allowed, using: {', '.join(ticked[:MAX_ITEMS])}")
    return dict(settings, **{k: k in ticked[:MAX_ITEMS] for k in ITEM_KEYS})


def run_daily_legend_race(runner, settings, info):
    settings = cap_items(runner, settings)
    runner.do_steps(info["navigate"], settings, phase="navigate")   # -> Daily Programs screen

    if runner.is_done(info):                      # already completed -> just tick it off
        runner.do_steps(info["exit"], settings, phase="exit")
        return "done", "already completed before run"

    runner.do_steps(info["enter"], settings, phase="enter")      # Daily Programs -> legend list
    runner.do_steps(info["run_steps"], settings, phase="run_steps")  # pick legend ... rewards -> Next
    runner.log("    legend race finished")

    # after the race the game usually lands on the Daily Programs screen already: then there is no need to go home
    # and come back, so check the done counter right here. (Needs the optional `screen_daily_programs` marker;
    # until it is captured, or when the screen isn't recognised, the old route via the Home tab is used.)
    marker = "screen_daily_programs"
    on_programs = False
    if runner.start_at is None:                    # "start at" runs keep the normal flow
        if catalog.exists(marker):
            on_programs = bool(runner.wait_for(marker, 2))
        else:
            runner.log(f"    (Daily Programs marker check skipped: templates\\{marker}.png not captured yet)")
    if on_programs:
        runner.log("    already on the Daily Programs screen: not going home, checking the done counter here")
        runner.popup_watch = False
    else:
        runner.do_steps(info["back"], settings, phase="back")       # Home tab
        runner.do_steps(info["navigate"], settings, phase="navigate")   # home -> Daily Programs screen
    finished = runner.is_done(info)               # verify against the game's own counter
    runner.do_steps(info["exit"], settings, phase="exit")
    if finished:
        return "done", "race finished, game shows complete"
    return "failed", "race ran but completion not confirmed"


def run_independent_run(runner, settings, info):
    runner.notes = []
    runner.do_steps(info["run_steps"], settings, phase="run_steps")
    runner.sleep(2)
    extra = "; " + "; ".join(runner.notes) if runner.notes else ""
    return "done", f"independent training started (agenda: {settings.get('agenda')}){extra}"


def run_club_daily(runner, settings, info):
    runner.do_steps(info["run_steps"], settings, phase="run_steps")
    return "done", "club requests and donations finished"


def run_team_trials(runner, settings, info):
    settings = cap_items(runner, settings)
    steps, k = info["run_steps"], info.get("repeat_from", 0)
    races = max(1, min(5, int(settings.get("races", 1))))
    sa = runner.start_at                         # "start at" a step inside the repeated part: skip the first-time setup
    path = (sa[1] if isinstance(sa[1], (tuple, list)) else (sa[1],)) if sa else ()
    in_loop = bool(sa) and sa[0] == "run_steps" and path[0] >= k
    if not in_loop:
        runner.do_steps(steps, settings, phase="run_steps", upto=k)      # Race page -> Team Trials page
    for n in range(races):
        if races > 1:
            runner.log(f"    team trials race {n + 1} of {races}")
        # (when starting mid-loop, the first race begins at the chosen step; every other race at "tap team_race_btn")
        race_settings = dict(settings, more_races=(n < races - 1))   # True = press Race Again instead of going home
        runner.do_steps(steps, race_settings, phase="run_steps", first=0 if (in_loop and n == 0) else k)
    return "done", f"{races} team trials race(s) finished"


def run_daily_missions(runner, settings, info):
    runner.do_steps(info["run_steps"], settings, phase="run_steps")
    return "done", "daily mission rewards collected"


def run_daily_shop(runner, settings, info):
    runner.notes = []
    try:
        runner.do_steps(info["run_steps"], settings, phase="run_steps")
    except AlreadyDone:                           # nothing left to buy: still leave the shop before finishing
        runner.do_steps(info["exit"], settings, phase="exit")
        raise
    runner.do_steps(info["exit"], settings, phase="exit")
    extra = "; " + "; ".join(runner.notes) if runner.notes else ""
    return "done", f"daily sales bought{extra}"


ACTION_FUNCS = {"daily_runs": run_daily_runs,
                "daily_legend_race": run_daily_legend_race, "independent_run": run_independent_run,
                "club_daily": run_club_daily, "daily_missions": run_daily_missions,
                "team_trials": run_team_trials, "daily_shop": run_daily_shop}


# --------------------------------------------------------------------------
# START POINTS (lets you begin an action from the screen the game is already on)
# --------------------------------------------------------------------------
PHASE_TITLES = {"navigate": "Go to Daily Programs", "enter": "Open the race list",
                "run_steps": "Race", "back": "Return home"}
START_BEGINNING = "From the beginning"


def step_what(step, settings):
    """Short human description of a step; used by the 'start at' list and by the run log."""
    kind = step["type"]
    try:
        what = step.get("template", "").format(**settings)
    except (KeyError, IndexError):
        what = step.get("template", "")
    if kind == "sleep":
        what = f"wait {step.get('seconds', 1)}s"
    elif kind == "tap_xy":
        by = step.get("y_by")
        what = f"tap the {settings.get(by['setting'], '?')} opponent card" if by else f"tap ({step['x']}, {step['y']})"
    elif kind == "expect_screen":
        what = f"check {screen_label(step['screen'])} marker"
    elif kind == "scroll_bottom":
        what = "scroll down to the bottom of the list"
    elif kind == "record_carats":
        what = "record the carats earned this run"
    elif kind == "tick_rows":
        what = "tick every row of the items chosen in Settings"
    elif kind == "tap_all":
        what = step.get("label") or f"tap every '{step['template']}' in the list"
    elif kind == "tap_below":
        what = f"tap {step['template']} below {step['anchor'].format(**settings)}"
    elif kind == "if_visible":
        what = step.get("label") or f"if {step['template']} visible: fill it"
    elif kind == "finish_if_visible":
        what = f"if {step['template']} visible: already done, finish here"
    elif kind == "plan_skills":
        what = step.get("label", "plan and buy skills")
    elif kind == "popup_watch":
        what = "watch for the Daily Sale popup" if step.get("on", True) else "stop watching for popups"
    else:
        what = f"{kind} {what}"
    if step.get("only_if"):
        what += " (if ticked)"
    return what


def _nested_steps(step, nums, path):
    """Yield (numbers, step, index path) for every step nested inside an if_visible block, e.g. 2.1, 2.2 ..."""
    for j, sub in enumerate(step.get("steps", [])):
        n2, p2 = nums + (j + 1,), path + (j,)
        yield n2, sub, p2
        yield from _nested_steps(sub, n2, p2)


def start_points(name, settings=None):
    """[(label, phase, step_index)] for the 'start at' dropdown. First entry = normal full run."""
    act = store.action(name)
    if not act or not act["info"].get("run_steps"):
        return [(START_BEGINNING, None, 0)]
    titles = dict(PHASE_TITLES, **act["info"].get("phase_titles", {}))
    settings = settings or act["settings"]
    points = [(START_BEGINNING, None, 0)]
    for phase in ("navigate", "enter", "run_steps", "back"):
        for i, step in enumerate(act["info"].get(phase, [])):
            if phase == "navigate" and i == 0:
                continue                                # same as the beginning
            what = step_what(step, settings)
            points.append((f"{titles[phase]}: {i + 1}. {what}", phase, i))
            for nums, sub, path in _nested_steps(step, (i + 1,), (i,)):     # steps inside an if_visible block
                points.append((f"{titles[phase]}: {'.'.join(map(str, nums))}. {step_what(sub, settings)}", phase, path))
    return points


# --------------------------------------------------------------------------
# MAIN ENTRY USED BY THE GUI
# --------------------------------------------------------------------------
def run_all(title, log, stop_event, only=None, progress=None, start_at=None, skip_event=None, step=None,
            pause_event=None):
    init_db()
    game = GameWindow(title)
    runner = Runner(game, log, stop_event, skip_event, pause_event)

    todo = []
    for a in store.actions():
        if only:
            if a["name"] == only:
                todo.append(a)
        elif not a["enabled"]:
            log(f"[skip] {a['name']}: disabled")
        elif store.status(a["name"]) == "done":
            log(f"[skip] {a['name']}: already checked off today")
        else:
            todo.append(a)

    total = len(todo)
    if total > 1:
        log("Run order: " + "  >  ".join(a["name"] for a in todo))
    if progress:
        progress(0, total)
    for i, a in enumerate(todo):
        name = a["name"]
        log(f"[run ] {name}")
        runner.skip_event.clear()          # a skip press only applies to the step running now
        runner.popup_watch = False
        runner.action = name
        runner.step_done, runner.step_total = 0, action_total(name, a["settings"])
        runner.on_step = (lambda d, t, n=name: step(n, d, t, "running")) if step else None
        if step:
            step(name, 0, runner.step_total, "running")
        try:
            runner.start_at = start_at if (only and start_at and start_at[0]) else None
            if runner.start_at:
                idx = runner.start_at[1]
                idx = tuple(idx) if isinstance(idx, (tuple, list)) else (idx,)
                log(f"    resuming: skipping ahead to {runner.start_at[0]} step {'.'.join(str(x + 1) for x in idx)}")
            runner.nested_start = ()
            runner.titles = {**PHASE_TITLES, "exit": "Exit", **a["info"].get("phase_titles", {})}
            runner._path = []
            status, detail = ACTION_FUNCS[name](runner, a["settings"], a["info"])
        except Stopped:
            log(f"[stop] {name}: stopped by you")
            return
        except AlreadyDone as e:   # the game itself shows it's complete (e.g. "Done for today!" on the Race page)
            status, detail = "done", str(e)
        except StepSkipped:        # skip pressed outside a normal step (e.g. popup clearing)
            runner.skip_event.clear()
            status, detail = "skipped", "skipped by you"
        except FocusFailed as e:   # game not in front: no input was sent, so stop the whole run
            store.set_status(name, "failed", str(e))
            if step:
                step(name, runner.step_done, runner.step_total, "failed")
            log(f"[stop] {name}: {e}")
            return
        except Exception as e:  # noqa
            status, detail = "failed", f"{type(e).__name__}: {e}"
        store.set_status(name, status, detail)
        if step:
            step(name, runner.step_total if status == "done" else runner.step_done, runner.step_total, status)
        log(f"[{status}] {name}: {detail}")
        if progress:
            progress(i + 1, total)
    log("Finished.")
