"""CLI entry point for astro-swiper."""

import sys
import argparse
from pathlib import Path

import yaml

from astro_swiper.web import AstroSwiper

DEFAULT_CONFIG = Path(__file__).parent / 'default_config.yaml'


def main():
    parser = argparse.ArgumentParser(
        description='Astro Swiper — web-based FITS triplet classifier'
    )
    parser.add_argument(
        'input_dir', nargs='?', default=None,
        help='Path to directory containing FITS triplets',
    )
    parser.add_argument(
        '-config', default='config.yaml', metavar='PATH',
        help='Path to YAML config file (default: config.yaml in cwd)',
    )
    parser.add_argument(
        '--print-config', action='store_true',
        help='Print the path to the bundled default config template and exit',
    )

    args = parser.parse_args()

    if args.print_config:
        print(DEFAULT_CONFIG)
        sys.exit(0)

    config_path = Path(args.config)
    if not config_path.exists():
        config_path = DEFAULT_CONFIG

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    if args.input_dir is not None:
        cfg['input_dir'] = str(Path(args.input_dir).resolve())

    AstroSwiper(cfg).run()
