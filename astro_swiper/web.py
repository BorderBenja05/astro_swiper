"""web.py — AstroSwiper: web-based FITS triplet classifier.

Usage as a module:
    from astro_swiper import AstroSwiper
    AstroSwiper('config.yaml').run()

Also accepts a pre-loaded dict instead of a path:
    AstroSwiper({'input_dir': '...', 'keybinds': {...}, ...}).run()
"""

import base64
import yaml
from pathlib import Path
from flask import Flask, render_template_string, request, send_file
from flask_socketio import SocketIO, emit

from astro_swiper.storage import make_backend
from astro_swiper.classifier import TripletClassifier

# ---------------------------------------------------------------------------
# Browser UI
# ---------------------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Astro Swiper</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" rel="stylesheet">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #111 url('/background') center top / cover no-repeat fixed;
           color: #eee; font-family: monospace;
           display: flex; flex-direction: column; align-items: center;
           padding: 40px 10px 10px; min-height: 100vh; }
    #status   { font-size: 1.1em; margin-bottom: 3px; min-height: 1.4em; }
    #progress { font-size: 0.85em; color: #888; margin-bottom: 6px; min-height: 1.2em; }
    #triplet-img { max-width: 100%; max-height: 78vh; object-fit: contain;
                   background: #000; display: block; }
    #spinner  { display: none; font-size: 0.9em; color: #666; margin: 4px; }
    #keybinds { display: flex; flex-wrap: wrap; justify-content: center;
                gap: 5px; margin-top: 8px; font-size: 1.1em; }
    .kb       { background: #1e1e1e; border: 1px solid #444;
                padding: 4px 12px; border-radius: 4px; }
    .kb b     { color: #7af; }
    #hint     { font-size: 0.95em; color: #fff; margin-top: 8px; }
    #photo-credit { position: fixed; bottom: 6px; right: 10px; font-size: 0.6em;
                    color: #444; text-decoration: none; }
    #title    { font-family: 'Press Start 2P', monospace; font-size: 64pt;
                line-height: 1; margin-bottom: 12px; }
    #gallery  { margin-top: 80px; width: 100%; max-width: 1400px; padding-bottom: 80px; }
    .gallery-divider { color: #444; text-align: center; margin-bottom: 40px;
                       letter-spacing: 4px; font-size: 0.85em; }
    .gallery-category { margin-bottom: 48px; }
    .gallery-category-title { color: #7af; font-size: 1.0em; letter-spacing: 3px;
                               text-transform: uppercase; margin-bottom: 12px;
                               padding-bottom: 6px; border-bottom: 1px solid #2a2a2a; }
    .gallery-row  { display: flex; flex-direction: column; gap: 8px; }
    .gallery-img  { width: 100%; border: 1px solid #222; display: block; }
  </style>
</head>
<body>
  <div id="title">Astro Swiper</div>
  <div id="status">Connecting…</div>
  <div id="progress"></div>
  <div id="spinner">Rendering…</div>
  <img id="triplet-img" src="" alt="">
  <div id="keybinds"></div>
  <div id="hint">Shift+↑↓ contrast &nbsp;|&nbsp; Shift+←→ brightness</div>
  <a id="photo-credit" href="https://www.pexels.com/photo/blue-and-purple-cosmic-sky-956999/" target="_blank">Photo by Felix Mittermeier</a>

  <div id="gallery">
    <div class="gallery-divider">── EXAMPLE GALLERY ──</div>
    <div id="gallery-content"></div>
  </div>

  <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
  <script>
    const socket   = io();
    const imgEl    = document.getElementById('triplet-img');
    const statusEl = document.getElementById('status');
    const progEl   = document.getElementById('progress');
    const spinEl   = document.getElementById('spinner');
    const kbEl     = document.getElementById('keybinds');

    socket.on('connect',    () => { statusEl.textContent = 'Connected — loading…'; });
    socket.on('disconnect', () => { statusEl.textContent = 'Disconnected.'; });
    socket.on('loading',    () => { spinEl.style.display = 'block'; });

    socket.on('update', d => {
      imgEl.src = 'data:image/png;base64,' + d.image;
      statusEl.textContent  = d.filename;
      progEl.textContent    = d.progress;
      spinEl.style.display  = 'none';
    });

    socket.on('done', d => {
      statusEl.textContent = '✓ ' + d.message;
      imgEl.src = ''; progEl.textContent = '';
      spinEl.style.display = 'none';
    });

    const arrowGlyph = {left:'←', right:'→', up:'↑', down:'↓'};
    const pretty = k => arrowGlyph[k] ?? k;

    socket.on('keybinds', list => {
      kbEl.innerHTML =
        list.map(([k, n]) => `<div class="kb"><b>${pretty(k)}</b> ${n}</div>`).join('');
    });

    document.addEventListener('keydown', e => {
      if (['ArrowLeft','ArrowRight','ArrowUp','ArrowDown',' '].includes(e.key))
        e.preventDefault();
      const arrows = {ArrowLeft:'left', ArrowRight:'right', ArrowUp:'up', ArrowDown:'down'};
      let key = arrows[e.key] ?? e.key;
      if (e.shiftKey && ['left','right','up','down'].includes(key)) key = 'shift+' + key;
      socket.emit('keypress', {key});
    });

    (function() {
      const labels = ['noise', 'dots', 'streaks', 'badsubs', 'dipoles'];
      const container = document.getElementById('gallery-content');
      labels.forEach(label => {
        const cat = document.createElement('div');
        cat.className = 'gallery-category';
        const title = document.createElement('div');
        title.className = 'gallery-category-title';
        title.textContent = label;
        const row = document.createElement('div');
        row.className = 'gallery-row';
        cat.appendChild(title);
        cat.appendChild(row);
        container.appendChild(cat);
        let errored = 0;
        for (let i = 0; i < 5; i++) {
          const img = document.createElement('img');
          img.className = 'gallery-img';
          img.src = '/example/' + label + '/' + i;
          img.onerror = function() {
            this.style.display = 'none';
            if (++errored === 5) cat.style.display = 'none';
          };
          row.appendChild(img);
        }
      });
    })();
  </script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class AstroSwiper:
    """
    Web-based FITS triplet classifier.

    Usage:
        from astro_swiper import AstroSwiper
        AstroSwiper('config.yaml').run()

    Also accepts a pre-loaded dict instead of a path:
        AstroSwiper({'input_dir': '...', 'keybinds': {...}, ...}).run()

    To use a custom triplet loader instead of the built-in filename scanner,
    pass a callable that accepts input_dir (may be None) and returns a list of
    [sub_path, sci_path, ref_path] triplets:

        def my_loader(input_dir):
            return [[sub, sci, ref], ...]

        AstroSwiper('config.yaml', triplet_loader=my_loader).run()

    When a triplet_loader is provided, input_dir in config is optional and is
    passed to the loader as-is (you may ignore it if not needed).
    """

    def __init__(self, config, triplet_loader=None):
        if isinstance(config, (str, Path)):
            with open(config) as f:
                cfg = yaml.safe_load(f)
        else:
            cfg = dict(config)

        input_dir = cfg.get('input_dir')
        if input_dir is None and triplet_loader is None:
            raise ValueError("config must include 'input_dir' when no triplet_loader is provided")

        self._port = cfg.get('port', 5000)
        self._app  = Flask(__name__)
        self._app.config['SECRET_KEY'] = 'astro_swiper'
        self._sio  = SocketIO(self._app, async_mode='threading', cors_allowed_origins='*')

        keybinds = {str(k): str(v) for k, v in cfg['keybinds'].items()}

        self._classifier = TripletClassifier(
            keybinds=keybinds,
            back_button=cfg.get('back_button', 'left'),
            storage=make_backend(cfg, keybinds),
            socketio=self._sio,
            resume=cfg.get('resume', True),
            overwrite=cfg.get('overwrite', False),
        )
        self._classifier.load_directory(input_dir, triplet_loader=triplet_loader)
        self._register_routes()
        self._generate_examples()

    def _register_routes(self):
        app = self._app
        sio = self._sio
        clf = self._classifier

        @app.route('/')
        def index_page():
            return render_template_string(HTML)

        @app.route('/background')
        def background():
            return send_file(
                Path(__file__).parent / 'imgs' / 'background.png',
                mimetype='image/png',
            )

        @app.route('/example/<label>/<int:n>')
        def serve_example(label, n):
            p = Path(__file__).parent / 'imgs' / 'examples' / f'{label}_{n}.png'
            if not p.exists():
                return ('Not found', 404)
            return send_file(p, mimetype='image/png')

        @sio.on('connect')
        def on_connect():
            kb_list = [
                (k, Path(v).stem)
                for k, v in clf.keybinds.items()
            ]
            kb_list.append((clf.back_button, 'back'))
            emit('keybinds', kb_list)
            clf.send_current(to=request.sid)

        @sio.on('keypress')
        def on_keypress(data):
            clf.handle_key(data.get('key', ''))

    def _generate_examples(self, labels=('noise', 'dots', 'streaks', 'badsubs', 'dipoles')):
        storage = self._classifier._storage
        if not hasattr(storage, 'get_examples'):
            return
        examples_dir = Path(__file__).parent / 'imgs' / 'examples'
        examples_dir.mkdir(exist_ok=True)
        clf = self._classifier
        for label in labels:
            triplets = storage.get_examples(label, n=5)
            for i, triplet in enumerate(triplets):
                out_path = examples_dir / f'{label}_{i}.png'
                if out_path.exists():
                    continue
                try:
                    imgs = clf._load_triplet(triplet)
                    out_path.write_bytes(base64.b64decode(clf._render(imgs)))
                except Exception as e:
                    print(f"Warning: could not render example {label}/{i}: {e}")
        print("Example gallery ready.")

    def run(self):
        print(f"Open http://localhost:{self._port} in your browser")
        self._sio.run(
            self._app, host='127.0.0.1', port=self._port,
            debug=False, use_reloader=False, allow_unsafe_werkzeug=True,
        )
