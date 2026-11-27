"""
UmaBot configuration constants.

All paths, thresholds, timing, and static data live here.
Other modules import from this single source of truth.
"""
import ctypes
import os
import sys
from pathlib import Path

# Must happen before any window/screen calls so coordinates are real pixels
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import pyautogui  # noqa: E402

pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False  # corner stop turned off: press STOP_KEY to stop instead

# --------------------------------------------------------------------------
# PATHS
# --------------------------------------------------------------------------
# Files live next to the exe (or next to this script when run as Python)
BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
if os.environ.get("UMABOT_HOME"):      # run.bat can point the source version at the folder holding your templates/db
    BASE = Path(os.environ["UMABOT_HOME"])

DB_PATH = BASE / "umabot.db"
TEMPLATE_DIR = BASE / "templates"
DEBUG_DIR = BASE / "debug"
RECORD_DIR = BASE / "records"          # crops of what was recorded (e.g. carats earned), for checking
CARATS_CSV = BASE / "carats.csv"      # one line per finished Independent Training run

# --------------------------------------------------------------------------
# WINDOW / MATCHING / TIMING
# --------------------------------------------------------------------------
REF_HEIGHT = 1080      # every screenshot is scaled so its height is this -> window size no longer matters
THRESHOLD = 0.85
DONE_THRESHOLD = 0.92   # the already-done checks must match almost exactly
DEFAULT_WINDOW_TITLE = "umamusume"

CLICK_DELAY = 1.0  # seconds to wait after a button is spotted, before clicking it (a slow PC/game ignores clicks while the screen is still settling)
STOP_KEY = "p"
PAUSE_KEY = "["
SKIP_KEY = "]"
START_KEY = "f8"

# the Daily Sale pop-up can only appear after a race (daily race, team trial, daily legend race). From the
# "popup_watch on" step after such a race until the "popup_watch off" step back on the home screen, any step that
# can't find what it wants for POPUP_GRACE seconds also looks for these popups and closes them.
POPUP_TEMPLATES = ["daily_sale_cancel_btn"]
POPUP_GRACE = 3

# --------------------------------------------------------------------------
# ITEM / LEGEND / SCREEN CONSTANTS
# --------------------------------------------------------------------------
ITEM_KEYS = ["mood_boost", "weather_sunny", "weather_rain", "inner_bracket", "outer_bracket"]
MAX_ITEMS = 2
_OLD_ITEM_KEYS = dict(zip(["item_1", "item_2", "item_3", "item_4", "item_5"], ITEM_KEYS))

LEGEND_UTILITY = {"legend_done_marker", "legend_items_race_btn", "legend_next_btn",
                  "legend_result_1st", "legend_runners_marker", "legend_view_results_btn",
                  "legend_race_pick", "legend_race_ex"}

LEGEND_NAMES = [
    "el_condor_pasa", "special_week", "symboli_rudolf", "king_halo", "taiki_shuttle",
    "sakura_bakushin_o", "curren_chan", "winning_ticket", "vodka", "tokai_teio",
    "mayano_top_gun", "mejiro_mcqueen", "tm_opera_o", "super_creek", "mejiro_ryan",
    "silence_suzuka", "gold_ship", "maruzensky", "fuji_kiseki", "mihono_bourbon",
    "matikanefukukitaru", "seiun_sky", "biwa_hayahide", "air_groove", "eishin_flash",
    "agnes_digital", "nice_nature", "grass_wonder", "oguri_cap",
]

SCREEN_DEFAULTS = ["home", "race", "club", "shop", "mission", "daily_programs", "career",
                   "ind_scenario", "ind_trainee", "ind_legacy", "ind_support", "ind_borrow", "ind_final",
                   "ind_event_rewards", "team_page", "team_opponent", "team_items",
                   "legend_list", "legend_items", "ind_training", "ind_skill_learn", "multi_race"]

SCREEN_LABELS = {"home": "Home", "race": "Race", "club": "Club", "shop": "Shop", "mission": "Mission",
                 "daily_programs": "Daily Programs", "career": "Career", "ind_scenario": "Scenario Select", "ind_trainee": "Trainee Select",
                 "ind_legacy": "Legacy Select", "ind_support": "Support Formation",
                 "ind_borrow": "Borrow Card", "ind_final": "Final Confirmation",
                 "ind_event_rewards": "Event Rewards Collected", "team_page": "Team Trials Page",
                 "team_opponent": "Select Opponent", "team_items": "Team Trials Items Selected",
                 "legend_list": "Legend List", "legend_items": "Legend Items Selected",
                 "ind_training": "Training In Progress", "ind_skill_learn": "Learn Skills"}