#!/usr/bin/env python3
"""Migrate an astro_swiper SQLite classifications DB from _id-keyed cache paths
to objectId-keyed cache paths.

Reads the mongo config block to find the alerts collection containing objectIds
(via `mongo.object_id_lookup.from`), batch-resolves every unique _id in the DB,
renames the on-disk cache files, and rewrites sub/sci/ref paths in the DB.

Dry-run by default — pass --apply to commit.

Usage:
    python migrate_to_objectid.py                 # dry run against config.yaml
    python migrate_to_objectid.py --apply         # commit changes
    python migrate_to_objectid.py -c other.yaml --apply
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

import yaml
from pymongo import MongoClient
from bson import ObjectId

TAG_RE = re.compile(r'^(?P<key>.+)_(?P<tag>sub|sci|ref)\.fits$')


def parse_key(path_str):
    """Split a cache path into (parent_dir, key, tag) or None if it doesn't match."""
    p = Path(path_str)
    m = TAG_RE.match(p.name)
    if not m:
        return None
    return p.parent, m.group('key'), m.group('tag')


def coerce_id(key):
    """Cache keys are strings; Mongo _ids might be int64 (ZTF/LSST) or ObjectId."""
    try:
        return int(key)
    except ValueError:
        pass
    try:
        return ObjectId(key)
    except Exception:
        return key


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-c', '--config', default='config.yaml')
    ap.add_argument('--apply', action='store_true',
                    help='Commit changes; otherwise dry-run only.')
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    mcfg  = cfg.get('mongo', {})
    look  = mcfg.get('object_id_lookup') or {}
    alerts_name      = look.get('from')
    object_id_field  = mcfg.get('object_id_field', 'objectId')
    if not alerts_name:
        sys.exit("Need mongo.object_id_lookup.from in config to locate the alerts collection.")

    sqlite_path = cfg.get('storage', {}).get('db')
    if not sqlite_path or not Path(sqlite_path).exists():
        sys.exit(f"SQLite DB not found at: {sqlite_path!r}")

    client = MongoClient(mcfg['uri'])
    alerts = client[mcfg['database']][alerts_name]

    db = sqlite3.connect(sqlite_path)
    rows = db.execute(
        "SELECT rowid, sub_path, sci_path, ref_path FROM classifications"
    ).fetchall()

    parsed_rows = []
    keys = set()
    for rowid, sub, sci, ref in rows:
        parsed = [parse_key(p) for p in (sub, sci, ref)]
        if not all(parsed):
            continue
        keys.add(parsed[1][1])  # key from sci
        parsed_rows.append((rowid, sub, sci, ref, parsed))

    print(f"{len(rows)} DB rows / {len(parsed_rows)} with parseable paths / "
          f"{len(keys)} unique cache keys.")

    mapping = {}
    cursor = alerts.find(
        {'_id': {'$in': [coerce_id(k) for k in keys]}},
        {object_id_field: 1},
    )
    for doc in cursor:
        obj_id = doc.get(object_id_field)
        if obj_id is not None:
            mapping[str(doc['_id'])] = str(obj_id)

    missing = [k for k in keys if k not in mapping]
    print(f"Resolved {len(mapping)}/{len(keys)} _ids to objectIds; {len(missing)} missing.")
    if missing:
        print("  first 5 missing:", missing[:5])

    # Group rows by the new sci_path so we can dedup — multiple _ids for the same
    # objectId collapse to a single DB row (sci_path is UNIQUE).
    by_new_sci = {}
    for rowid, sub, sci, ref, parsed in parsed_rows:
        key = parsed[1][1]
        if key not in mapping:
            continue
        obj_id = mapping[key]
        sci_dir = parsed[1][0]
        new_sci = str(sci_dir / f'{obj_id}_sci.fits')
        by_new_sci.setdefault(new_sci, []).append(
            (rowid, sub, sci, ref, parsed, obj_id)
        )

    renames = {}        # old_path -> new_path
    row_updates = []    # (rowid, new_sub, new_sci, new_ref)
    drop_rowids = []    # rows we'll delete because a newer dup wins
    for new_sci, group in by_new_sci.items():
        group.sort(key=lambda r: r[0])
        winner = group[-1]
        for r in group[:-1]:
            drop_rowids.append(r[0])
        rowid, sub, sci, ref, parsed, obj_id = winner
        new_paths = {}
        for path_str, (d, _, tag) in zip((sub, sci, ref), parsed):
            new_path = str(d / f'{obj_id}_{tag}.fits')
            renames[path_str] = new_path
            new_paths[tag] = new_path
        row_updates.append((rowid, new_paths['sub'], new_paths['sci'], new_paths['ref']))

    print(f"Plan: drop {len(drop_rowids)} duplicate rows, "
          f"update {len(row_updates)} rows, rename up to {len(renames)} files.")

    if not args.apply:
        print("\nDry run — re-run with --apply to commit.")
        return

    renamed = skipped_absent = skipped_clash = 0
    for old, new in renames.items():
        if old == new:
            continue
        old_p, new_p = Path(old), Path(new)
        if not old_p.exists():
            skipped_absent += 1
            continue
        if new_p.exists():
            old_p.unlink()
            skipped_clash += 1
            continue
        old_p.rename(new_p)
        renamed += 1
    print(f"Files: {renamed} renamed, {skipped_absent} missing, {skipped_clash} already existed.")

    if drop_rowids:
        db.executemany(
            "DELETE FROM classifications WHERE rowid=?",
            [(r,) for r in drop_rowids],
        )
    for rowid, sub_new, sci_new, ref_new in row_updates:
        db.execute(
            "UPDATE classifications SET sub_path=?, sci_path=?, ref_path=? WHERE rowid=?",
            (sub_new, sci_new, ref_new, rowid),
        )
    db.commit()
    db.close()
    client.close()
    print("Done.")


if __name__ == '__main__':
    main()
