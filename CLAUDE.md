# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Astro Swiper is a Python web application for interactive classification of astronomical FITS image triplets. Users view science/difference/reference image triplets in a browser and classify them via keyboard shortcuts.

## Running the Application

```bash
# Install dependencies
pip install flask flask-socketio astropy matplotlib numpy pyyaml

# Run with default config.yaml
python astro_swiper_web.py

# Run with explicit config path
python astro_swiper_web.py my_cfg.yaml

# Open in browser
# http://localhost:5000
# Over SSH: ssh -L 5000:localhost:5000 user@host
```

## Architecture

Three-module design with clear separation of concerns:

- **`astro_swiper_web.py`** — Flask-SocketIO server + embedded HTML/JS UI. Defines the `AstroSwiper` public API class. Handles HTTP routes and WebSocket events (`connect`, `keypress`). Entry point for CLI usage.

- **`classifier.py`** — `TripletClassifier` class. Loads FITS triplets using astropy's Z-scale normalization, renders them with matplotlib to base64 PNG, handles all keyboard events, manages navigation, and prefetches the next image in a daemon thread. Uses `threading.Lock` to protect shared state.

- **`storage.py`** — Pluggable storage via `StorageBackend` abstract base class. Three backends: `SQLiteBackend` (recommended), `CSVBackend`, `TxtBackend` (legacy). `make_backend()` factory instantiates from config.

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
- `back_button` — key for undo (default: `left`)
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
