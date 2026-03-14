"""CLI entry point for astro-swiper."""

import argparse
from astro_swiper.web import AstroSwiper


def main():
    parser = argparse.ArgumentParser(
        description='Astro Swiper — web-based FITS triplet classifier'
    )
    parser.add_argument(
        'config', nargs='?', default='config.yaml',
        help='Path to YAML config file (default: config.yaml)',
    )
    AstroSwiper(parser.parse_args().config).run()
