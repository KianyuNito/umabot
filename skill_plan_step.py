"""
Independent career skills, run by umabot.

The bot runs the scanner's own code (skill_scanner.py) on the Learn Skills screen: import, scan (with
the double-circle reveal), aptitudes and the plan (skill_planner.py). Nothing is planned from an
old scan; the costs are read again on every run.

Entry points used by engine.py:
  read_aptitudes(shot_bgr)                  Complete Career screen, before Skills
  plan_skills(game, log, check_stop, sleep, apt, db_path, notes, must_buy=())   Learn Skills screen
Any problem raises PlanFailed (not retried) with the reason. Nothing is confirmed.
"""
import os
import time

import cv2
from PIL import Image

import skill_scanner as sc
import skill_planner as sp
from skill_store import SkillStore
from vision import find_all


class PlanFailed(Exception):
    """Stops the action at once. Not a StepFailed: do_steps retries those, and a retry would
    scan and buy again on points that are already spent."""


PLUS_TEMPLATE = "ind_skill_plus_btn"
PLUS_TOLERANCE = 0.03      # a + button must sit this close (fraction of screen height) to its row
MAX_PAGES = 150


# ---- picture helpers -------------------------------------------------------------------------
def _pil(shot_bgr):
    return Image.fromarray(cv2.cvtColor(shot_bgr, cv2.COLOR_BGR2RGB))


def _pane_geometry(shot_bgr):
    """(x0, width, height) of the pane in window pixels."""
    h, w = shot_bgr.shape[:2]
    return int(sc.PANE[0] * w), int((sc.PANE[2] - sc.PANE[0]) * w), h


def _pane(pil):
    w, h = pil.size
    return pil.crop((int(sc.PANE[0] * w), 0, int(sc.PANE[2] * w), h))


# ---- aptitudes -------------------------------------------------------------------------------
def read_aptitudes(shot_bgr):
    """{key: letter} for all eight aptitudes, or PlanFailed listing what could not be read."""
    letters = sc.read_apt(_pane(_pil(shot_bgr)))
    unread = [k for k, v in letters.items() if v is None]
    if unread:
        raise PlanFailed("could not read aptitudes: " + ", ".join(unread))
    return letters


# ---- bridge: the scanner's screen functions use the bot's game window --------------------------
def _scan_io(game, log, check_stop, db_path):
    """The scanner's host interface, backed by the bot's game window."""
    def grab(h):
        return _pane(_pil(game.screenshot()))

    def drag(h, down, scale=1.0):
        shot = game.screenshot()
        x0, pw, hh = _pane_geometry(shot)
        px = x0 + int(sc.DRAG_X * pw)
        a = int(sc.DRAG_START_Y * hh)
        b = a - int(sc.DRAG_DIST * scale * hh)
        if down:
            game.drag(px, a, px, b, duration=sc.DRAG_SECONDS)
        else:
            game.drag(px, b, px, a, duration=sc.DRAG_SECONDS)

    def click(h, fx, fy):
        shot = game.screenshot()
        x0, pw, hh = _pane_geometry(shot)
        game.tap(x0 + int(fx * pw), int(fy * hh))

    def ask(prompt=""):
        if "Press Enter" in prompt:          # the reveal warning: nothing to type, just go on
            log("    reveal mode: clicking + then - on single-circle skills to read double-circle costs")
            return ""
        raise PlanFailed("the scanner needed input and the bot cannot ask: " + prompt.strip())

    return sc.ScanIO(
        lambda: game,
        grab,
        drag,
        click,
        check_stop,                                  # the bot's stop key (P) stops the scan too
        lambda *a, **k: log(" ".join(str(x) for x in a)),
        ask,
        sc.read_points,
        db_path,
    )


def _import_if_needed(db_path, json_path, log):
    """The skill list (names, scores, chains) comes from skills_slim.json. Imported once."""
    if SkillStore(db_path).count() == 0:
        if not os.path.exists(json_path):
            raise PlanFailed(f"skill list not found: {json_path}")
        log("    importing the skill list (skills_slim.json)")
        sc.cmd_import(json_path, db_path)


def _points_once(game):
    return sc.read_points_detail(_pane(_pil(game.screenshot())))


def _points(game, sleep, tries=4, want=None):
    """Read the points until two readings in a row agree (or, with `want`, until the reading equals it).
    Returns (value or None, raw text, picture)."""
    last = (None, [], None)
    previous = None
    if want is not None:
        tries = max(tries, 6)
    for _ in range(tries):
        value, texts, picture = _points_once(game)
        last = (value, texts, picture)
        if want is not None and value == want:
            return last
        if want is None and value is not None and value == previous:
            return last
        previous = value
        sleep(0.4)
    return last


def _save_points_picture(picture, folder):
    """Keep a picture of the points box for checking what the bot read."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"points_{time.strftime('%Y%m%d_%H%M%S')}.png")
    picture.save(path)
    return path


MAX_TAPS_PER_PAGE = 40


def _next_target(game, known, queue, seen=None, noplus=None):
    """The first planned skill whose + button is on screen right now: (name, x, y), or None.
    seen / noplus (optional sets) collect the skill names read on screen, and the planned ones whose
    row was read but had no + button next to it, so a failure can say which of the two happened."""
    shot = game.screenshot()
    rows, _, _, _ = sc.read_page(_pane(_pil(shot)), known)
    _, _, hh = _pane_geometry(shot)
    plus = find_all(shot, PLUS_TEMPLATE)
    for r in rows:
        if seen is not None:
            seen.add(r["name"])
        if r["name"] not in queue:
            continue
        row_y = r["cost_y"] * hh
        near = [c for c in plus if abs(c[1] - row_y) <= PLUS_TOLERANCE * hh]
        if near:
            bx, by, _s = min(near, key=lambda c: abs(c[1] - row_y))
            return r["name"], bx, by
        if noplus is not None:
            noplus.add(r["name"])
    return None


def drop_auto_selected(queue, name, pos, chain):
    """Tapping a higher part of a chain also selects the lower parts that sit on other rows (a gold skill
    selects its white prerequisite). Remove those from the queue. Returns the names removed."""
    dropped = []
    for other in list(queue):
        if other == name:
            continue
        keep = [x for x in queue[other] if not (x[2] == chain and x[1] < pos)]
        if len(keep) != len(queue[other]):
            dropped.append(other)
        if keep:
            queue[other] = keep
        else:
            del queue[other]
    return dropped


# ---- the step --------------------------------------------------------------------------------
def plan_skills(game, log, check_stop, sleep, apt, db_path, notes, must_buy=()):
    """Scan the Learn Skills list, plan the purchase from that scan, buy exactly the planned skills."""
    if apt is None:
        raise PlanFailed("aptitudes not read: start from the step that reads them, or run the whole action")
    io = _scan_io(game, log, check_stop, db_path)
    json_path = os.path.join(os.path.dirname(db_path), "skills_slim.json")
    _import_if_needed(db_path, json_path, log)

    # 1. scan: the scanner's own function, run on the bot's window
    log("    scanning the Learn Skills list")
    result = sc.cmd_scan(True, io)
    if result is None:
        raise PlanFailed("skill database is empty: the skill list did not import")
    bottom, points, scale = result
    if not bottom:
        raise PlanFailed("the scan did not reach the bottom of the list; nothing was bought")
    if points is None:
        raise PlanFailed("could not read the skill points")
    log(f"    skill points: {points}")

    # 2. plan from this scan
    try:
        plan = sp.make_plan(db_path, apt, points, must_buy=must_buy)
    except ValueError as e:
        raise PlanFailed(str(e))
    for why in plan["skipped"]:
        log(f"    must buy skipped, {why}")
    picks = plan["picks"]
    if not picks:
        notes.append("no skills to buy with the points")
        log("    nothing affordable to plan")
        return
    log(f"    plan: {len(picks)} purchase(s), gain {plan['gain']}, cost {plan['cost']}, left {plan['left']}")

    # 3. buy. queue: name -> [(cost, position in its chain, chain)], lower parts first
    queue = {}
    for p in picks:
        queue.setdefault(p["name"], []).append((p["cost"], p.get("pos", 0), p.get("chain", 0)))
    known = sc.known_names(SkillStore(db_path).names())
    bought = 0
    seen, noplus = set(), set()

    # Look at the screen again before every tap: buying a skill can move the rows below it.
    # Don't trust the scan's drag length: measure one page here, so a short last page in the scan
    # cannot make this phase skip rows. The scan left the list at the bottom, so go up first.
    sc.go_to_top(None, io)
    _, moved, shift, err = sc.scroll(None, True, scale, io)
    if not moved:                                   # lagged frame (or a list shorter than one page): retry once
        _, moved, shift, err = sc.scroll(None, True, scale, io)
    if moved and err <= sc.SHIFT_MAX_ERR and shift > 0.03:
        scale = max(0.4, min(1.0, scale * sc.SHIFT_TARGET / shift))
        log(f"    buy pass drag {scale:.2f} (test page moved {shift * 100:.0f}%)")
    elif not moved:
        log(f"    buy pass drag {scale:.2f} (list did not move: shorter than one page, keeping the scan's value)")
    else:
        log(f"    buy pass drag {scale:.2f} (movement unreadable, keeping the scan's value)")
    for attempt in range(3):
        sc.go_to_top(None, io)
        for _ in range(MAX_PAGES * MAX_TAPS_PER_PAGE):
            check_stop()
            if not queue:
                break
            target = _next_target(game, known, queue, seen, noplus)
            if target is None:
                _, moved, _, _ = sc.scroll(None, True, scale, io)   # the scanner's own: one page down
                if not moved:
                    break
                continue
            name, bx, by = target
            cost, pos, chain = queue[name].pop(0)
            if not queue[name]:
                del queue[name]
            game.tap(bx, by)
            sleep(0.8)
            bought += 1
            log(f"    bought {name} (-{cost})")
            for other in drop_auto_selected(queue, name, pos, chain):
                log(f"    {other} was selected with {name} (its prerequisite)")
                bought += 1
        if not queue:
            break
        log(f"    pass {attempt + 1}: {sum(len(v) for v in queue.values())} purchase(s) still to make "
            f"({', '.join(sorted(queue))}); back to the top for another pass")

    if queue and bought == 0:
        log("    no skills were bought; nothing is selected in the game")
    if queue:
        why = []
        for n in sorted(queue):
            kind = "row read but no + button next to it" if n in noplus else (
                "never read on screen" if n not in seen else "row read")
            why.append(f"{n} ({kind})")
        raise PlanFailed("planned skills not found on the screen: " + ", ".join(why)
                         + " (stopped before Confirm; press Reset in the game)")
    expected_left = points - plan["cost"]
    final, final_text, final_picture = _points(game, sleep, want=expected_left)
    if final is None:
        saved = _save_points_picture(final_picture, os.path.join(os.path.dirname(db_path), "debug")) if final_picture else "no picture"
        log(f"    WARNING: could not read the skill points at the end (expected {expected_left}); "
            f"picture saved to {saved}. Nothing contradicts the plan, so continuing.")
    elif final != expected_left:
        saved = _save_points_picture(final_picture, os.path.join(os.path.dirname(db_path), "debug")) if final_picture else "no picture"
        raise PlanFailed(f"after buying, the skill points read {final} (the screen read as {final_text}), "
                         f"expected {expected_left}; picture saved to {saved}. Stopped before Confirm. "
                         "Press Reset in the game if the skills selected are wrong.")
    notes.append(f"{bought} skill(s) bought, gain {plan['gain']}, points left {expected_left}")
    log(f"    done: {bought} purchase(s) made")
