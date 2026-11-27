"""
Skill scanner for the Umamusume skill-learn screen (Windows).

Commands:
  python skill_scanner.py import skills_slim.json   build the skill database (base scores, chains, categories)
  python skill_scanner.py debug                     read the screen once, save pictures, show what it sees
  python skill_scanner.py scan                      scroll the list, read every cost + your skill points
  python skill_scanner.py scan --no-reveal          same, but never click (double-circle costs stay unknown)
  python skill_scanner.py calc --apt mile=A,medium=A,long=B,sprint=G,front=G,pace=B,late=A,end=G [--points N]
                                                    pick the skills with the highest total score you can afford

Scores: the json holds each skill's base score (grade_value). At calc time the score is
  round(base x multiplier), where the multiplier comes from your character's aptitude:
  S/A 1.1   B/C 0.9   D/E/F 0.8   G 0.7
  - a skill tied to a running style OR a distance uses that one aptitude
  - a skill tied to both (dual) multiplies the two multipliers (e.g. A + A = 1.21)
  - a skill with several alternative conditions uses the best of them
  - generic skills, dirt skills and inherited uniques (flat 180) never scale
  Rounding is "nearest" by default; pass --round floor to round down.
  --apt is remembered, so later runs of calc can leave it out.

Chains (a higher tier can only be bought after the tier below it; costs add up):
  3 tiers:  ○ -> ◎ -> gold      options: ○ | ○+◎ | ○+◎+gold
  2 tiers:  white -> gold (or ○ -> gold)      options: white | white+gold
  A tier's gain = its full score minus the full score of the tier below it.
  If a lower tier is not on the screen (already bought), only the remaining tiers are options.

Install once:  uv pip install winocr pillow numpy pywin32 pyautogui
Needs circle_single.png and circle_double.png next to this script.
Emergency stop while scanning: hold Esc (or throw the mouse into a screen corner).
"""
import argparse
import ctypes
import difflib
import json
import re
import sys
import time
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image
from skill_planner import APT_MULT, DISTANCES, STYLES, TIER_SYMBOL, best_selection, build_groups
from skill_store import SkillStore

_out = print      # the bot replaces these two to write into its own log
_ask = input

HERE = Path(__file__).resolve().parent

# ======================= SETTINGS (edit if needed) =======================
WINDOW_TITLE = "Umamusume"          # part of the game window's title
DB_PATH = HERE / "skills.db"
OCR_LANG = "en"
OCR_SCALE = 2                       # crops are enlarged this much before reading

# The learn screen is the left part of the game window (x 148..958 of 1920 in your screenshots).
# Everything below is a fraction of that pane, not of the whole window.
PANE = (148 / 1920, 0.0, 958 / 1920, 1.0)

LIST_TOP, LIST_BOTTOM = 0.37, 0.80  # list area (also used to detect scrolling; stops above Confirm)
VISIBLE_TOP, VISIBLE_BOTTOM = 0.375, 0.803  # what we read from a row must sit between these
NAME_X = (0.26, 0.64)               # column holding skill names (+ descriptions); stops before the - button
COST_X = (0.70, 0.775)              # column holding the cost number
POINTS_BOX = (0.64, 0.31, 0.84, 0.35)      # x1, y1, x2, y2 of the Skill Points number
NAME_TO_COST = 0.046                # cost number sits this far below the name
NAME_TO_ROW_TOP = 0.018             # name centre -> top of its row
NAME_TO_ROW_BOTTOM = 0.076          # name centre -> bottom of the + / - buttons (all we read or click)
COST_TOLERANCE = 0.02
ICON_X = (0.185, 0.245)             # skill icon column (used to tell same-name skills apart)
ICON_DY, ICON_HALF = 0.046, 0.02    # icon centre is this far below the name; half its height
CIRCLE_Y_TOLERANCE = 0.015          # circle centre must be this close to its name's height
PLUS_X, MINUS_X = 0.801, 0.667      # the + and - buttons (height = the cost number's height)

CIRCLE_MATCH_MIN = 0.6              # how well a circle picture must match (1.0 = identical)
DOUBLE_DROP_MIN = 40                # inner ring darkness: above this = double circle
CLICK_SETTLE = 0.6

DRAG_X = 0.40                       # on the description text, never on a button
DRAG_START_Y = 0.78
DRAG_DIST = 0.28                    # 78% -> 50%
DRAG_SECONDS = 0.5
SETTLE_SECONDS = 0.8
MOVE_THRESHOLD = 0.5                # average pixel difference below this = list did not move
MAX_UP = 40
MAX_DOWN = 150
# The game keeps scrolling a bit after you let go, so the drag length is measured, not guessed:
SHIFT_TARGET = 0.20                 # we want each page to move the list this much (fraction of screen height)
SHIFT_MAX = 0.27                    # moving more than this in one go risks skipping a row
SHIFT_MAX_ERR = 10.0                # picture difference above this = movement could not be measured
CAL_START_SCALE = 0.4               # first test drag (fraction of DRAG_DIST)
MIN_SCALE, MAX_SCALE = 0.15, 1.25
MAX_GAP_RETRIES = 3
NAME_MATCH_CUTOFF = 0.85
# =========================================================================

TIER_MARKS = [("○", 1), ("◯", 1), ("(1)", 1), ("◎", 2), ("(2)", 2)]


# ---------------------------- database ----------------------------------

def parse_label(label):
    """'Medium Corners ◎' -> ('Medium Corners', 2)."""
    s = label.strip()
    for mark, tier in TIER_MARKS:
        if s.endswith(mark):
            return s[: -len(mark)].strip(), tier
    return s, 0


def condition_alts(cond):
    """'running_style==3&phase==2@running_style==3&...' -> [(style|None, distance|None), ...] one per
    alternative. Returns [] (never scales) when any alternative is a dirt condition."""
    out = []
    for alt in (cond or "").split("@"):
        style = dist = None
        for tok in alt.split("&"):
            m = re.fullmatch(r"(running_style|distance_type|ground_type)==(\d+)", tok.strip())
            if not m:
                continue
            kind, val = m.group(1), int(m.group(2))
            if kind == "ground_type":
                if val == 2:
                    return []  # dirt: no scaling
            elif kind == "running_style":
                style = val
            else:
                dist = val
        out.append((style, dist))
    if all(s is None and d is None for s, d in out):
        return []
    return out


def cmd_import(path, db_path=DB_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    skills = data["skills"] if isinstance(data, dict) else data
    rows, scaling = [], 0
    for s in skills:
        name, tier = parse_label(s["name"])
        inherited = str(s["id"]).startswith("9")  # inherited uniques: flat score, never scale
        alts = [] if inherited else condition_alts(s.get("condition_1", ""))
        scaling += bool(alts)
        rows.append((name, tier, int(s["grade_value"]), json.dumps(alts), int(s["group_id"]), int(s["group_rate"])))
    carried = SkillStore(db_path).replace_skills(rows)
    if carried:
        print(f"Carried over {carried} costs from the old database.")
    print(f"Imported {len(rows)} skills ({scaling} scale with aptitude, {len(rows) - scaling} never scale).")


# ------------------------- name matching / pairing ----------------------
def normalize(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def match_name(text, known):
    """known = {normalized: real name}. Returns (real name or None, similarity)."""
    n = normalize(text)
    if not n:
        return None, 0.0
    candidates = [n, n[:-1]]  # safety net if a circle is ever read as an extra letter
    best_name, best = None, 0.0
    for norm, real in known.items():
        for c in candidates:
            r = difflib.SequenceMatcher(None, c, norm).ratio()
            if r > best:
                best, best_name = r, real
    return best_name, best


def icon_color_at(img, y):
    """Dominant colour name of the skill icon in the row whose name is at height y (fraction)."""
    w, h = img.size
    box = (int(ICON_X[0] * w), int((y + ICON_DY - ICON_HALF) * h),
           int(ICON_X[1] * w), int((y + ICON_DY + ICON_HALF) * h))
    arr = np.asarray(img.crop(box).convert("HSV")).reshape(-1, 3).astype(float)
    sel = arr[(arr[:, 1] > 115) & (arr[:, 2] > 140)]
    if len(sel) < 30:
        return None
    hue = float(np.median(sel[:, 0])) * 360 / 255
    if hue < 15 or hue >= 340:
        return "red"
    if hue < 45:
        return "orange"
    if hue < 70:
        return "yellow"
    if hue < 170:
        return "green"
    if hue < 260:
        return "blue"
    return "purple"


def pair_rows(name_lines, cost_lines, circles, known, icon_color=None):
    """
    name_lines / cost_lines: [(text, y_centre_fraction)]
    circles: [(kind 1|2, y_centre_fraction, score)]
    Returns (rows, seen, notes). rows = fully visible rows with a cost:
      {"name", "tier" (0 none, 1 single, 2 double), "cost", "y", "cost_y"}
    seen = every known name recognised on screen, including cut-off rows.
    icon_color(y) -> colour name; used only for skills that share a name (e.g. "Indomitable [blue]").
    """
    notes = []
    costs = []
    for text, y in cost_lines:
        cleaned = re.sub(r"[ ,]", "", text)
        if re.fullmatch(r"\d{1,4}", cleaned):  # a bare number only; ignores "40% OFF!" badges
            costs.append((int(cleaned), y))
    rows, seen = [], set()
    matched = []
    for text, y in name_lines:
        name, sim = match_name(text, known)
        if name and sim >= NAME_MATCH_CUTOFF:
            matched.append((name, sim, y))
    # A description line that mentions the skill ("at Kyoto Racecourse.") also looks like its name,
    # but never matches as well as the real name line, so keep only the best-matching line(s).
    top_sim = {}
    for name, sim, _ in matched:
        top_sim[name] = max(top_sim.get(name, 0.0), sim)
    matched = [m for m in matched if m[1] >= top_sim[m[0]] - 0.02]
    for name, sim, y in matched:
        seen.add(name)
        if y - NAME_TO_ROW_TOP < VISIBLE_TOP or y + NAME_TO_ROW_BOTTOM > VISIBLE_BOTTOM:
            notes.append(f"skipped (cut off at edge): {name}")
            continue
        tier, best_c = 0, None
        for kind, cy, score in circles:
            if abs(cy - y) <= CIRCLE_Y_TOLERANCE and (best_c is None or score > best_c):
                best_c, tier = score, kind
        target = y + NAME_TO_COST
        best = None
        for c, cy in costs:
            d = abs(cy - target)
            if d <= COST_TOLERANCE and (best is None or d < best[0]):
                best = (d, c, cy)
        full = name
        variants = getattr(known, "variants", {}).get(name)
        if variants:
            colour = icon_color(y) if icon_color else None
            full = variants.get(colour)
            if full is None:
                notes.append(f"same-name skill '{name}': icon colour {colour!r} matches none of {sorted(variants)}")
                continue
        if best:
            rows.append({"name": full, "tier": tier, "cost": best[1], "y": y, "cost_y": best[2]})
        else:
            notes.append(f"no cost found next to: {full}{TIER_SYMBOL[tier]}")
    return rows, seen, notes


# ------------------------------ circles ---------------------------------
def load_templates():
    from PIL import Image

    out = []
    for fname in ("circle_single.png", "circle_double.png"):
        p = HERE / fname
        if not p.exists():
            print(f"Missing {fname} next to the script.")
            sys.exit(1)
        out.append(np.asarray(Image.open(p).convert("L"), dtype=np.float64))
    return out


def zncc(gray, tmpl):
    """Normalised cross-correlation of tmpl over gray (1.0 = identical shape, any brightness)."""
    g = gray.astype(np.float64)
    t = tmpl.astype(np.float64)
    t = t - t.mean()
    th, tw = t.shape
    H, W = g.shape
    s = (H + th, W + tw)
    full = np.fft.irfft2(np.fft.rfft2(g, s=s) * np.fft.rfft2(t[::-1, ::-1], s=s), s=s)
    num = full[th - 1:H, tw - 1:W]

    def integ(a):
        return np.pad(a.cumsum(0).cumsum(1), ((1, 0), (1, 0)))

    def box(i):
        return i[th:, tw:] - i[:-th, tw:] - i[th:, :-tw] + i[:-th, :-tw]

    n = th * tw
    s1 = box(integ(g))
    s2 = box(integ(g * g))
    var = np.maximum(s2 - s1 ** 2 / n, 0)
    den = np.sqrt(var) * np.sqrt((t * t).sum())
    return np.where(var > n / 4.0, num / np.maximum(den, 1e-9), 0.0)


def ring_drop(gray, cx, cy):
    """How much darker the inner ring (radius 3-5 px) is than the background. Double circle: high."""
    pad = 14
    g = np.pad(gray, pad, mode="edge")
    ys, xs = np.mgrid[int(cy) - 12 + pad:int(cy) + 13 + pad, int(cx) - 12 + pad:int(cx) + 13 + pad]
    r = np.hypot(xs - pad - cx, ys - pad - cy)
    patch = g[ys, xs].astype(np.float64)
    ring = patch[(r >= 3.0) & (r <= 5.0)]
    return float(np.percentile(patch, 90) - ring.mean())


def find_circles(gray):
    """Returns [(kind 1|2, cx, cy, match score, ring drop)] in the pixels of `gray`."""
    single, double = load_templates()
    th, tw = single.shape
    both = np.maximum(zncc(gray, single), zncc(gray, double))
    found = []
    for _ in range(12):
        iy, ix = np.unravel_index(np.argmax(both), both.shape)
        s = both[iy, ix]
        if s < CIRCLE_MATCH_MIN:
            break
        cx, cy = ix + tw / 2, iy + th / 2
        drop = ring_drop(gray, cx, cy)
        found.append((2 if drop >= DOUBLE_DROP_MIN else 1, cx, cy, float(s), drop))
        both[max(0, iy - th):iy + th, max(0, ix - tw):ix + tw] = -1
    return found


def paint_circles(img, circles):
    """Cover each circle with the surrounding background colour so OCR never sees it."""
    arr = np.array(img)
    h, w = arr.shape[:2]
    for _, cx, cy, _, _ in circles:
        x0, x1 = max(0, int(cx - 11)), min(w, int(cx + 12))
        y0, y1 = max(0, int(cy - 11)), min(h, int(cy + 12))
        fx0, fx1 = max(0, x0 - 3), min(w, x1 + 3)
        fy0, fy1 = max(0, y0 - 3), min(h, y1 + 3)
        frame = arr[fy0:fy1, fx0:fx1].copy()
        mask = np.ones(frame.shape[:2], dtype=bool)
        mask[y0 - fy0:y1 - fy0, x0 - fx0:x1 - fx0] = False
        fill = np.median(frame[mask], axis=0)
        arr[y0:y1, x0:x1] = fill
    from PIL import Image

    return Image.fromarray(arr)


# ----------------------------- Windows side -----------------------------
def dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def find_window():
    import win32gui

    found = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            t = win32gui.GetWindowText(h)
            if t:
                found.append((h, t))

    win32gui.EnumWindows(cb, None)
    for h, t in found:
        if WINDOW_TITLE.lower() in t.lower():
            try:
                win32gui.ShowWindow(h, 9)  # restore if minimised
                win32gui.SetForegroundWindow(h)
            except Exception:
                pass
            time.sleep(0.4)
            return h
    print(f'No window with "{WINDOW_TITLE}" in its title. Open windows:')
    for _, t in found:
        print("  ", t)
    print("Set WINDOW_TITLE at the top of the script to match.")
    sys.exit(1)


def pane_rect(h):
    """Screen position and size of the learn-screen pane: x, y, w, h."""
    import win32gui

    _, _, r, b = win32gui.GetClientRect(h)
    x, y = win32gui.ClientToScreen(h, (0, 0))
    return (x + int(PANE[0] * r), y + int(PANE[1] * b),
            int((PANE[2] - PANE[0]) * r), int((PANE[3] - PANE[1]) * b))


def grab(h):
    from PIL import ImageGrab

    x, y, w, hh = pane_rect(h)
    return ImageGrab.grab(bbox=(x, y, x + w, y + hh), all_screens=True).convert("RGB")


def check_abort():
    if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:  # Esc
        raise KeyboardInterrupt("Esc pressed")


def crop(img, x1, y1, x2, y2):
    w, h = img.size
    return img.crop((int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)))


def ocr_lines(img):
    """Returns [(text, y_centre_in_image_pixels)] for the given image."""
    import winocr
    from PIL import ImageOps

    big = img.convert("L")
    big = ImageOps.autocontrast(big)
    big = big.resize((big.width * OCR_SCALE, big.height * OCR_SCALE)).convert("RGB")
    result = winocr.recognize_pil_sync(big, OCR_LANG)
    out = []
    for line in result["lines"]:
        words = line["words"]
        if not words:
            continue
        top = min(w["bounding_rect"]["y"] for w in words)
        bottom = max(w["bounding_rect"]["y"] + w["bounding_rect"]["height"] for w in words)
        out.append((line["text"], (top + bottom) / 2 / OCR_SCALE))
    return out


def read_page(img, known):
    """Returns (rows, seen, notes, circles_in_name_crop_pixels)."""
    w, h = img.size
    top = int(LIST_TOP * h)
    name_img = crop(img, NAME_X[0], LIST_TOP, NAME_X[1], LIST_BOTTOM)
    cost_img = crop(img, COST_X[0], LIST_TOP, COST_X[1], LIST_BOTTOM)
    circles_px = find_circles(np.asarray(name_img.convert("L"), dtype=np.float64))
    painted = paint_circles(name_img, circles_px)
    name_lines = [(t, (y + top) / h) for t, y in ocr_lines(painted)]
    cost_lines = [(t, (y + top) / h) for t, y in ocr_lines(cost_img)]
    circles = [(kind, (cy + top) / h, s) for kind, _, cy, s, _ in circles_px]
    rows, seen, notes = pair_rows(name_lines, cost_lines, circles, known,
                                  icon_color=lambda y: icon_color_at(img, y))
    return rows, seen, notes, circles_px


def _digits_from(lines):
    texts = [t for t, _ in lines]
    digits = "".join(re.sub(r"\D", "", t) for t in texts)
    return (int(digits) if digits else None), texts


def _twice(img, gap=60):
    """The same picture twice, side by side. Windows OCR often ignores a lone digit (a 1-digit points
    number), but reads the same digit when it appears twice."""
    out = Image.new("RGB", (img.width * 2 + gap, img.height), (255, 255, 255))
    out.paste(img, (0, 0))
    out.paste(img, (img.width + gap, 0))
    return out


def _with_anchor(mask, text="Points"):
    """The digits drawn after a word. OCR reads 'Points 5' far more reliably than a lone '5'."""
    from PIL import ImageDraw, ImageFont
    h = mask.height
    size = max(12, int(h * 0.6))
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:
        return None
    w = int(ImageDraw.Draw(mask).textlength(text, font=font))
    out = Image.new("RGB", (w + 40 + mask.width, h), (255, 255, 255))
    ImageDraw.Draw(out).text((10, (h - size) // 2), text, fill=(0, 0, 0), font=font)
    out.paste(mask, (w + 40, 0))
    return out


def read_points_detail(img):
    """One reading of the skill points box in an already-captured pane picture:
    (value or None, raw OCR text, picture of the box).
    Tries the isolated orange digits first, then the digits written twice (for a 1-digit number),
    then the plain padded crop."""
    box = crop(img, *POINTS_BOX)
    mask = _digits_image(box)

    value, texts = _digits_from(ocr_lines(mask))
    if value is not None:
        return value, texts, mask

    anchored = _with_anchor(mask)
    if anchored is not None:
        value, texts4 = _digits_from(ocr_lines(anchored))
        if value is not None:
            return value, texts4, mask

    lines = ocr_lines(_twice(mask))
    texts2 = [t for t, _ in lines]
    tokens = " ".join(texts2).split()
    if len(tokens) == 2 and tokens[0] == tokens[1] and tokens[0].isdigit():
        return int(tokens[0]), texts2, mask
    joined = "".join(re.sub(r"\D", "", t) for t in texts2)
    half = len(joined) // 2
    if joined and len(joined) % 2 == 0 and joined[:half] == joined[half:]:
        return int(joined[:half]), texts2, mask

    value, texts3 = _digits_from(ocr_lines(_pad(box)))
    return value, texts + texts2 + texts3, mask


def _digits_image(img, margin=16):
    """The points number is orange on a pale bar: in plain greyscale it has weak contrast, and a dark
    corner of the crop weakens it more. So pick out the coloured (orange) pixels and draw them as black
    digits on white. Falls back to the padded original crop if too few coloured pixels are found."""
    a = np.asarray(img.convert("RGB")).astype(int)
    mask = (a.max(2) - a.min(2)) > 70
    if int(mask.sum()) < 80:
        return _pad(img, margin)
    out = np.where(mask, 0, 255).astype(np.uint8)
    out = np.pad(out, margin, mode="constant", constant_values=255)
    return Image.fromarray(out).convert("RGB")


def _pad(img, margin=16):
    """Add a margin of the crop's own edge colour around it. OCR often drops a digit that touches the
    edge of a tight crop (3754 read as 375)."""
    arr = np.pad(np.asarray(img.convert("RGB")), ((margin, margin), (margin, margin), (0, 0)), mode="edge")
    return Image.fromarray(arr)


def read_points(img):
    return read_points_detail(img)[0]


class ScanIO(NamedTuple):
    """Everything cmd_scan needs from the machine it runs on."""
    window: object
    grab: object
    drag: object
    click: object
    stop: object
    log: object
    ask: object
    points: object
    db_path: object


def desktop_io():
    return ScanIO(find_window, grab, drag, click, check_abort, print, input, read_points, DB_PATH)


def list_gray(img):
    return np.asarray(crop(img, 0, LIST_TOP, 1, LIST_BOTTOM).convert("L"), dtype=np.int16)


def list_changed(a, b):
    ga, gb = list_gray(a), list_gray(b)
    if ga.shape != gb.shape:
        return True
    return float(np.abs(ga - gb).mean()) >= MOVE_THRESHOLD


def drag(h, down, scale=1.0):
    """down=True scrolls the list down (finger swipes up)."""
    import pyautogui

    pyautogui.PAUSE = 0
    x, y, w, hh = pane_rect(h)
    px = x + int(DRAG_X * w)
    a = y + int(DRAG_START_Y * hh)
    b = a - int(DRAG_DIST * scale * hh)
    start, end = (a, b) if down else (b, a)
    pyautogui.moveTo(px, start)
    pyautogui.mouseDown()
    try:
        pyautogui.moveTo(px, end, duration=DRAG_SECONDS)
    finally:
        pyautogui.mouseUp()


def click(h, fx, fy):
    import pyautogui

    pyautogui.PAUSE = 0
    x, y, w, hh = pane_rect(h)
    pyautogui.moveTo(x + int(fx * w), y + int(fy * hh))
    time.sleep(0.05)
    pyautogui.mouseDown()
    time.sleep(0.06)
    pyautogui.mouseUp()


def list_strip(img):
    return np.asarray(crop(img, 0.22, LIST_TOP, 0.62, LIST_BOTTOM).convert("L"), dtype=np.float32)[:, ::2]


def measure_shift(a, b):
    """How far the list content moved between two pictures.
    Returns (shift, error): shift is a fraction of the pane height, positive = list scrolled down.
    error is how badly the two pictures still differ after lining them up (high = not measurable)."""
    ga, gb = list_strip(a), list_strip(b)
    n = ga.shape[0]
    best_err, best_dy = None, 0
    for sign in (1, -1):
        x, y = (ga, gb) if sign == 1 else (gb, ga)
        for dy in range(0, int(n * 0.7)):
            err = float(np.abs(x[dy:] - y[:n - dy]).mean())
            if best_err is None or err < best_err:
                best_err, best_dy = err, sign * dy
    return best_dy / a.size[1], best_err


def scroll(h, down, scale=1.0, io=None):
    """Drag once. Returns (picture after, did it move, shift, error) - see measure_shift."""
    io = io or desktop_io()
    io.stop()
    before = io.grab(h)
    io.drag(h, down, scale)
    time.sleep(SETTLE_SECONDS)
    after = io.grab(h)
    moved = list_changed(before, after)
    shift, err = measure_shift(before, after) if moved else (0.0, 0.0)
    return after, moved, shift, err


def go_to_top(h, io=None):
    for _ in range(MAX_UP):
        _, moved, _, _ = scroll(h, False, io=io)
        if not moved:
            _, moved, _, _ = scroll(h, False, io=io)  # confirm with a second try
            if not moved:
                return
    print("Warning: still moving after the top-scroll limit; may not be at the first row.")


def calibrate(h, io=None):
    """From the top of the list: test-drag, measure how far it really went, and pick a drag length
    that moves the list about SHIFT_TARGET. Leaves the list at the top again."""
    scale = CAL_START_SCALE
    for _ in range(3):
        _, moved, shift, err = scroll(h, True, scale, io)
        if moved and err <= SHIFT_MAX_ERR and shift > 0.03:
            new = max(MIN_SCALE, min(MAX_SCALE, scale * SHIFT_TARGET / shift))
            print(f"  test drag {scale:.2f} moved the list {shift * 100:.0f}% of the screen height")
            close = abs(shift - SHIFT_TARGET) < 0.04
            scale = new
            go_to_top(h, io)
            if close:
                break
        elif moved and err > SHIFT_MAX_ERR:
            print(f"  test drag {scale:.2f} moved the list too far to measure; trying a shorter one")
            scale = max(MIN_SCALE, scale * 0.5)
            go_to_top(h, io)
        else:
            scale = min(MAX_SCALE, scale * 1.5)  # barely moved
            go_to_top(h, io)
    print(f"Drag length set to {scale:.2f} (aiming for {SHIFT_TARGET * 100:.0f}% of the screen height per page).")
    return scale


def reveal_double(h, row, known, io=None):
    """Click + on a single-circle row so its double circle shows, read its cost, click - to undo.
    Returns the double-circle cost, or None if there is none."""
    io = io or desktop_io()
    io.stop()
    io.click(h, PLUS_X, row["cost_y"])
    time.sleep(CLICK_SETTLE)
    rows, _, _, _ = read_page(io.grab(h), known)
    cost2 = next((r["cost"] for r in rows if r["name"] == row["name"] and r["tier"] == 2), None)
    for _ in range(3):
        io.stop()
        io.click(h, MINUS_X, row["cost_y"])
        time.sleep(CLICK_SETTLE)
        rows, _, _, _ = read_page(io.grab(h), known)
        if any(r["name"] == row["name"] and r["tier"] == 1 and r["cost"] == row["cost"] for r in rows):
            return cost2
    raise RuntimeError(
        f"Could not put '{row['name']}' back to how it was. Stopping. "
        "Press Reset in the game yourself before doing anything else."
    )


# ------------------------------- commands -------------------------------
class Known(dict):
    """normalised base name -> base name. .variants = {base name: {icon colour: full name}}"""
    variants = {}


def known_names(names):
    k = Known()
    k.variants = {}
    for n in names:
        m = re.fullmatch(r"(.*?)\s*\[(\w+)\]", n)
        if m:  # "Indomitable [blue]" -> base "Indomitable", icon colour "blue"
            k.variants.setdefault(m.group(1), {})[m.group(2).lower()] = n
            k[normalize(m.group(1))] = m.group(1)
        else:
            k[normalize(n)] = n
    return k


def cmd_debug():
    dpi_aware()
    known = known_names(SkillStore(DB_PATH).names())
    h = find_window()
    img = grab(h)
    img.save("debug_pane.png")
    print(f"Pane picture: {img.size[0]}x{img.size[1]}  (saved debug_pane.png - it should show only the Learn screen)")
    name_img = crop(img, NAME_X[0], LIST_TOP, NAME_X[1], LIST_BOTTOM)
    name_img.save("debug_names.png")
    crop(img, COST_X[0], LIST_TOP, COST_X[1], LIST_BOTTOM).save("debug_costs.png")
    crop(img, *POINTS_BOX).save("debug_points.png")
    circles_px = find_circles(np.asarray(name_img.convert("L"), dtype=np.float64))
    paint_circles(name_img, circles_px).save("debug_names_painted.png")
    print("Saved debug_names.png, debug_names_painted.png, debug_costs.png, debug_points.png")
    print("\nCircles found (kind, match score, ring darkness):")
    for kind, cx, cy, s, drop in circles_px:
        print(f"   {'double ◎' if kind == 2 else 'single ○'}  match={s:.2f}  ring={drop:.0f}  at ({cx:.0f},{cy:.0f})")
    print("\nRaw name-column reading (circles already painted out):")
    for t, _ in ocr_lines(paint_circles(name_img, circles_px)):
        print("  ", repr(t))
    print("Raw cost-column reading:")
    for t, _ in ocr_lines(crop(img, COST_X[0], LIST_TOP, COST_X[1], LIST_BOTTOM)):
        print("  ", repr(t))
    print("\nSkill points read:", read_points(img))
    if not known:
        print("\nNo skills in the database yet. Run the 'import' command first to test matching.")
        return
    rows, seen, notes, _ = read_page(img, known)
    print("\nMatched rows (name, circle -> cost):")
    for r in rows:
        print(f"   {r['name']}{TIER_SYMBOL[r['tier']]} -> {r['cost']}   (icon colour: {icon_color_at(img, r['y'])})")
    for note in notes:
        print("   note:", note)


def cmd_scan(reveal, io=None):
    io = io or desktop_io()
    dpi_aware()
    store = SkillStore(io.db_path)
    pairs = store.pairs()
    known = known_names(store.names())
    if not known:
        io.log("Database is empty. Run: python skill_scanner.py import skills_slim.json")
        return
    h = io.window()
    if reveal:
        io.log("Reveal mode: to read double-circle (◎) costs the tool clicks + then - on single-circle skills.")
        io.log("It never presses Confirm or Reset. Hold Esc to stop.")
        io.ask("Press Enter to start... ")
    io.log("Going to the top of the list... (hold Esc to stop)")
    go_to_top(h, io)
    io.log("Testing how far the list moves per drag...")
    scale = calibrate(h, io)
    good = scale                      # the drag length that gave a full-size page (the bot reuses it)

    img = io.grab(h)
    points = io.points(img)
    if points is None:
        points = int(io.ask("Could not read skill points. Type the number: "))
    io.log("Skill points:", points)

    found, warned = {}, set()
    clicked = False

    def record(name, tier, cost):
        if (name, tier) not in pairs:
            if (name, tier) not in warned:
                warned.add((name, tier))
                io.log(f"  note: saw '{name}{TIER_SYMBOL[tier]}' but it is not in your list; ignored")
            return
        old = found.get((name, tier))
        if old is not None and old != cost:
            io.log(f"  note: cost of {name}{TIER_SYMBOL[tier]} changed {old} -> {cost}")
        found[(name, tier)] = cost

    def handle(rows):
        nonlocal clicked
        for r in rows:
            record(r["name"], r["tier"], r["cost"])
        if reveal:
            for r in rows:
                if r["tier"] == 1 and (r["name"], 2) in pairs and (r["name"], 2) not in found:
                    clicked = True
                    c2 = reveal_double(h, r, known, io)
                    if c2 is None:
                        io.log(f"  no double-circle version found for {r['name']}")
                    else:
                        record(r["name"], 2, c2)

    bottom = False
    try:
        rows, _, _, _ = read_page(img, known)
        handle(rows)
        gap_tries, pages = 0, 0
        while pages < MAX_DOWN:
            used = scale
            new_img, moved, shift, err = scroll(h, True, used, io)
            if not moved:
                new_img, moved, shift, err = scroll(h, True, used, io)  # one retry before believing it
            if not moved:
                io.log("Reached the bottom.")
                bottom = True
                break
            rows, _, _, _ = read_page(new_img, known)
            handle(rows)
            pages += 1
            io.log(f"  page {pages}: list moved {shift * 100:.0f}% of the screen height, {len(found)} costs read so far")
            if err <= SHIFT_MAX_ERR and SHIFT_TARGET * 0.8 <= shift <= SHIFT_MAX:
                good = used                   # a full page: the short page at the bottom must not count
            if err > SHIFT_MAX_ERR:
                io.log("  warning: could not measure the movement; it may have moved too far. Using a shorter drag.")
                scale = max(MIN_SCALE, scale * 0.6)
            elif shift > SHIFT_MAX:
                scale = max(MIN_SCALE, min(MAX_SCALE, used * SHIFT_TARGET / shift))
                if gap_tries < MAX_GAP_RETRIES:
                    io.log(f"  moved a bit far ({shift * 100:.0f}%); going back and using a shorter drag")
                    scroll(h, False, used * (1 - SHIFT_TARGET / shift), io)
                    gap_tries += 1
                    continue
                io.log("  warning: still moving too far; some skills may be skipped")
            else:
                gap_tries = 0
                if shift > 0.03:  # keep the drag tuned as we go
                    scale = max(MIN_SCALE, min(MAX_SCALE, used * (SHIFT_TARGET / shift) ** 0.5))
        else:
            io.log("Stopped at the page limit.")
        if clicked:
            after = io.points(io.grab(h))
            if after is not None and after != points:
                io.log(f"WARNING: skill points now read {after}, expected {points}. "
                       "Some skill may still be selected - press Reset in the game.")
    finally:
        store.save_scan(found, points)
        io.log(f"\nSaved {len(found)} of {len(pairs)} entries read on this screen "
               f"(the rest are skills this career cannot learn). Skill points: {points}")
        if not bottom:
            io.log("The scan did NOT reach the bottom of the list, so it is incomplete.")
    return bottom, points, good


def parse_apt(text):
    apt = {}
    for part in text.split(","):
        if not part.strip():
            continue
        key, _, val = part.partition("=")
        key, val = key.strip().lower(), val.strip().upper()
        if key not in STYLES and key not in DISTANCES:
            raise ValueError(f"unknown aptitude '{key}' (use {', '.join(DISTANCES)} and {', '.join(STYLES)})")
        if val not in APT_MULT:
            raise ValueError(f"aptitude '{key}={val}': letter must be one of {' '.join(APT_MULT)}")
        apt[key] = val
    return apt


def cmd_calc(points_override, apt_text, round_mode):
    mode = round_mode or "nearest"
    store = SkillStore(DB_PATH)
    saved_apt = store.meta("apt")
    if apt_text:
        try:
            apt = parse_apt(apt_text)
        except ValueError as e:
            _out(e)
            return
        apt = {**(json.loads(saved_apt) if saved_apt else {}), **apt}
        store.set_meta("apt", json.dumps(apt))
    else:
        apt = json.loads(saved_apt) if saved_apt else {}
    missing = [k for k in [*DISTANCES, *STYLES] if k not in apt]
    if missing:
        _out("Aptitudes missing: " + ", ".join(missing))
        _out("Give them once, e.g.  calc --apt sprint=G,mile=A,medium=A,long=B,front=G,pace=B,late=A,end=G")
        return
    saved_points = store.meta("points")
    points = points_override if points_override is not None else (int(saved_points) if saved_points else None)
    if points is None:
        _out("No skill points known. Run 'scan' or use --points N.")
        return
    groups, assumed = build_groups(store.items(), apt, mode)
    if not groups:
        _out("No scanned skills yet. Run 'scan' first.")
        return
    chosen = best_selection(groups, points)
    chosen.sort(key=lambda o: o[0] / o[1], reverse=True)
    _out("Aptitudes: " + "  ".join(f"{k}={apt[k]}" for k in [*DISTANCES, *STYLES]) + f"   (rounding: {mode})")
    _out(f"Skill points: {points}   (skills with a cost: {len(groups)})\n")
    _out(f"{'Skill':40} {'Base':>6} {'Score':>6} {'Gain':>6} {'Cost':>6} {'Gain/Cost':>10}")
    for _, _, parts in chosen:
        for name, tier, base, fullscore, gain, cost in parts:
            ratio = f"{gain / cost:10.3f}" if cost else "         -"
            _out(f"{(name + TIER_SYMBOL[tier]):40} {base:6d} {fullscore:6d} {gain:6d} {cost:6d} {ratio}")
    total_cost = sum(co for _, co, _ in chosen)
    total_gain = sum(sc for sc, _, _ in chosen)
    _out(f"\nTotal gain: {total_gain}   Total cost: {total_cost}   Left over: {points - total_cost}")
    _out("Score = full score at your aptitude; Gain = Score minus the tier below it (what you actually add).")
    _out("A ◎ or gold is only bought together with the tiers below it; all their costs are counted.")
    if assumed:
        _out(f"\nNot on screen, so assumed already bought ({len(assumed)}): " + ", ".join(sorted(assumed)))


# ---- aptitude screen (the Attributes screen, before the Learn screen) ----
# Each letter's centre, as a fraction of the game pane (same pane as the skill list).
APT_BOXES = {
    "sprint": (0.711, 0.510), "mile": (0.827, 0.510),
    "medium": (0.711, 0.537), "long": (0.827, 0.537),
    "front":  (0.711, 0.578), "pace": (0.827, 0.578),
    "late":   (0.711, 0.605), "end":  (0.827, 0.605),
}
# Letter colours in the game. S, A, B, D, E, F were sampled from the in-game screen;
# C from the radar badges. G is NOT yet sampled, so it is only an estimate.
APT_COLORS = {
    "S": (219, 170, 47), "A": (245, 145, 82), "B": (247, 132, 167), "C": (135, 218, 110),
    "D": (108, 195, 245), "E": (209, 119, 233), "F": (130, 122, 214), "G": (150, 150, 150),
}
APT_RADIUS = 9          # pixels around each letter centre to sample
APT_MIN_PIXELS = 20     # fewer coloured pixels than this = letter not found
APT_MAX_DIST = 45       # colour further than this from every letter = unsure


def read_apt(img):
    """Returns {key: letter or None}. None means the letter could not be read clearly."""
    w, h = img.size
    a = np.asarray(img.convert("RGB"), dtype=int)
    out = {}
    for key, (fx, fy) in APT_BOXES.items():
        cx, cy = int(fx * w), int(fy * h)
        r = APT_RADIUS
        px = a[cy - r:cy + r, cx - r:cx + r].reshape(-1, 3)
        coloured = px[(px.max(1) - px.min(1)) > 60]
        if len(coloured) < APT_MIN_PIXELS:
            out[key] = None
            continue
        c = np.median(coloured, 0)
        best = min(APT_COLORS, key=lambda L: float(np.sum((np.array(APT_COLORS[L]) - c) ** 2)))
        dist = float(np.sqrt(np.sum((np.array(APT_COLORS[best]) - c) ** 2)))
        out[key] = best if dist <= APT_MAX_DIST else None
    return out


def cmd_apt():
    """Reads the eight aptitude letters from the screen and saves them for calc."""
    dpi_aware()
    h = find_window()
    img = grab(h)
    letters = read_apt(img)
    order = [*DISTANCES, *STYLES]
    unread = [k for k in order if letters[k] is None]
    _out("Aptitudes read from screen: " + "  ".join(f"{k}={letters[k] or '?'}" for k in order))
    if unread:
        _out("Could not read: " + ", ".join(unread))
        _out("Nothing was saved. Open the aptitude screen, then run apt again.")
        img.save("debug_apt_pane.png")
        _out("Saved debug_apt_pane.png - send it if a letter is wrong.")
        return
    SkillStore(DB_PATH).set_meta("apt", json.dumps(letters))
    _out("Saved. calc will use these letters from now on.")


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("import")
    s.add_argument("file")
    sub.add_parser("debug")
    sub.add_parser("apt")
    s = sub.add_parser("scan")
    s.add_argument("--no-reveal", action="store_true")
    s = sub.add_parser("calc")
    s.add_argument("--points", type=int)
    s.add_argument("--apt", help="e.g. mile=A,medium=A,long=B,sprint=G,front=G,pace=B,late=A,end=G")
    s.add_argument("--round", choices=["nearest", "floor"], dest="round_mode")
    a = p.parse_args()
    try:
        if a.cmd == "import":
            cmd_import(a.file)
        elif a.cmd == "debug":
            cmd_debug()
        elif a.cmd == "apt":
            cmd_apt()
        elif a.cmd == "scan":
            cmd_scan(not a.no_reveal)
        else:
            cmd_calc(a.points, a.apt, a.round_mode)
    except KeyboardInterrupt:
        _out("\nStopped.")


if __name__ == "__main__":
    main()
