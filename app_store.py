"""The one ActionStore and TemplateCatalog the whole app shares. Import `store` and `catalog` from here.

Built from config and the seed actions. Nothing is written to disk here: engine.init_db() does that.
"""
from action_store import ActionStore
from actions_config import CLUB_ITEMS, SEED_ACTIONS
from config import (DB_PATH, TEMPLATE_DIR, LEGEND_NAMES, LEGEND_UTILITY, SCREEN_DEFAULTS,
                    _OLD_ITEM_KEYS)
from template_catalog import TemplateCatalog

store = ActionStore(DB_PATH, SEED_ACTIONS, TEMPLATE_DIR, _OLD_ITEM_KEYS)
catalog = TemplateCatalog(TEMPLATE_DIR, LEGEND_NAMES, LEGEND_UTILITY, SCREEN_DEFAULTS, CLUB_ITEMS)