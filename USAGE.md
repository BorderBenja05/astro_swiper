# Astro Swiper — Usage

## Installation

```bash
pip install flask flask-socketio astropy matplotlib numpy pyyaml
```

---

## Running

### 1. As a Python import (recommended)

```python
from astro_swiper_web import AstroSwiper

AstroSwiper('config.yaml').run()
```

### 2. With a custom triplet loader

If your files don't follow the default `*scicutout / *subcutout / *refcutout` naming convention, provide a `triplet_loader` function. It receives `input_dir` from the config (or `None` if omitted) and must return a list of `[sub_path, sci_path, ref_path]` triplets.

```python
from astro_swiper_web import AstroSwiper

def my_loader(input_dir):
    # build and return your triplets however you like
    import glob, re
    sci_files = sorted(glob.glob(f"{input_dir}/*_science.fits"))
    triplets = []
    for sci in sci_files:
        base = re.sub(r'_science\.fits$', '', sci)
        sub  = base + '_difference.fits'
        ref  = base + '_template.fits'
        if os.path.exists(sub) and os.path.exists(ref):
            triplets.append([sub, sci, ref])
    return triplets

AstroSwiper('config.yaml', triplet_loader=my_loader).run()
```

`input_dir` becomes optional in config when a loader is supplied — you can omit it entirely if your loader doesn't need it.

### 4. With an inline config dict (no file needed)

```python
from astro_swiper_web import AstroSwiper

AstroSwiper({
    'input_dir': '/data/cutouts/',
    'back_button': 'up',
    'port': 5000,
    'resume': True,
    'overwrite': False,
    'storage': {'backend': 'sqlite', 'db': 'classifications.db'},
    'keybinds': {
        'a': 'noise',
        'e': 'streaks',
        'd': 'dots',
        '1': 'small',
        '2': 'medium',
    },
}).run()
```

### 5. From the command line

```bash
python astro_swiper_web.py              # uses config.yaml in current directory
python astro_swiper_web.py my_cfg.yaml  # explicit config path
```

Then open **http://localhost:5000** in a browser.

**Over SSH** (no X11 needed):
```bash
ssh -L 5000:localhost:5000 user@host
# then open http://localhost:5000 locally
```

---

## config.yaml reference

| Key | Default | Description |
|-----|---------|-------------|
| `input_dir` | *(required)* | Directory containing `.fits` or `.fits.gz` cutout triplets |
| `back_button` | `left` | Key that undoes the last classification |
| `port` | `5000` | Port the web server listens on |
| `resume` | `true` | Skip already-classified triplets on startup |
| `overwrite` | `false` | Wipe all saved classifications and start fresh |
| `storage.backend` | `sqlite` | Storage format: `sqlite`, `csv`, or `txt` |
| `keybinds` | *(required)* | Map of key → label (or file path for `txt` backend) |

---

## Storage backends

### SQLite (recommended)

```yaml
storage:
  backend: sqlite
  db: training_sets/classifications.db
```

Single file, atomic writes, safe against crashes. Query results with pandas:

```python
import sqlite3, pandas as pd
df = pd.read_sql(
    "SELECT * FROM classifications",
    sqlite3.connect("training_sets/classifications.db")
)
counts = df['label'].value_counts()
```

### CSV

```yaml
storage:
  backend: csv
  file: training_sets/classifications.csv
```

One row per triplet with columns `sub_path, sci_path, ref_path, label`. Easy to open in Excel or pandas:

```python
import pandas as pd
df = pd.read_csv("training_sets/classifications.csv")
```

### Txt (legacy)

```yaml
storage:
  backend: txt
  already_classified: training_sets/already_classified.txt
```

One `.txt` file per category; keybind values must be **file paths** (not labels):

```yaml
keybinds:
  a: training_sets/noise.txt
  c: training_sets/skips.txt
  ...
```

Each file contains triplet paths, three lines per entry (sub, sci, ref).

---

## Input data format

Each triplet is a set of three co-registered FITS cutout files sharing a common basename:

```
<basename>scicutout.fits[.gz]
<basename>subcutout.fits[.gz]
<basename>refcutout.fits[.gz]
```

All files must be in the same flat directory (`input_dir`). Both `.fits` and `.fits.gz` are supported.

---

## Controls

| Key | Action |
|-----|--------|
| *(configured keybinds)* | Classify current triplet |
| `back_button` (default `left`) | Undo last classification |
| `Shift+↑` | Increase contrast (narrow display window) |
| `Shift+↓` | Decrease contrast (widen display window) |
| `Shift+→` | Increase brightness (shift window up) |
| `Shift+←` | Decrease brightness (shift window down) |
