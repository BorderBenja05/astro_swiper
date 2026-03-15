# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Astro Swiper is a Python web application for interactive classification of astronomical FITS image triplets. Users view science/difference/reference image triplets in a browser and classify them via keyboard shortcuts.

## Installation & Running

```bash
# Install (editable / development)
pip install -e .

# Run via CLI entry point (registered as 'asswiper' in pyproject.toml)
asswiper                              # uses config.yaml in cwd, falls back to bundled default
asswiper /path/to/fits/dir            # pass input_dir positionally
asswiper -config my_cfg.yaml          # explicit config path
asswiper --print-config               # print path to bundled default_config.yaml template

# Or as a Python import
from astro_swiper import AstroSwiper
AstroSwiper('config.yaml').run()

# Open in browser: http://localhost:5000
# Over SSH: ssh -L 5000:localhost:5000 user@host
```

## Package Structure

```
astro_swiper/          # installable package
├── __init__.py        # re-exports AstroSwiper
├── web.py             # Flask-SocketIO server + embedded HTML/JS UI + AstroSwiper class
├── classifier.py      # TripletClassifier: FITS I/O, rendering, key handling
├── storage.py         # StorageBackend ABC + SQLite/CSV/Txt implementations
├── _cli.py            # CLI entry point (astro-swiper command)
└── imgs/
    └── background.png
pyproject.toml         # build config, dependencies, entry points
setup.py               # minimal shim for legacy tools
```

## Architecture

Three-module design with clear separation of concerns:

- **`astro_swiper/web.py`** — Flask-SocketIO server + embedded HTML/JS UI. Defines the `AstroSwiper` public API class. Handles HTTP routes and WebSocket events (`connect`, `keypress`).

- **`astro_swiper/classifier.py`** — `TripletClassifier` class. Loads FITS triplets using astropy's Z-scale normalization, renders them with matplotlib to base64 PNG, handles all keyboard events, manages navigation, and prefetches the next image in a daemon thread. Uses `threading.Lock` to protect shared state.

- **`astro_swiper/storage.py`** — Pluggable storage via `StorageBackend` abstract base class. Three backends: `SQLiteBackend` (recommended), `CSVBackend`, `TxtBackend` (legacy). `make_backend()` factory instantiates from config.

## Data Flow

```
Browser keypress → WebSocket 'keypress' → classifier.handle_key()
  → if classification: save to storage, load next triplet
  → if undo (back_button): revert last save
  → if Shift+arrow: adjust vmin/vmax, re-render
  → render matplotlib PNG → base64 → WebSocket 'update' → browser
```

## Configuration

`config.yaml` keys:
- `input_dir` — directory with `.fits` / `.fits.gz` triplet files
- `back_button` — key for undo (default: `up`)
- `port` — server port (default: `5000`)
- `resume` — skip already-classified on startup (default: `true`)
- `overwrite` — wipe all classifications and restart (default: `false`)
- `storage.backend` — `sqlite`, `csv`, or `txt`
- `keybinds` — map of key → label string (or file path for `txt` backend)

Config can be a YAML file path, an inline dict, or omitted when using a custom `triplet_loader`.

## Custom Triplet Loaders

Override the default `*scicutout / *subcutout / *refcutout` file discovery by passing a `triplet_loader` function to `AstroSwiper`. It receives `input_dir` (or `None`) and returns `[[sub_path, sci_path, ref_path], ...]`.

## Storage Backends

- **SQLite** — `classifications` table with columns `sci_path` (UNIQUE), `sub_path`, `ref_path`, `label`. Query with pandas via `pd.read_sql(...)`.
- **CSV** — columns `sub_path, sci_path, ref_path, label`. Append-only; full rewrite on undo.
- **Txt** — legacy multi-file format; keybind values must be file paths; one `.txt` per label.

## Input Data Format

Each triplet is three co-registered FITS cutouts sharing a basename in a flat directory:
```
<basename>scicutout.fits[.gz]
<basename>subcutout.fits[.gz]
<basename>refcutout.fits[.gz]
```
