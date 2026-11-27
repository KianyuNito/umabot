"""
Vision module: template matching, screen detection, OCR.
Pure functions, no GUI/database state.
"""
import cv2
import numpy as np

from config import THRESHOLD, SCREEN_LABELS
from app_store import catalog


_template_cache = {}


def load_template(name):
    path = catalog.path(name)
    try:
        stamp = path.stat().st_mtime
    except OSError:
        raise FileNotFoundError(f"Missing template: templates\\{name}.png")
    cached = _template_cache.get(name)
    if cached is None or cached[0] != stamp:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(f"Missing template: templates\\{name}.png")
        _template_cache[name] = (stamp, img)
    return _template_cache[name][1]


def best_score(screen, name):
    tpl = load_template(name)
    if tpl.shape[0] > screen.shape[0] or tpl.shape[1] > screen.shape[1]:
        return 0.0
    return float(cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED).max())


def find(screen, name, threshold=THRESHOLD):
    tpl = load_template(name)
    if tpl.shape[0] > screen.shape[0] or tpl.shape[1] > screen.shape[1]:
        return None
    res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    if score >= threshold:
        h, w = tpl.shape[:2]
        return loc[0] + w // 2, loc[1] + h // 2, score
    return None


def find_all(screen, name, threshold=THRESHOLD):
    tpl = load_template(name)
    th, tw = tpl.shape[:2]
    if th > screen.shape[0] or tw > screen.shape[1]:
        return []
    res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= threshold)
    found = []
    for score, x, y in sorted(zip(res[ys, xs], xs, ys), key=lambda t: -t[0]):
        cx, cy = int(x) + tw // 2, int(y) + th // 2
        if all(abs(cx - fx) > tw // 2 or abs(cy - fy) > th // 2 for fx, fy, _ in found):
            found.append((cx, cy, float(score)))
    return found


def screen_label(name):
    return SCREEN_LABELS.get(name, name.replace("_", " ").title())


# --- screen markers: optional images that prove which screen the game is on (names: catalog.markers()) ---


def detect_screen(screen):
    scores = {}
    for marker in catalog.markers():
        if catalog.exists(marker):
            scores[marker[len("screen_"):]] = best_score(screen, marker)
    if not scores:
        return None, 0.0, scores
    best = max(scores, key=scores.get)
    return (best if scores[best] >= THRESHOLD else None), scores[best], scores


def read_count(img):
    import re
    big = cv2.resize(img, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    candidates = [big, bw, 255 - bw]

    def parse(text):
        m = re.search(r"[xX×]\s*(\d[\d,. ]*)", text or "") or re.search(r"(\d[\d,. ]*)\s*$", (text or "").strip())
        digits = re.sub(r"\D", "", m.group(1)) if m else ""
        return int(digits) if digits else None

    try:
        import winocr
        from PIL import Image
        for c in candidates:
            pil = Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB) if c.ndim == 3 else c)
            res = winocr.recognize_pil_sync(pil, "en")
            text = res.get("text", "") if isinstance(res, dict) else getattr(res, "text", "")
            n = parse(text)
            if n is not None:
                return n
    except Exception:
        pass
    return None