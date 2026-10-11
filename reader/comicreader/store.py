#what the reader keeps of its own, in one sqlite file in its data folder: where each comic was read up to,
#and what the last scan learned of each archive, so a restart does not read the whole library again
import json
import os
import sqlite3
import threading
import time


class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.lock = threading.Lock()
        #one connection, shared by the server's threads under the lock: sqlite is happiest with few writers,
        #and every write here is a single small row
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS progress (
                series TEXT PRIMARY KEY,
                key TEXT,
                position INTEGER NOT NULL,
                seen INTEGER NOT NULL,
                updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sources (
                path TEXT PRIMARY KEY,
                data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings (
                scope TEXT PRIMARY KEY,
                data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS growth (
                series TEXT PRIMARY KEY,
                pages INTEGER NOT NULL,
                grew REAL,
                added INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS covers (
                target TEXT PRIMARY KEY,
                data TEXT NOT NULL);
        """)
        #how far down its page the reader was, for a comic read by scrolling: added after the table was
        #first made, so a data folder from before gains it here
        columns = [row[1] for row in self.db.execute("PRAGMA table_info(progress)")]
        if "part" not in columns:
            self.db.execute("ALTER TABLE progress ADD COLUMN part REAL NOT NULL DEFAULT 0")
        self.db.commit()

    def progress(self, series):
        with self.lock:
            row = self.db.execute("SELECT key, position, seen, updated, part FROM progress WHERE series = ?",
                                  (series,)).fetchone()
        if row is None:
            return None
        return {"key": row[0], "position": row[1], "seen": row[2], "updated": row[3], "part": row[4]}

    def every_progress(self):
        with self.lock:
            rows = self.db.execute("SELECT series, key, position, seen, updated, part FROM progress").fetchall()
        return {row[0]: {"key": row[1], "position": row[2], "seen": row[3], "updated": row[4], "part": row[5]}
                for row in rows}

    def save_progress(self, series, key, position, seen, part=0.0):
        #seen is how many pages the comic had when it was read, so "new since you last read" is the pages
        #it has gained since, whatever page the reader stopped on. part is how far down that page the screen
        #was, as a share of the page, so a comic scrolled through opens again exactly where it was left
        stamp = time.time()
        with self.lock:
            self.db.execute("INSERT INTO progress (series, key, position, seen, updated, part) VALUES (?, ?, ?, ?, ?, ?) "
                            "ON CONFLICT(series) DO UPDATE SET key = excluded.key, position = excluded.position, "
                            "seen = MAX(progress.seen, excluded.seen), updated = excluded.updated, part = excluded.part",
                            (series, key, position, seen, stamp, part))
            self.db.commit()
        return self.progress(series)

    def growth(self):
        #when each comic last gained pages, and how many: what a scan saw it holding, against the time before
        with self.lock:
            rows = self.db.execute("SELECT series, pages, grew, added FROM growth").fetchall()
        return {row[0]: {"pages": row[1], "grew": row[2], "added": row[3]} for row in rows}

    def saw(self, counts, now=None):
        #a scan's count of every comic's pages. a comic seen for the first time is only counted - the first
        #scan of a library is not every comic in it being updated at once - and one that has grown since the
        #last scan is noted as having grown now, by how much. one that has shrunk - pages taken out, a
        #chapter re-cut - is counted again without being called updated
        now = time.time() if now is None else now
        known = self.growth()
        with self.lock:
            for series, pages in counts.items():
                before = known.get(series)
                if before is None:
                    self.db.execute("INSERT INTO growth (series, pages, grew, added) VALUES (?, ?, NULL, 0)",
                                    (series, pages))
                elif pages > before["pages"]:
                    self.db.execute("UPDATE growth SET pages = ?, grew = ?, added = ? WHERE series = ?",
                                    (pages, now, pages - before["pages"], series))
                elif pages != before["pages"]:
                    self.db.execute("UPDATE growth SET pages = ? WHERE series = ?", (pages, series))
            self.db.commit()

    def forget_progress(self, series):
        with self.lock:
            self.db.execute("DELETE FROM progress WHERE series = ?", (series,))
            self.db.commit()

    def sources(self):
        with self.lock:
            rows = self.db.execute("SELECT data FROM sources").fetchall()
        found = {}
        for (data,) in rows:
            try:
                source = json.loads(data)
                found[source["path"]] = source
            except (ValueError, KeyError):
                continue
        return found

    def save_source(self, source):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO sources (path, data) VALUES (?, ?)",
                            (source["path"], json.dumps(source)))
            self.db.commit()

    def forget_sources(self, keep):
        #archives that have gone - renamed, or given up for chapter archives - are not carried for ever
        with self.lock:
            known = [row[0] for row in self.db.execute("SELECT path FROM sources").fetchall()]
            gone = [path for path in known if path not in keep]
            self.db.executemany("DELETE FROM sources WHERE path = ?", [(path,) for path in gone])
            self.db.commit()
        return len(gone)

    def settings(self, scope):
        with self.lock:
            row = self.db.execute("SELECT data FROM settings WHERE scope = ?", (scope,)).fetchone()
        try:
            return json.loads(row[0]) if row else {}
        except ValueError:
            return {}

    def save_settings(self, scope, data):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO settings (scope, data) VALUES (?, ?)", (scope, json.dumps(data)))
            self.db.commit()

    def covers(self):
        #the cover chosen for each comic, folder, series and author that has one: a page of a comic, by the
        #page itself so it survives renumbering, or a picture put in the data folder
        with self.lock:
            rows = self.db.execute("SELECT target, data FROM covers").fetchall()
        found = {}
        for target, data in rows:
            try:
                found[target] = json.loads(data)
            except ValueError:
                continue
        return found

    def save_cover(self, target, data):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO covers (target, data) VALUES (?, ?)", (target, json.dumps(data)))
            self.db.commit()

    def forget_cover(self, target):
        with self.lock:
            self.db.execute("DELETE FROM covers WHERE target = ?", (target,))
            self.db.commit()
