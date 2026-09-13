"""Command line interface: ``geohash-partition build`` and ``geohash-partition view``."""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from . import __version__
from .io import InputError
from .leaflet_map import load, save_map
from .partitioner import ConfigError, PartitionConfig, Partitioner


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geohash-partition",
        description="Assemble geohash grids into connected, weight-balanced areas.",
    )
    parser.add_argument("--version", action="version", version=f"geohash-partition {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser(
        "build",
        help="form areas from a two-column CSV of geohash,weight rows",
        description="Form areas and write <name>.geojson, <name>.json and <name>-map.html to the output directory.",
    )
    build.add_argument(
        "-i", "--input", required=True, help="CSV with two columns: geohash, then weight (header optional)"
    )
    build.add_argument("-o", "--output-dir", default=".", help="directory for the outputs (default: current)")
    build.add_argument("--name", default="areas", help="base file name for the outputs (default: areas)")
    build.add_argument("--min-area-weight", type=float, required=True, help="reject areas lighter than this")
    build.add_argument("--max-area-weight", type=float, required=True, help="stop growing an area at this weight")
    build.add_argument("--max-grids-per-area", type=int, default=100, help="cap on grids per area (default 100)")
    build.add_argument("--precision", type=int, default=6, help="geohash precision to work at (default 6)")
    build.add_argument("--greediness", type=int, default=2, help="orphan-absorption passes (default 2)")
    build.add_argument("--max-areas", type=int, default=None, help="stop after this many areas")
    build.add_argument("--max-failures", type=int, default=100, help="consecutive rejected seeds before stopping")
    build.add_argument("--no-fill-holes", action="store_true", help="leave gaps enclosed by areas unfilled")
    build.add_argument("--seed-order", choices=("heaviest", "lightest", "random"), default="heaviest")
    build.add_argument("--random-seed", type=int, default=None, help="seed for --seed-order random")
    build.add_argument("--include-leftover", action="store_true", help="add leftover grids to the GeoJSON file")
    build.add_argument("--csv", action="store_true", help="also write <name>-assignments.csv (geohash,area_id,weight)")
    build.add_argument("--no-json", action="store_true", help="skip <name>.json")
    build.add_argument("--no-map", action="store_true", help="skip <name>-map.html")
    build.add_argument("--title", default=None, help="title shown on the map")
    build.add_argument(
        "--tiles",
        default="auto",
        help="base map: auto (OpenStreetMap; OpenTopoMap when the HTML is opened from disk), osm, opentopomap, or a tile URL template with {z}/{x}/{y}",
    )
    build.add_argument("--tiles-attribution", default=None, help="attribution HTML, required with a custom tile URL")
    build.add_argument("-q", "--quiet", action="store_true", help="suppress progress messages")

    view = commands.add_parser(
        "view",
        help="render the Leaflet HTML map from a saved .json or .geojson",
        description="Render a static interactive Leaflet map from a saved result (.json) or FeatureCollection (.geojson).",
    )
    view.add_argument("-i", "--input", required=True, help="<name>.json or <name>.geojson")
    view.add_argument("-o", "--output", default=None, help="HTML file to write (default: <input>-map.html)")
    view.add_argument("--title", default=None, help="title shown on the map")
    view.add_argument("--no-leftover", action="store_true", help="do not draw leftover grids")
    view.add_argument(
        "--tiles",
        default="auto",
        help="base map: auto (OpenStreetMap; OpenTopoMap when the HTML is opened from disk), osm, opentopomap, or a tile URL template with {z}/{x}/{y}",
    )
    view.add_argument("--tiles-attribution", default=None, help="attribution HTML, required with a custom tile URL")
    return parser


def _integral(value: float):
    return int(value) if float(value).is_integer() else value


def _run_build(args: argparse.Namespace) -> int:
    log = (lambda message: None) if args.quiet else (lambda message: print(message, file=sys.stderr))
    try:
        config = PartitionConfig(
            min_area_weight=_integral(args.min_area_weight),
            max_area_weight=_integral(args.max_area_weight),
            max_grids_per_area=args.max_grids_per_area,
            precision=args.precision,
            greediness=args.greediness,
            max_areas=args.max_areas,
            max_failures=args.max_failures,
            fill_holes=not args.no_fill_holes,
            seed_order=args.seed_order,
            random_seed=args.random_seed,
        )
        result = Partitioner(config).partition(args.input, log=log)
    except (ConfigError, InputError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    formats = ["geojson"]
    if not args.no_json:
        formats.append("json")
    if args.csv:
        formats.append("csv")
    if not args.no_map:
        formats.append("map")
    try:
        paths = result.save(
            args.output_dir,
            name=args.name,
            formats=formats,
            include_leftover=args.include_leftover,
            title=args.title,
            tiles=args.tiles,
            tiles_attribution=args.tiles_attribution,
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    labels = {
        "geojson": "GeoJSON (open in geojson.io)",
        "json": "Full result",
        "csv": "Assignments",
        "map": "Leaflet map",
    }
    for fmt, path in paths.items():
        log(f"{labels[fmt]}: {path}")
    return 0


def _run_view(args: argparse.Namespace) -> int:
    try:
        data = load(args.input)
        output = args.output or f"{os.path.splitext(args.input)[0]}-map.html"
        save_map(
            data,
            output,
            title=args.title,
            include_leftover=not args.no_leftover,
            tiles=args.tiles,
            tiles_attribution=args.tiles_attribution,
        )
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"Leaflet map: {output}", file=sys.stderr)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "build":
        return _run_build(args)
    return _run_view(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
