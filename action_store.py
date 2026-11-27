"""Action store: the actions table, today's progress marks and the app settings, kept in SQLite.

One module owns the schema, the seed merge and the old-key migration. Everything it needs from outside
(database path, seed actions, template folder, old->new item key map) is passed in, so the tests can point
it at a temporary file and need neither the game nor the rest of umabot.

Every call opens its own short-lived connection, so the GUI thread and the run thread never share one.
`snapshot()` is the call to use when drawing the window: one connection, actions and today's status together.
"""
import datetime
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class ActionStore:
    def __init__(self, db_path, seed_actions, template_dir=None, old_item_keys=None, today=None):
        self.db_path = db_path
        self.seed_actions = seed_actions
        self.template_dir = Path(template_dir) if template_dir else None
        self.old_item_keys = old_item_keys or {}
        self._today = today or (lambda: datetime.date.today().isoformat())

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:                      # commit on success, roll back on error
                yield conn
        finally:
            conn.close()                    # sqlite3's own "with" never closes

    @staticmethod
    def _to_action(row):
        return {"name": row["name"], "enabled": bool(row["enabled"]),
                "settings": json.loads(row["settings"]), "info": json.loads(row["info"])}

    # ---------------- setup and migration ----------------
    def init(self):
        """Create the tables, then merge the seed actions in: keep the user's values, pick up new setting
        keys and refreshed info. Settings saved under the old item_N names move to their new names."""
        had_existing = False
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS actions(
                name TEXT PRIMARY KEY, order_idx INTEGER, enabled INTEGER,
                settings TEXT, info TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS progress(
                day TEXT, name TEXT, status TEXT, detail TEXT, PRIMARY KEY(day, name))""")
            c.execute("CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY, value TEXT)")
            c.execute("DELETE FROM actions WHERE name=?", ("clear_popups",))      # action removed
            for a in self.seed_actions:
                row = c.execute("SELECT settings FROM actions WHERE name=?", (a["name"],)).fetchone()
                if not row:
                    c.execute("INSERT INTO actions VALUES(?,?,?,?,?)",
                              (a["name"], a["order_idx"], a["enabled"],
                               json.dumps(a["settings"]), json.dumps(a["info"])))
                    continue
                had_existing = True
                stored = json.loads(row["settings"])
                for old_k, new_k in self.old_item_keys.items():          # item_1.. were renamed
                    if old_k in stored and new_k not in stored:
                        stored[new_k] = stored[old_k]
                merged = {k: stored.get(k, v) for k, v in a["settings"].items()}
                for k, opts in a["info"].get("options", {}).items():
                    if merged.get(k) not in opts:
                        merged[k] = a["settings"][k]
                c.execute("UPDATE actions SET settings=?, info=?, order_idx=? WHERE name=?",
                          (json.dumps(merged), json.dumps(a["info"]), a["order_idx"], a["name"]))
        if had_existing:
            self._rename_old_templates()

    def _rename_old_templates(self):
        """Template pictures captured under the old item_N names get the new file names."""
        if not self.template_dir:
            return
        for old_k, new_k in self.old_item_keys.items():
            old_f = self.template_dir / f"legend_{old_k}.png"
            new_f = self.template_dir / f"legend_item_{new_k}.png"
            if old_f.exists() and not new_f.exists():
                old_f.rename(new_f)

    # ---------------- actions ----------------
    def actions(self):
        with self._conn() as c:
            rows = c.execute("SELECT * FROM actions ORDER BY order_idx").fetchall()
        return [self._to_action(r) for r in rows]

    def action(self, name):
        with self._conn() as c:
            row = c.execute("SELECT * FROM actions WHERE name=?", (name,)).fetchone()
        return self._to_action(row) if row else None

    def save(self, name, enabled, settings):
        with self._conn() as c:
            c.execute("UPDATE actions SET enabled=?, settings=? WHERE name=?",
                      (1 if enabled else 0, json.dumps(settings), name))

    # ---------------- today's progress ----------------
    def status(self, name):
        with self._conn() as c:
            r = c.execute("SELECT status FROM progress WHERE day=? AND name=?",
                          (self._today(), name)).fetchone()
        return r["status"] if r else "pending"

    def set_status(self, name, status, detail=""):
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO progress VALUES(?,?,?,?)",
                      (self._today(), name, status, detail))

    def reset_today(self):
        with self._conn() as c:
            c.execute("DELETE FROM progress WHERE day=?", (self._today(),))

    def snapshot(self):
        """Every action in run order, each with today's "status" added. One connection, two queries."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM actions ORDER BY order_idx").fetchall()
            marks = {r["name"]: r["status"]
                     for r in c.execute("SELECT name, status FROM progress WHERE day=?", (self._today(),))}
        return [dict(self._to_action(r), status=marks.get(r["name"], "pending")) for r in rows]

    # ---------------- app settings ----------------
    def app_setting(self, key, default=""):
        with self._conn() as c:
            r = c.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_app_setting(self, key, value):
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO app_settings VALUES(?,?)", (key, value))
