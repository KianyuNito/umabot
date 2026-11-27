"""Reads carats.csv for the History page. Pure Python: no Qt, no game."""
import csv
from datetime import datetime

ACTION_LABELS = {"independent_run": "Independent run", "team_trials": "Team trials"}


def read_carats(path):
    """[{action, when (datetime), carats ("?" or a number), image}] newest first.
    Rows from before the action column existed have action "". Lines it can't read are skipped."""
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
    except OSError:
        return []
    out = []
    for r in rows:
        try:
            out.append({"action": r[4] if len(r) > 4 else "",
                        "when": datetime.strptime(f"{r[0]} {r[1]}", "%Y-%m-%d %H:%M:%S"),
                        "carats": r[2], "image": r[3]})
        except (IndexError, ValueError):
            continue                    # the header, and any damaged line
    return out[::-1]
