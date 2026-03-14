"""storage.py — Classification storage backends for astro_swiper."""

import os, sqlite3, csv


class StorageBackend:
    def get_classified(self) -> set:           raise NotImplementedError
    def save(self, sub, sci, ref, key, label): raise NotImplementedError
    def undo(self) -> 'str | None':            raise NotImplementedError
    def clear(self):                           raise NotImplementedError
    def close(self): pass


class SQLiteBackend(StorageBackend):
    def __init__(self, db_path):
        os.makedirs(os.path.dirname(db_path) or '.', exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS classifications (
                rowid    INTEGER PRIMARY KEY AUTOINCREMENT,
                sci_path TEXT UNIQUE,
                sub_path TEXT,
                ref_path TEXT,
                label    TEXT
            )
        """)
        self._db.commit()

    def get_classified(self):
        return {r[0] for r in self._db.execute(
            "SELECT sci_path FROM classifications"
        ).fetchall()}

    def save(self, sub, sci, ref, key, label):
        self._db.execute(
            "INSERT OR REPLACE INTO classifications "
            "(sci_path, sub_path, ref_path, label) VALUES (?, ?, ?, ?)",
            (sci, sub, ref, label),
        )
        self._db.commit()

    def undo(self):
        row = self._db.execute(
            "SELECT sci_path FROM classifications ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        self._db.execute("DELETE FROM classifications WHERE sci_path = ?", (row[0],))
        self._db.commit()
        return row[0]

    def clear(self):
        self._db.execute("DELETE FROM classifications")
        self._db.commit()

    def close(self):
        self._db.close()


class CSVBackend(StorageBackend):
    def __init__(self, csv_path):
        os.makedirs(os.path.dirname(csv_path) or '.', exist_ok=True)
        self._path = csv_path
        if not os.path.exists(csv_path):
            with open(csv_path, 'w', newline='') as f:
                csv.writer(f).writerow(['sub_path', 'sci_path', 'ref_path', 'label'])

    def get_classified(self):
        with open(self._path, newline='') as f:
            return {row['sci_path'] for row in csv.DictReader(f)}

    def save(self, sub, sci, ref, key, label):
        with open(self._path, 'a', newline='') as f:
            csv.writer(f).writerow([sub, sci, ref, label])

    def undo(self):
        with open(self._path, newline='') as f:
            rows = list(csv.reader(f))
        if len(rows) <= 1:
            return None
        last_sci = rows[-1][1]
        with open(self._path, 'w', newline='') as f:
            csv.writer(f).writerows(rows[:-1])
        return last_sci

    def clear(self):
        with open(self._path, 'w', newline='') as f:
            csv.writer(f).writerow(['sub_path', 'sci_path', 'ref_path', 'label'])


class TxtBackend(StorageBackend):
    """Original multi-file format. keybinds must be {key: filepath}."""
    def __init__(self, keybinds, already_classified_path):
        self._keybinds = keybinds
        self._ac_path  = already_classified_path
        os.makedirs(os.path.dirname(already_classified_path) or '.', exist_ok=True)
        if not os.path.exists(already_classified_path):
            open(already_classified_path, 'w').close()
        for path in keybinds.values():
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)

    def get_classified(self):
        with open(self._ac_path) as f:
            lines = [l.strip() for l in f if l.strip()]
        return set(lines[i] for i in range(0, len(lines), 2))

    def save(self, sub, sci, ref, key, label):
        with open(self._keybinds[key], 'a') as f:
            f.write(f"{sub}\n{sci}\n{ref}\n")
        with open(self._ac_path, 'a') as f:
            f.write(f"{sci}\n{key}\n")

    def undo(self):
        with open(self._ac_path) as f:
            lines = f.readlines()
        if len(lines) < 2:
            return None
        last_key = lines[-1].strip()
        last_sci = lines[-2].strip()
        with open(self._ac_path, 'w') as f:
            f.writelines(lines[:-2])
        cat_path = self._keybinds[last_key]
        with open(cat_path) as f:
            cat_lines = f.readlines()
        with open(cat_path, 'w') as f:
            f.writelines(cat_lines[:-3])
        return last_sci

    def clear(self):
        open(self._ac_path, 'w').close()
        for path in self._keybinds.values():
            open(path, 'w').close()


def make_backend(cfg, keybinds) -> StorageBackend:
    storage_cfg = cfg.get('storage', {})
    backend     = storage_cfg.get('backend', 'sqlite').lower()
    if backend == 'sqlite':
        return SQLiteBackend(storage_cfg.get('db', 'classifications.db'))
    elif backend == 'csv':
        return CSVBackend(storage_cfg.get('file', 'classifications.csv'))
    elif backend == 'txt':
        return TxtBackend(
            keybinds=keybinds,
            already_classified_path=storage_cfg.get(
                'already_classified', 'training_sets/already_classified.txt'
            ),
        )
    raise ValueError(f"Unknown storage backend '{backend}'. Choose sqlite, csv, or txt.")
