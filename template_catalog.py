"""Template catalog: which template pictures exist, what they are called, where they live, saving a new one.

Pure: it gets the folder and the static name lists from the caller, so tests can use a temporary folder.
The shared instance is built in app_store.py. What the actions NEED is not here (that is engine.py's
step walk); this module only knows the files and the names that can exist.
"""
from pathlib import Path


class TemplateCatalog:
    def __init__(self, template_dir, legend_names, legend_utility, screen_defaults, club_items):
        self.dir = Path(template_dir)
        self.legend_names = list(legend_names)
        self.legend_utility = set(legend_utility)
        self.screen_defaults = list(screen_defaults)
        self.club_items = tuple(club_items)

    # ---------------- files ----------------
    def path(self, name):
        return self.dir / f"{name}.png"

    def exists(self, name):
        return self.path(name).exists()

    def missing(self, required):
        return [n for n in required if not self.exists(n)]

    def save(self, name, crop):
        """Write the crop as template <name>. Returns False if the file could not be written."""
        import cv2      # here and not at the top, so the names above work without OpenCV
        self.dir.mkdir(exist_ok=True)
        return bool(cv2.imwrite(str(self.path(name)), crop))

    # ---------------- names ----------------
    def markers(self):
        """screen_<n>: the suggested screens, then any other screen_*.png on disk."""
        names = [f"screen_{n}" for n in self.screen_defaults]
        for p in sorted(self.dir.glob("screen_*.png")):
            if p.stem not in names:
                names.append(p.stem)
        return names

    def available_legends(self):
        """Every known legend (in-game order), plus any extra legend_<n>.png tile you captured yourself."""
        names = list(self.legend_names)
        for p in sorted(self.dir.glob("legend_*.png")):
            if p.stem in self.legend_utility or p.stem.endswith("_race") or p.stem.startswith("legend_item_"):
                continue
            n = p.stem[len("legend_"):]
            if n not in names:
                names.append(n)
        return names

    def available_agendas(self):
        """Saved agendas you captured a name for: agenda_<n>.png"""
        return [p.stem[len("agenda_"):] for p in sorted(self.dir.glob("agenda_*.png"))]

    def picker_names(self, missing, capturable):
        """Every name the Save-as box offers: missing first, then the rest, no duplicates.
        `missing` and `capturable` are what the actions need (engine.py knows those)."""
        return list(dict.fromkeys([
            *missing, *capturable, *self.markers(),
            *(f"legend_{n}" for n in self.available_legends()),
            *(f"club_item_{i}_shoes" for i in self.club_items),
            "club_request_cooldown_msg", "club_request_cancel_btn", "club_request_confirm_btn",
            "club_request_result_popup", "club_request_result_close_btn",
            *(f"empty_{i}" for i in range(1, 6)),      # spare names to capture a picture under as a placeholder
        ]))