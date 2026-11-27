"""Skills store: the skills and meta tables in skills.db.

One module owns the table layout, the old-format rename, the import and the cost scan, so nothing else
opens skills.db. Every call opens its own short-lived connection (same pattern as ActionStore).
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime


class SkillStore:
    def __init__(self, db_path):
        self.db_path = db_path

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:                      # commit on success, roll back on error
                cols = [r[1] for r in conn.execute("PRAGMA table_info(skills)")]
                if cols and ("tier" not in cols or "base" not in cols):    # old format: keep it for the import
                    conn.execute("DROP TABLE IF EXISTS skills_old")
                    conn.execute("ALTER TABLE skills RENAME TO skills_old")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS skills("
                    "name TEXT NOT NULL, tier INTEGER NOT NULL, base INTEGER NOT NULL, alts TEXT NOT NULL, "
                    "grp INTEGER NOT NULL, rank INTEGER NOT NULL, cost INTEGER, scanned_at TEXT, "
                    "PRIMARY KEY(name, tier))")
                conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
                yield conn
        finally:
            conn.close()

    # ---------------- reading ----------------
    def count(self):
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM skills").fetchone()[0]

    def items(self):
        """(name, tier, base, alts, grp, rank, cost) for every skill."""
        with self._conn() as c:
            return c.execute("SELECT name, tier, base, alts, grp, rank, cost FROM skills").fetchall()

    def names(self):
        with self._conn() as c:
            return [r[0] for r in c.execute("SELECT DISTINCT name FROM skills")]

    def pairs(self):
        """{(name, tier)} of every skill in the list."""
        with self._conn() as c:
            return set(c.execute("SELECT name, tier FROM skills").fetchall())

    # ---------------- writing ----------------
    def replace_skills(self, rows):
        """rows: (name, tier, base, alts_json, grp, rank). Upserts them and deletes every skill not in rows.
        Costs already scanned in an old-format table are carried over. Returns how many were carried."""
        keep = {(r[0], r[1]) for r in rows}
        with self._conn() as c:
            c.executemany(
                "INSERT INTO skills(name, tier, base, alts, grp, rank) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(name, tier) DO UPDATE SET base=excluded.base, alts=excluded.alts, "
                "grp=excluded.grp, rank=excluded.rank", rows)
            for name, tier in c.execute("SELECT name, tier FROM skills").fetchall():
                if (name, tier) not in keep:
                    c.execute("DELETE FROM skills WHERE name=? AND tier=?", (name, tier))
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='skills_old'").fetchone():
                return 0
            carried = c.execute(
                "UPDATE skills SET cost=(SELECT o.cost FROM skills_old o WHERE o.name=skills.name AND o.tier=skills.tier) "
                "WHERE EXISTS (SELECT 1 FROM skills_old o WHERE o.name=skills.name AND o.tier=skills.tier "
                "AND o.cost IS NOT NULL)").rowcount
            c.execute("DROP TABLE skills_old")
            return carried

    def save_scan(self, found, points):
        """found: {(name, tier): cost}. Clears every old cost, stores these, remembers the skill points."""
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as c:
            c.execute("UPDATE skills SET cost=NULL, scanned_at=NULL")
            c.executemany("UPDATE skills SET cost=?, scanned_at=? WHERE name=? AND tier=?",
                          [(cost, now, n, t) for (n, t), cost in found.items()])
            c.execute("INSERT OR REPLACE INTO meta VALUES('points', ?)", (str(points),))

    # ---------------- meta (saved aptitudes, last skill points) ----------------
    def meta(self, key):
        with self._conn() as c:
            r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def set_meta(self, key, value):
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, value))