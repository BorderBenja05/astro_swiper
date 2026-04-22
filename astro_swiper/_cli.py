"""CLI entry point for astro-swiper."""

import sys
import argparse
from pathlib import Path

import yaml

from astro_swiper.web import AstroSwiper

DEFAULT_CONFIG = Path(__file__).parent / 'default_config.yaml'


def _deep_merge(base, override):
    """Recursively merge override into base; override wins on conflicts."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


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
        '--obs', default=None, metavar='NAME',
        help='Observatory to classify (e.g. lsst, ztf). Merges observatories.<NAME> from config.',
    )
    parser.add_argument(
        '--print-config', action='store_true',
        help='Print the path to the bundled default config template and exit',
    )
    cheat = parser.add_mutually_exclusive_group()
    cheat.add_argument(
        '-cheat_real', action='store_true',
        help='Only sample alerts with candidate.rb > 0.9 and candidate.drb > 0.9 '
             '(requires mongo.object_id_lookup pointing at the alerts collection).',
    )
    cheat.add_argument(
        '-cheat_fake', action='store_true',
        help='Only sample alerts with candidate.rb < 0.4 and candidate.drb < 0.4 '
             '(requires mongo.object_id_lookup pointing at the alerts collection).',
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

    if args.obs is not None:
        obs_cfgs = cfg.get('observatories', {})
        if args.obs not in obs_cfgs:
            available = list(obs_cfgs) or ['(none defined)']
            print(f"Error: observatory '{args.obs}' not found in config. "
                  f"Available: {available}", file=sys.stderr)
            sys.exit(1)
        cfg = _deep_merge(cfg, obs_cfgs[args.obs])
        cfg['observatory'] = args.obs.upper()

    if args.input_dir is not None:
        cfg['input_dir'] = str(Path(args.input_dir).resolve())

    if args.cheat_real:
        cfg.setdefault('mongo', {})['cheat_real'] = True
    if args.cheat_fake:
        cfg.setdefault('mongo', {})['cheat_fake'] = True

    AstroSwiper(cfg).run()
