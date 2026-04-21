"""mongo.py — MongoDB triplet loader and storage backend for astro_swiper.

Three document formats are supported:

Path-based (default):
    { "sci_path": "/data/abc_sci.fits", "sub_path": "...", "ref_path": "...", "label": null }

Embedded binary (use_embedded: true) — FITS bytes stored directly in the document:
    { "cutoutScience": <binary>, "cutoutDifference": <binary>, "cutoutTemplate": <binary> }
    Files are written to temp_dir on first load, keyed by ObjectId so the paths
    are stable across restarts (resume tracking via SQLite works correctly).

GridFS-based (use_gridfs: true) — fields hold GridFS ObjectIds:
    { "sci_file_id": ObjectId("..."), "sub_file_id": ObjectId("..."), ... }

label_field controls MongoDB-side filtering: only documents where label_field is
null are returned.  Set label_field to null/~ in config to disable this filter
and rely entirely on the SQLite resume logic (required for read-only connections).

Example config.yaml (LSST embedded binary, read-only connection):

    mongo:
      uri:          "mongodb://user:pass@host:port/db?authSource=db"
      database:     boom
      collection:   LSST_alerts_cutouts
      sci_field:    cutoutScience
      sub_field:    cutoutDifference
      ref_field:    cutoutTemplate
      use_embedded: true
      temp_dir:     /tmp/astro_swiper_cache
      # label_field omitted → no MongoDB-side filtering; SQLite resume handles it

    storage:
      backend: sqlite
      db: training_sets/classifications.db
"""

import tempfile
from collections import deque
from pathlib import Path

from .storage import StorageBackend


def _pymongo():
    try:
        import pymongo
        return pymongo
    except ImportError:
        raise ImportError(
            "pymongo is required for MongoDB support.  "
            "Install it with:  pip install 'astro-swiper[mongo]'"
        )


class MongoTripletLoader:
    """Load FITS triplets from a MongoDB collection.

    Acts as a triplet_loader callable: accepts input_dir (ignored) and returns
    [[sub_path, sci_path, ref_path], ...].

    If label_field is set, only documents where that field is null are returned.
    Leave label_field unset (null in YAML) for read-only connections — the
    existing resume/SQLite logic will skip already-classified triplets instead.
    """

    def __init__(self, cfg: dict):
        pm = _pymongo()
        uri = cfg.get('uri', 'mongodb://localhost:27017')
        self._label_field  = cfg.get('label_field')   # None → no MongoDB filter
        self._sci_field    = cfg.get('sci_field',  'sci_path')
        self._sub_field    = cfg.get('sub_field',  'sub_path')
        self._ref_field    = cfg.get('ref_field',  'ref_path')
        self._use_gridfs   = cfg.get('use_gridfs',   False)
        self._use_embedded = cfg.get('use_embedded', False)
        self._extra_query  = cfg.get('query',        {})

        self._client = pm.MongoClient(uri)
        self._col    = self._client[cfg['database']][cfg['collection']]

        if self._use_gridfs or self._use_embedded:
            cache_root      = cfg.get('temp_dir') or tempfile.mkdtemp(prefix='astro_swiper_')
            self._cache_dir = Path(cache_root)
            self._cache_dir.mkdir(parents=True, exist_ok=True)

        if self._use_gridfs:
            import gridfs
            self._gfs = gridfs.GridFS(self._client[cfg['database']])

    def __call__(self, input_dir) -> list:
        """Return [[sub_path, sci_path, ref_path], ...] for matching documents."""
        query = dict(self._extra_query)
        if self._label_field is not None:
            query[self._label_field] = None
        docs = list(self._col.find(query))

        if self._use_embedded:
            return [self._resolve_embedded(doc) for doc in docs]
        if self._use_gridfs:
            return [self._resolve_gridfs(doc) for doc in docs]
        return [
            [doc[self._sub_field], doc[self._sci_field], doc[self._ref_field]]
            for doc in docs
        ]

    def _resolve_embedded(self, doc) -> list:
        """Write embedded FITS bytes to cache files; return stable local paths."""
        obj_id = str(doc['_id'])
        paths  = []
        for field, tag in [
            (self._sub_field, 'sub'),
            (self._sci_field, 'sci'),
            (self._ref_field, 'ref'),
        ]:
            local_path = self._cache_dir / f'{obj_id}_{tag}.fits'
            if not local_path.exists():
                local_path.write_bytes(bytes(doc[field]))
            paths.append(str(local_path))
        return paths

    def _resolve_gridfs(self, doc) -> list:
        """Download GridFS FITS files to the cache dir; return local paths."""
        paths = []
        for field, tag in [
            (self._sub_field, 'sub'),
            (self._sci_field, 'sci'),
            (self._ref_field, 'ref'),
        ]:
            file_id    = doc[field]
            local_path = self._cache_dir / f'{file_id}_{tag}.fits'
            if not local_path.exists():
                grid_out = self._gfs.get(file_id)
                local_path.write_bytes(grid_out.read())
            paths.append(str(local_path))
        return paths

    def close(self):
        self._client.close()


class MongoBackend(StorageBackend):
    """Store triplet classifications in a MongoDB collection.

    Works best alongside MongoTripletLoader pointing at the same collection:
    save() sets label_field on the document matched by sci_field.

    Supports get_examples() so the example gallery in the UI is populated.
    """

    def __init__(self, cfg: dict):
        pm  = _pymongo()
        uri = cfg.get('uri', 'mongodb://localhost:27017')
        self._label_field = cfg.get('label_field', 'label')
        self._sci_field   = cfg.get('sci_field',   'sci_path')
        self._sub_field   = cfg.get('sub_field',   'sub_path')
        self._ref_field   = cfg.get('ref_field',   'ref_path')

        self._client  = pm.MongoClient(uri)
        self._col     = self._client[cfg['database']][cfg['collection']]
        self._col.create_index(self._sci_field, unique=True)
        self._history = deque()

    def get_classified(self) -> set:
        docs = self._col.find(
            {self._label_field: {'$nin': [None, '']}},
            {self._sci_field: 1},
        )
        return {doc[self._sci_field] for doc in docs}

    def save(self, sub, sci, ref, key, label):
        self._col.update_one(
            {self._sci_field: sci},
            {'$set': {
                self._sub_field:   sub,
                self._ref_field:   ref,
                self._label_field: label,
            }},
            upsert=True,
        )
        self._history.append(sci)

    def undo(self) -> 'str | None':
        if not self._history:
            return None
        sci = self._history.pop()
        self._col.update_one(
            {self._sci_field: sci},
            {'$set': {self._label_field: None}},
        )
        return sci

    def clear(self):
        self._col.update_many({}, {'$set': {self._label_field: None}})
        self._history.clear()

    def close(self):
        self._client.close()

    def get_examples(self, label, n=5) -> list:
        docs = list(self._col.find(
            {self._label_field: label},
            {self._sci_field: 1, self._sub_field: 1, self._ref_field: 1},
        ).limit(n))
        return [
            [doc[self._sub_field], doc[self._sci_field], doc[self._ref_field]]
            for doc in docs
        ]
