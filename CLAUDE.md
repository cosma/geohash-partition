# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

The project uses uv; don't use pip.

```bash
uv sync --extra dev                  # create .venv with pytest
uv run pytest                        # all tests
uv run pytest tests/test_partitioner.py::test_orphan_pass_counts_touching_sides   # one test
uv run pytest -k fill_gaps           # tests matching a keyword

# the same quality checks CI runs
uv run --only-group quality ruff check .
uv run --only-group quality ruff format --check .
uv run --group quality mypy          # files come from [tool.mypy] in pyproject.toml

# the CLI on the bundled synthetic Berlin sample
uv run geohash-partition build -i examples/sample.csv -o examples/output \
  --min-area-weight 2000 --max-area-weight 4000 --max-grids-per-area 60
uv run geohash-partition view -i examples/output/areas.json
```

- Releases: `uv version --bump patch|minor|major`, commit, then push a `vX.Y.Z` tag. Pushing the tag
  runs `.github/workflows/release.yml`, which checks the tag against `uv version --short`, builds,
  smoke-tests the wheel and sdist, and publishes with PyPI trusted publishing (environment `pypi`).
  The version is defined only in `pyproject.toml`; `geohash_partition.__version__` reads it from
  installed metadata, so don't hard-code it again.
- `uv run python examples/make_sample.py` regenerates `examples/sample.csv` (deterministic seed).
- `uv run python docs/make_geohash_figure.py` regenerates `docs/images/geohash-grid.svg`.
- The README's precision comparison table and `docs/images/areas-map-precision-*.jpg` come from
  running `build` on the sample at precision 6 and 5 with the limits above. Update them when
  algorithm output changes.

CI (`.github/workflows/python-package.yml`) runs tests on Python 3.9, 3.10, 3.11 and 3.14 and the
quality job on 3.14. `astral-sh/setup-uv` is pinned by commit SHA because that action publishes no
floating major tags, so `@v10` does not resolve.

## Constraints

- **Zero runtime dependencies.** All geometry is plain math: haversine in `grid.py`, geohash
  encoding and neighbours in `geohash.py`, outlines and ray-cast point-in-polygon in `outline.py`.
  Don't add shapely, geopandas, numpy, folium or similar. pandas DataFrames are accepted by duck
  typing and never imported.
- **Python 3.9 support.** Modules use `from __future__ import annotations`. Ruff's UP006, UP007,
  UP035 and UP045 stay disabled until 3.9 is dropped. mypy is only installed on 3.10+ through an
  environment marker in the `quality` dependency group.
- **The partitioning rules are deliberate.** Ask before changing the semantics of seeding, growth,
  acceptance, the orphan rule or gap filling. Leftover grids outside areas are acceptable: areas
  must not grow outward beyond what the orphan pass attaches.
- **Data stays synthetic.** Tests, examples and docs use generated data such as the Berlin sample;
  don't add real third-party datasets.
- Markdown is excluded from Ruff so README examples keep their hand alignment.

## Architecture

`Partitioner.partition()` in `geohash_partition/partitioner.py` runs the whole pipeline over two
dicts: `pool` (free grids by geohash) and `assigned` (geohash to `Area`).

1. **Load** (`io.py`). `iter_rows` normalises a CSV path, DataFrame, list of dicts, mapping or
   pairs into `(geohash, weight)`; `aggregate` truncates geohashes to `precision` and sums weights.
   CSV files are read by position (exactly two columns, header optional); DataFrames and dicts use
   `geohash_column` / `weight_column`. Empty, NaN or infinite weights raise `InputError` naming the
   row.
2. **Seed and grow** (`_seed_and_grow`, `area.py`). Grids are tried as seeds heaviest first.
   `Area.grow` adds the free 4-neighbour with the smallest mean haversine distance to the area,
   caching running distance sums in `_candidates`. Growth only reads the pool; grids are claimed
   when the area is accepted (`weight >= min_area_weight`). An area's id is its seed geohash. The
   last grid added may overshoot `max_area_weight` because the limit is checked before adding.
3. **Orphan pass** (`_absorb_orphans`, `greediness` passes). A free grid is attached when areas
   touch it on two or more of its sides. Sides are counted, so one area can count twice or three
   times (a corner or a bay). It joins the lightest touching area; within a pass grids are handled
   heaviest first.
4. **Gap filling** (`_fill_gaps`). Gaps are the holes in the outline of all areas combined, built
   with `polygons_from_boxes(..., connect_diagonal=True)` so a hole touching the outside only at a
   corner still counts. `cells_in_box` plus `point_in_ring` find the cells inside each hole ring.
   `_split_gap` assigns them from the gap's edge inward so areas stay 4-connected, using
   `_choose_area`: grids with weight go to the lightest touching area, empty cells to the area
   sharing the most edges. Cells without an input row become `Grid(..., empty=True)` with weight 0,
   and stats such as `grouped_grids` exclude them.

Invariants checked by `check_invariants` in `tests/test_partitioner.py`: areas are 4-connected, a
geohash belongs to at most one area, seeds appear in non-increasing weight order, and each area's
id equals its seed.

`outline.py` builds polygons by cancelling box edges shared by two grids and chaining the remaining
edges into rings. At pinch vertices, `connect_diagonal=False` (used for GeoJSON output) keeps
corner-touching boxes apart and `connect_diagonal=True` (used for gap detection) joins them.
Geohash bounding boxes come from interval halving, so their edges are exact floats and shared edges
cancel bit-for-bit; keep that property when touching `geohash.bbox`.

Outputs live on `PartitionResult`: `to_geojson` (via `geojson.py`: RFC 7946 winding plus simplestyle
`fill` / `stroke` properties so geojson.io colours areas), `to_dict` / `save_json`, `save_csv` and
`save_map`. `leaflet_map.py` keeps the entire HTML and JavaScript page in the `_TEMPLATE` string and
embeds the data as JSON with `</` escaped. Leaflet 1.9.4 loads from jsDelivr with pinned SRI hashes.
OpenStreetMap tiles require a Referer header, so with `tiles="auto"` the page switches to OpenTopoMap
when opened from `file://`. `build_payload` accepts a live result, a saved result dict or a bare
GeoJSON FeatureCollection, which is what the `view` command relies on.

`cli.py` exposes `geohash-partition build` (writes `<name>.geojson`, `<name>.json` and
`<name>-map.html`) and `geohash-partition view`.

Tests build synthetic geohash blocks with `block()` and `uniform_block()` from `tests/conftest.py`,
starting at geohash `u4pruy`; test modules import them as `tests.conftest`.
