# Astro Swiper

Web-based interactive classifier for astronomical FITS image triplets. View science/difference/reference image triplets in a browser and classify them via keyboard shortcuts.

## Installation

```bash
pip install astro-swiper
```

---

## Running

### 1. From the command line

```bash
aswiper /path/to/fits/triplets/          # positional input dir, uses config.yaml in cwd
aswiper /path/to/fits/triplets/ -config my_cfg.yaml  # explicit config path
aswiper --print-config                   # print path to the bundled default config template
```

Then open **http://localhost:5000** in a browser.

**Over SSH** (no X11 needed):
```bash
ssh -L 5000:localhost:5000 user@host
# then open http://localhost:5000 locally
```

### 2. As a Python import

```python
from astro_swiper import AstroSwiper

AstroSwiper('config.yaml').run()
```

### 3. With an inline config dict (no file needed)

```python
from astro_swiper import AstroSwiper

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

### 4. With a custom triplet loader

If your files don't follow the default `*scicutout / *subcutout / *refcutout` naming convention, provide a `triplet_loader` function. It receives `input_dir` from the config (or `None` if omitted) and must return a list of `[sub_path, sci_path, ref_path]` triplets.

```python
from astro_swiper import AstroSwiper

def my_loader(input_dir):
    from pathlib import Path
    triplets = []
    for sci in sorted(Path(input_dir).glob('*_science.fits')):
        base = str(sci).removesuffix('_science.fits')
        sub, ref = base + '_difference.fits', base + '_template.fits'
        if Path(sub).exists() and Path(ref).exists():
            triplets.append([sub, str(sci), ref])
    return triplets

AstroSwiper('config.yaml', triplet_loader=my_loader).run()
```

`input_dir` is optional in config when a loader is supplied.

---

## Configuration

Get a copy of the default config to use as a starting point:

```bash
aswiper --print-config
cp $(aswiper --print-config) config.yaml
```

### config.yaml reference

| Key | Default | Description |
|-----|---------|-------------|
| `input_dir` | *(required)* | Directory containing `.fits` or `.fits.gz` cutout triplets. Can be overridden by the CLI positional argument. |
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

Single file, atomic writes, safe against crashes. Query with pandas:

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

One row per triplet with columns `sub_path, sci_path, ref_path, label`.

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
```

Each file contains triplet paths, three lines per entry (sub, sci, ref).

---

## Input data format

Each triplet is three co-registered FITS cutout files sharing a common basename in a flat directory:

```
<basename>scicutout.fits[.gz]
<basename>subcutout.fits[.gz]
<basename>refcutout.fits[.gz]
```

Both `.fits` and `.fits.gz` are supported.

---

## Controls

| Key | Action |
|-----|--------|
| *(configured keybinds)* | Classify current triplet |
| `back_button` (default `left`) | Undo last classification |
| `Shift+↑` | Increase contrast (narrow display range) |
| `Shift+↓` | Decrease contrast (widen display range) |
| `Shift+→` | Increase brightness (shift range up) |
| `Shift+←` | Decrease brightness (shift range down) |
