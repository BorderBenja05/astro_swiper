"""mongo.py — MongoDB triplet loader and storage backend for astro_swiper.

Three document formats are supported:

Path-based (default):
    { "sci_path": "/data/abc_sci.fits", "sub_path": "...", "ref_path": "...", "label": null }

Embedded binary (use_embedded: true) — FITS bytes stored directly in the document:
    { "cutoutScience": <binary>, "cutoutDifference": <binary>, "cutoutTemplate": <binary> }
    Files are written to temp_dir on first load.  By default paths are keyed by
    the Mongo `_id`, but set `object_id_field` (and optionally `object_id_lookup`
    to pull the field from another collection) so that every alert for the same
    astronomical object shares one cache path — classifying one then skips the
    rest on resume.

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
      sample_size:  500            # uses $sample; set 0 to fetch all (slow on large collections)
      # label_field omitted → no MongoDB-side filtering; SQLite resume handles it

      # Resume by objectId instead of per-alert _id.  If the cutouts collection
      # already has the objectId inline, set `object_id_field` alone.  If it
      # lives in a sibling alerts collection (e.g. ZTF_alerts), point
      # `object_id_lookup` at it to $lookup + flatten it onto each cutout doc.
      object_id_field:  objectId
      object_id_lookup:
        from:          ZTF_alerts
        local_field:   _id
        foreign_field: _id

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
        self._label_field    = cfg.get('label_field')   # None → no MongoDB filter
        self._sci_field      = cfg.get('sci_field',  'sci_path')
        self._sub_field      = cfg.get('sub_field',  'sub_path')
        self._ref_field      = cfg.get('ref_field',  'ref_path')
        self._use_gridfs     = cfg.get('use_gridfs',   False)
        self._use_embedded   = cfg.get('use_embedded', False)
        self._extra_query    = cfg.get('query',        {})
        self._sample_size    = cfg.get('sample_size',  500)
        self._object_id_field  = cfg.get('object_id_field')   # None → key cache by _id
        self._object_id_lookup = cfg.get('object_id_lookup')  # {from, local_field, foreign_field}
        self._cheat_real       = cfg.get('cheat_real', False)
        self._cheat_fake       = cfg.get('cheat_fake', False)
        if self._cheat_real and self._cheat_fake:
            raise ValueError("cheat_real and cheat_fake are mutually exclusive.")
        if (self._cheat_real or self._cheat_fake) and not self._object_id_lookup:
            raise ValueError(
                "cheat_real / cheat_fake need mongo.object_id_lookup set so "
                "they can filter by the joined alert's candidate.rb / candidate.drb."
            )

        self._client = pm.MongoClient(uri)
        self._col    = self._client[cfg['database']][cfg['collection']]

        # Populated by __call__: sci_path → {'fwhm': ..., 'drb': ..., 'rb': ...}
        self.metadata: dict = {}

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

        cheating = self._cheat_real or self._cheat_fake
        if cheating:
            docs = self._fetch_cheat(query)
        else:
            pipeline = [{'$match': query}]
            if self._sample_size:
                pipeline.append({'$sample': {'size': self._sample_size}})
            if self._object_id_lookup:
                pipeline.extend(self._lookup_stages())

            if pipeline != [{'$match': query}]:
                docs = list(self._col.aggregate(pipeline))
            else:
                docs = list(self._col.find(query))

        if self._object_id_field:
            docs = self._dedup_by_object_id(docs)
        if cheating and self._sample_size:
            docs = docs[: self._sample_size]

        if self._use_embedded:
            triplets = [self._resolve_embedded(doc) for doc in docs]
        elif self._use_gridfs:
            triplets = [self._resolve_gridfs(doc) for doc in docs]
        else:
            triplets = [
                [doc[self._sub_field], doc[self._sci_field], doc[self._ref_field]]
                for doc in docs
            ]

        for triplet, doc in zip(triplets, docs):
            meta = {
                'fwhm':            doc.get('_alert_fwhm'),
                'drb':             doc.get('_alert_drb'),
                'rb':              doc.get('_alert_rb'),
                'rock':            doc.get('_alert_rock'),
                'star':            doc.get('_alert_star'),
                'near_brightstar': doc.get('_alert_near_brightstar'),
                'stationary':      doc.get('_alert_stationary'),
            }
            if any(v is not None for v in meta.values()):
                self.metadata[triplet[1]] = meta
        return triplets

    def _lookup_stages(self) -> list:
        """Pipeline stages that join object_id_field in from a sibling collection.

        Used in the non-cheat path: after $sample has already cut the set down
        to a manageable size, so running $lookup per-doc is cheap.
        """
        lk = self._object_id_lookup
        joined = '_object_id_join'
        return [
            {'$lookup': {
                'from':         lk['from'],
                'localField':   lk.get('local_field',   '_id'),
                'foreignField': lk.get('foreign_field', '_id'),
                'pipeline':     [{'$project': {
                    self._object_id_field:        1,
                    'candidate.fwhm':             1,
                    'candidate.drb':              1,
                    'candidate.rb':               1,
                    'properties.rock':            1,
                    'properties.star':            1,
                    'properties.near_brightstar': 1,
                    'properties.stationary':      1,
                }}],
                'as':           joined,
            }},
            {'$addFields': {
                self._object_id_field: {
                    '$ifNull': [
                        {'$arrayElemAt': [f'${joined}.{self._object_id_field}', 0]},
                        f'${self._object_id_field}',
                    ],
                },
                '_alert_fwhm':            {'$arrayElemAt': [f'${joined}.candidate.fwhm',             0]},
                '_alert_drb':             {'$arrayElemAt': [f'${joined}.candidate.drb',              0]},
                '_alert_rb':              {'$arrayElemAt': [f'${joined}.candidate.rb',               0]},
                '_alert_rock':            {'$arrayElemAt': [f'${joined}.properties.rock',            0]},
                '_alert_star':            {'$arrayElemAt': [f'${joined}.properties.star',            0]},
                '_alert_near_brightstar': {'$arrayElemAt': [f'${joined}.properties.near_brightstar', 0]},
                '_alert_stationary':      {'$arrayElemAt': [f'${joined}.properties.stationary',      0]},
            }},
            {'$project': {joined: 0}},
        ]

    def _fetch_cheat(self, query: dict) -> list:
        """Cheat-mode fast path: pre-query the alerts collection for matching
        rb/drb, then fetch just those cutouts by _id.  Avoids a per-document
        $lookup against the (enormous) cutouts collection."""
        lk = self._object_id_lookup
        if not self._object_id_field:
            raise ValueError("cheat mode requires mongo.object_id_field to be set.")

        alerts = self._col.database[lk['from']]
        cheat_match = (
            {'candidate.rb': {'$gt': 0.9}, 'candidate.drb': {'$gt': 0.9}}
            if self._cheat_real
            else {'candidate.rb': {'$lt': 0.1}, 'candidate.drb': {'$lt': 0.1}}
        )
        criteria = 'rb>0.9, drb>0.9' if self._cheat_real else 'rb<0.4, drb<0.4'
        # $sample BEFORE $match — WiredTiger's random cursor samples fast with
        # no index, whereas $match on unindexed candidate.rb/drb would collscan
        # the full alerts collection.  Loop sampling until we have enough
        # unique objectIds (or hit MAX_ROUNDS) so rare cheat criteria still
        # yield a full batch.
        target         = self._sample_size or 500
        pool_per_round = max(target * 40, 20000)
        MAX_ROUNDS     = 10

        print(f"Cheat mode: filtering ZTF_alerts to {criteria}, "
              f"target {target} unique objects.", flush=True)

        id_to_obj, id_to_cand, seen_obj = {}, {}, set()
        for rnd in range(1, MAX_ROUNDS + 1):
            alert_pipeline = [
                {'$sample': {'size': pool_per_round}},
                {'$match': cheat_match},
                {'$project': {
                    '_id':                        1,
                    self._object_id_field:        1,
                    'candidate.fwhm':             1,
                    'candidate.drb':              1,
                    'candidate.rb':               1,
                    'properties.rock':            1,
                    'properties.star':            1,
                    'properties.near_brightstar': 1,
                    'properties.stationary':      1,
                }},
            ]
            round_hits = 0
            for a in alerts.aggregate(alert_pipeline, allowDiskUse=True):
                oid = a.get(self._object_id_field)
                round_hits += 1
                if oid in seen_obj:
                    continue
                if oid is not None:
                    seen_obj.add(oid)
                id_to_obj[a['_id']] = oid
                cand = a.get('candidate')  or {}
                prop = a.get('properties') or {}
                id_to_cand[a['_id']] = {
                    'fwhm':            cand.get('fwhm'),
                    'drb':             cand.get('drb'),
                    'rb':              cand.get('rb'),
                    'rock':            prop.get('rock'),
                    'star':            prop.get('star'),
                    'near_brightstar': prop.get('near_brightstar'),
                    'stationary':      prop.get('stationary'),
                }
            print(f"  round {rnd}: sampled {pool_per_round}, "
                  f"{round_hits} matched filter, {len(seen_obj)} unique objects so far.",
                  flush=True)
            if len(seen_obj) >= target:
                break

        if not id_to_obj:
            print("Cheat mode: no alerts matched the filter.", flush=True)
            return []

        cutout_query = dict(query)
        cutout_query['_id'] = {'$in': list(id_to_obj.keys())}
        docs = list(self._col.find(cutout_query))
        for doc in docs:
            doc[self._object_id_field] = id_to_obj.get(doc['_id'])
            cand = id_to_cand.get(doc['_id'], {})
            doc['_alert_fwhm']            = cand.get('fwhm')
            doc['_alert_drb']             = cand.get('drb')
            doc['_alert_rb']              = cand.get('rb')
            doc['_alert_rock']            = cand.get('rock')
            doc['_alert_star']            = cand.get('star')
            doc['_alert_near_brightstar'] = cand.get('near_brightstar')
            doc['_alert_stationary']      = cand.get('stationary')
        print(f"Cheat mode: fetched {len(docs)} cutouts for "
              f"{len(seen_obj)} unique objectIds.", flush=True)
        return docs

    def _dedup_by_object_id(self, docs) -> list:
        seen, out = set(), []
        for doc in docs:
            oid = doc.get(self._object_id_field)
            if oid is None:
                out.append(doc)
                continue
            if oid in seen:
                continue
            seen.add(oid)
            out.append(doc)
        return out

    def _cache_key(self, doc) -> str:
        """Stable filename stem for cache files — objectId if configured, else _id."""
        if self._object_id_field:
            oid = doc.get(self._object_id_field)
            if oid is not None:
                return str(oid)
        return str(doc['_id'])

    def _resolve_embedded(self, doc) -> list:
        """Write embedded FITS bytes to cache files; return stable local paths."""
        key   = self._cache_key(doc)
        paths = []
        for field, tag in [
            (self._sub_field, 'sub'),
            (self._sci_field, 'sci'),
            (self._ref_field, 'ref'),
        ]:
            local_path = self._cache_dir / f'{key}_{tag}.fits'
            if not local_path.exists():
                local_path.write_bytes(bytes(doc[field]))
            paths.append(str(local_path))
        return paths

    def _resolve_gridfs(self, doc) -> list:
        """Download GridFS FITS files to the cache dir; return local paths."""
        key   = self._cache_key(doc)
        paths = []
        for field, tag in [
            (self._sub_field, 'sub'),
            (self._sci_field, 'sci'),
            (self._ref_field, 'ref'),
        ]:
            file_id    = doc[field]
            local_path = self._cache_dir / f'{key}_{tag}.fits'
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
