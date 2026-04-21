"""mongo.py — MongoDB triplet loader and storage backend for astro_swiper.

Document format (path-based, default):
    {
        "sci_path": "/data/abc_scicutout.fits",
        "sub_path": "/data/abc_subcutout.fits",
        "ref_path": "/data/abc_refcutout.fits",
        "label":    null            # null = unlabeled
    }

Document format (GridFS-based, use_gridfs: true):
    {
        "sci_file_id": ObjectId("..."),   # GridFS file IDs
        "sub_file_id": ObjectId("..."),
        "ref_file_id": ObjectId("..."),
        "label":       null
    }

Example config.yaml:

    mongo:
      uri:        mongodb://localhost:27017
      database:   astro
      collection: triplets
      label_field: label       # field checked/set for classification status
      sci_field:  sci_path     # field holding the science image path or GridFS ID
      sub_field:  sub_path
      ref_field:  ref_path
      use_gridfs: false        # set true when fields hold GridFS ObjectIds
      temp_dir:   /tmp/astro   # local cache dir for GridFS downloads

    storage:
      backend: mongo           # use MongoBackend for saving classifications
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
    """Load unlabeled FITS triplets from a MongoDB collection.

    Acts as a triplet_loader callable: accepts input_dir (ignored) and returns
    [[sub_path, sci_path, ref_path], ...] for every document where label_field
    is null (or absent).

    Supports two document formats:
    - Path-based (default): fields contain filesystem paths (strings).
    - GridFS-based (use_gridfs: true): fields contain GridFS ObjectIds;
      files are downloaded to temp_dir on first access.
    """

    def __init__(self, cfg: dict):
        pm = _pymongo()
        uri = cfg.get('uri', 'mongodb://localhost:27017')
        self._label_field = cfg.get('label_field', 'label')
        self._sci_field   = cfg.get('sci_field',   'sci_path')
        self._sub_field   = cfg.get('sub_field',   'sub_path')
        self._ref_field   = cfg.get('ref_field',   'ref_path')
        self._use_gridfs  = cfg.get('use_gridfs',  False)
        self._extra_query = cfg.get('query',       {})

        self._client = pm.MongoClient(uri)
        self._col    = self._client[cfg['database']][cfg['collection']]

        if self._use_gridfs:
            import gridfs
            self._gfs       = gridfs.GridFS(self._client[cfg['database']])
            cache_root      = cfg.get('temp_dir') or tempfile.mkdtemp(prefix='astro_swiper_')
            self._cache_dir = Path(cache_root)
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    def __call__(self, input_dir) -> list:
        """Return [[sub_path, sci_path, ref_path], ...] for unlabeled documents."""
        query = {self._label_field: None, **self._extra_query}
        docs  = list(self._col.find(query))
        if self._use_gridfs:
            return [self._resolve_gridfs(doc) for doc in docs]
        return [
            [doc[self._sub_field], doc[self._sci_field], doc[self._ref_field]]
            for doc in docs
        ]

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
    unlabeled documents are loaded by the loader, and save() writes the label
    back to the same document (matched by sci_field).

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
        self._history = deque()   # ordered list of sci values for undo

    # ------------------------------------------------------------------
    # StorageBackend interface
    # ------------------------------------------------------------------

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
