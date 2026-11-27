"""
Skill plan for the Independent career.

Pure logic: no screen, no OCR. Takes the aptitudes and the skill points read from the game,
reads costs and base scores from skills.db, and returns the purchase set with the highest total gain.
Used by engine.py (the bot) and can later replace the calc section of the scanner.
"""
import json
from fractions import Fraction

from skill_store import SkillStore

# aptitude letter -> multiplier (exact fractions)
APT_MULT = {"S": Fraction(11, 10), "A": Fraction(11, 10), "B": Fraction(9, 10), "C": Fraction(9, 10),
            "D": Fraction(8, 10), "E": Fraction(8, 10), "F": Fraction(8, 10), "G": Fraction(7, 10)}
STYLES = {"front": 1, "pace": 2, "late": 3, "end": 4}
DISTANCES = {"sprint": 1, "mile": 2, "medium": 3, "long": 4}
TIER_SYMBOL = {0: "", 1: " ○", 2: " ◎"}
ROUND_MODE = "nearest"


def rnd(x, mode=ROUND_MODE):
    """x is an exact Fraction."""
    return int(x // 1) if mode == "floor" else int((x + Fraction(1, 2)) // 1)


def multiplier(alts, apt):
    """alts: [(style|None, distance|None)]; [] = never scales. Best alternative wins."""
    if not alts:
        return Fraction(1)
    style_name = {v: k for k, v in STYLES.items()}
    dist_name = {v: k for k, v in DISTANCES.items()}
    best = None
    for style, dist in alts:
        m = Fraction(1)
        if style is not None:
            m *= APT_MULT[apt[style_name[style]]]
        if dist is not None:
            m *= APT_MULT[apt[dist_name[dist]]]
        best = m if best is None else max(best, m)
    return best


def build_groups(items, apt, mode=ROUND_MODE):
    """items: (name, tier, base, alts_json, grp, rank, cost|None).
    Returns (groups, assumed). Each group is one skill chain; at most one of its options can be taken.
    An option is (total gain, total cost, parts); parts = (name, tier, base, full score, gain, cost)."""
    chains = {}
    for it in items:
        chains.setdefault(it[4], []).append(it)
    groups, assumed = [], []
    for members in chains.values():
        members.sort(key=lambda m: m[5])
        full = [rnd(m[2] * multiplier(json.loads(m[3]), apt), mode) for m in members]
        first = next((i for i, m in enumerate(members) if m[6]), None)
        if first is None:
            continue
        for i in range(first):
            assumed.append(members[i][0] + TIER_SYMBOL[members[i][1]])
        opts, parts, gain, cost = [], [], 0, 0
        for j in range(first, len(members)):
            name, tier, base, _, _, _, c = members[j]
            if not c:
                break  # a tier we could not read blocks everything above it
            g = full[j] - (full[j - 1] if j > 0 else 0)
            gain += g
            if j > first and name != members[j - 1][0]:
                # A skill on its own row (a gold skill) is charged its displayed price, and the game
                # selects its prerequisite (white) with it at no extra charge (checked in the game:
                # tapping the gold took exactly its price). So the lower parts on other rows cost 0 here.
                parts = [(n, t, b, f, gg, 0 if n != name else cc) for (n, t, b, f, gg, cc) in parts]
                cost = c
            else:
                cost += c               # same row: the second tier (◎) costs extra on top of the first (○)
            parts = parts + [(name, tier, base, full[j], g, c)]
            opts.append((gain, cost, parts))
        if opts:
            groups.append(opts)
    return groups, assumed


def best_selection(groups, points):
    """Multiple-choice knapsack: best total gain within the points. Returns the chosen options."""
    n = len(groups)
    dp = [0] * (points + 1)
    take = [bytearray(points + 1) for _ in range(n)]
    for i, opts in enumerate(groups):
        for w in range(points, 0, -1):
            best, pick = dp[w], 0
            for k, (sc, co, _) in enumerate(opts):
                if co <= w and dp[w - co] + sc > best:
                    best, pick = dp[w - co] + sc, k + 1
            dp[w] = best
            take[i][w] = pick
    w, chosen = points, []
    for i in range(n - 1, -1, -1):
        k = take[i][w]
        if k:
            chosen.append(groups[i][k - 1])
            w -= groups[i][k - 1][1]
    return chosen


def take_must_buy(groups, points, must_buy):
    """Buy the must-buy skills first, in order: the cheapest option of the skill's chain that includes it.
    Returns (forced options, groups left for the picker, points left, why each skipped name was skipped).
    A name is skipped if it is not in any group (not scanned, unreadable cost, or its chain was already taken
    by an earlier name) or if its option does not fit in the points left; the next name is then tried.
    shortcut: always the cheapest option, so the picker never upgrades a must-buy chain to its next tier."""
    forced, skipped = [], []
    for name in must_buy:
        found = [(g, o) for g in groups for o in g if any(p[0] == name for p in o[2])]
        if not found:
            skipped.append(f"{name}: not in the scan, cost unreadable, or same chain as an earlier must-buy")
            continue
        g, opt = min(found, key=lambda go: go[1][1])
        if opt[1] > points:
            skipped.append(f"{name}: costs {opt[1]}, only {points} points left")
            continue
        forced.append(opt)
        points -= opt[1]
        groups = [x for x in groups if x is not g]
    return forced, groups, points, skipped


def make_plan(db_path, apt, points, mode=ROUND_MODE, must_buy=()):
    """The purchase plan.
    apt: {"sprint": "E", ..., "end": "D"} (all eight keys); points: skill points on screen.
    Returns a dict:
      picks   [{"name", "tier" (1 = ○, 2 = ◎), "cost", "gain"}] in buy order (lower tier first)
      gain, cost, left    totals
      assumed             skills not on the list, treated as already bought
      skipped             must_buy names that could not be bought, each with the reason
    Raises ValueError if the aptitudes are incomplete or the database is empty."""
    missing = [k for k in [*DISTANCES, *STYLES] if k not in apt]
    if missing:
        raise ValueError("aptitudes missing: " + ", ".join(missing))
    groups, assumed = build_groups(SkillStore(db_path).items(), apt, mode)
    if not groups:
        raise ValueError("no scanned costs in the database; run the scanner's 'scan' first")
    forced, groups, left, skipped = take_must_buy(groups, points, must_buy)
    chosen = forced + best_selection(groups, left)
    picks = []
    for chain, (gain, cost, parts) in enumerate(chosen):
        for pos, (name, tier, _base, _full, g, c) in enumerate(parts):
            # chain/pos: parts of one chain, lowest first. Tapping a higher part in the game also selects
            # the lower parts that sit on other rows (e.g. a gold skill selects its white prerequisite).
            picks.append({"name": name, "tier": tier, "cost": c, "gain": g, "chain": chain, "pos": pos})
    total_cost = sum(p["cost"] for p in picks)
    return {
        "picks": picks,
        "gain": sum(p["gain"] for p in picks),
        "cost": total_cost,
        "left": points - total_cost,
        "assumed": sorted(assumed),
        "skipped": skipped,
    }
