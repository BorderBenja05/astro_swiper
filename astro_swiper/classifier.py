"""classifier.py — TripletClassifier: FITS loading, rendering, and key handling."""

import os, io, base64, gzip, shutil, tempfile, threading
from pathlib import Path

from tqdm import tqdm

import numpy as np
from astropy.io import fits
from astropy.visualization import ZScaleInterval
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec


class TripletClassifier:
    def __init__(self, keybinds, back_button, storage, socketio,
                 resume=True, overwrite=False):
        self.keybinds    = keybinds
        self.back_button = back_button
        self.resume      = resume
        self._storage    = storage
        self._socketio   = socketio   # injected — no module-level global needed

        self.triplets = []
        self.index    = 0
        self._lock    = threading.Lock()
        self._zscale  = ZScaleInterval()

        self.vmin     = 0.0
        self.vmax     = 1.0
        self.step_pct = 0.1

        self._imgs_idx = None
        self._imgs     = None
        self._b64      = None
        self._b64_key  = None
        self._pf_lock  = threading.Lock()
        self._pf       = None

        if overwrite:
            self._storage.clear()
        self.pre_classified = self._storage.get_classified() if resume else set()

    # ── FITS I/O ──────────────────────────────────────────────────────────────

    def _load_fits(self, path):
        path = Path(path)
        if path.suffix == '.gz':
            with gzip.open(path, 'rb') as f_in:
                with tempfile.NamedTemporaryFile(suffix='.fits', delete=False) as f_out:
                    shutil.copyfileobj(f_in, f_out)
                    tmp = Path(f_out.name)
            try:
                with fits.open(tmp) as h:
                    return np.nan_to_num(h[0].data)
            finally:
                tmp.unlink()
        with fits.open(path) as h:
            return np.nan_to_num(h[0].data)

    def _load_triplet(self, triplet):
        return tuple(self._zscale(self._load_fits(p)) for p in triplet)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render(self, imgs):
        fig = plt.figure(figsize=(21, 7), facecolor='black')
        gs  = gridspec.GridSpec(1, 3, wspace=0.02)
        for i, (title, img) in enumerate(zip(('SUB', 'SCI', 'REF'), imgs)):
            ax = fig.add_subplot(gs[i])
            ax.set_title(title, fontsize=16, color='white')
            ax.axis('off')
            ax.imshow(img, cmap='gray', origin='lower', vmin=self.vmin, vmax=self.vmax)
        plt.tight_layout(pad=0.4)
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', facecolor='black', dpi=100)
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()

    def _get_b64(self):
        idx = self.index
        if self._imgs_idx != idx:
            with self._pf_lock:
                if self._pf and self._pf[0] == idx:
                    self._imgs, self._pf = self._pf[1], None
                else:
                    self._imgs = self._load_triplet(self.triplets[idx])
            self._imgs_idx = idx
            self._b64      = None
        key = (idx, round(self.vmin, 8), round(self.vmax, 8))
        if self._b64_key != key:
            self._b64     = self._render(self._imgs)
            self._b64_key = key
        return self._b64

    # ── Prefetch ──────────────────────────────────────────────────────────────

    def _prefetch_next(self):
        nxt = self.index
        while nxt < len(self.triplets):
            if self.resume and self.triplets[nxt][1] in self.pre_classified:
                nxt += 1
            else:
                break
        if nxt >= len(self.triplets):
            return
        target, triplet = nxt, self.triplets[nxt]
        def _work():
            imgs = self._load_triplet(triplet)
            with self._pf_lock:
                self._pf = (target, imgs)
        threading.Thread(target=_work, daemon=True).start()

    # ── Navigation ────────────────────────────────────────────────────────────

    def _skip_classified(self):
        while self.index < len(self.triplets):
            if self.resume and self.triplets[self.index][1] in self.pre_classified:
                self.index += 1
            else:
                break

    # ── Emit ──────────────────────────────────────────────────────────────────

    def _emit_current(self, to=None):
        if self.index >= len(self.triplets):
            self._socketio.emit('done', {'message': f'All {len(self.triplets)} triplets done!'})
            return
        triplet = self.triplets[self.index]
        payload = {
            'image':    self._get_b64(),
            'filename': Path(triplet[1]).name,
            'progress': f'{self.index + 1} / {len(self.triplets)}',
        }
        self._socketio.emit('update', payload, to=to) if to else \
            self._socketio.emit('update', payload)

    def send_current(self, to=None):
        sid = to
        def _work():
            self._socketio.emit('loading')
            with self._lock:
                self._emit_current(to=sid)
        threading.Thread(target=_work, daemon=True).start()

    # ── Key handling ──────────────────────────────────────────────────────────

    def handle_key(self, key):
        def _work():
            with self._lock:
                if key.startswith('shift+'):
                    self._apply_scaling(key)
                    self._emit_current()
                elif key == self.back_button:
                    self._undo()
                    self._emit_current()
                elif key in self.keybinds:
                    self._classify(key)
                    self._emit_current()
                    self._prefetch_next()
        threading.Thread(target=_work, daemon=True).start()

    def _apply_scaling(self, key):
        rng  = self.vmax - self.vmin
        step = rng * self.step_pct
        if   key == 'shift+up':    self.vmax -= step
        elif key == 'shift+down':  self.vmax += step
        elif key == 'shift+right': self.vmin += step; self.vmax += step
        elif key == 'shift+left':  self.vmin -= step; self.vmax -= step
        self._b64 = None

    def _classify(self, key):
        sub, sci, ref = self.triplets[self.index]
        label = self.keybinds[key]
        self._storage.save(sub, sci, ref, key, label)
        self.pre_classified.add(sci)
        print(f"[{self.index + 1}/{len(self.triplets)}] {Path(sci).name} → {label}")
        self.index += 1
        self._skip_classified()

    def _undo(self):
        last_sci = self._storage.undo()
        if last_sci is None:
            print("Nothing to undo.")
            return
        self.pre_classified.discard(last_sci)
        for i, triplet in enumerate(self.triplets):
            if triplet[1] == last_sci:
                self.index = i
                break
        else:
            self.index = max(0, self.index - 1)
        print(f"Undid: {Path(last_sci).name}")

    # ── Setup ─────────────────────────────────────────────────────────────────

    def load_directory(self, directory_path, triplet_loader=None):
        if triplet_loader is not None:
            triplets = list(triplet_loader(directory_path))
        else:
            directory_path = Path(directory_path)
            print(f'Finding all files in {directory_path}...\n'
                  f'This may take a minute or two depending on network speed and number of files.', flush=True)
            with os.scandir(directory_path) as it:
                entries = list(it)
            names = {e.name for e in tqdm(entries, desc='Building file index') if e.is_file()}
            triplets = []
            for sci_sfx, sub_sfx, ref_sfx in [
                ('scicutout.fits.gz', 'subcutout.fits.gz', 'refcutout.fits.gz'),
                ('scicutout.fits',    'subcutout.fits',    'refcutout.fits'),
            ]:
                for name in names:
                    if name.endswith(sci_sfx):
                        base = name[:-len(sci_sfx)]
                        sub_name, ref_name = base + sub_sfx, base + ref_sfx
                        if sub_name in names and ref_name in names:
                            triplets.append([
                                str(directory_path / sub_name),
                                str(directory_path / name),
                                str(directory_path / ref_name),
                            ])
        self.triplets = sorted(triplets, key=lambda t: t[1])
        self._skip_classified()
        print(f"Loaded {len(self.triplets)} triplets; resuming at index {self.index}.")
