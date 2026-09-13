"""The GeohashPartition pipeline: load → seed & grow → absorb orphans → fill holes → result.

All geometry is plain math: haversine for distances, ray casting for
point-in-polygon, and edge cancellation for outlines. No spatial libraries.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from .area import Area
from .geohash import cells_in_box, center
from .geojson import area_feature, feature_collection, leftover_feature
from .grid import Grid, Number
from .io import Source, aggregate, iter_rows, write_assignments_csv, write_json
from .outline import Ring, point_in_ring, polygons_from_boxes
from .style import weight_range

Logger = Callable[[str], None]

SEED_ORDERS = ("heaviest", "lightest", "random")
OUTPUT_FORMATS = ("geojson", "json", "csv", "map")


class ConfigError(ValueError):
    """Raised for invalid parameter combinations."""


@dataclass(frozen=True)
class PartitionConfig:
    """All knobs that influence how areas are formed.

    Core constraints
    ----------------
    min_area_weight
        An area whose total weight ends below this is rejected and its grids
        are released back to the pool.
    max_area_weight
        Growth stops once the area's weight reaches this value. The last grid
        added may push the area slightly above it (the check happens before
        each addition, never after).
    max_grids_per_area
        Hard cap on the number of grids in one area during growth.
    precision
        Geohash length grids are truncated to. Rows sharing the same truncated
        geohash have their weights summed.
    greediness
        Number of orphan-absorption passes run after seeding. In each pass every
        free grid that areas touch on two or more of its sides is handed to the
        lightest of them. Sides are counted, so a grid in a corner or bay of a
        single area qualifies too. ``0`` disables the pass.

    Extra knobs
    -----------
    max_areas
        Stop seeding after this many areas (``None`` = unlimited).
    max_failures
        Stop seeding after this many *consecutive* rejected seeds.
    fill_holes
        Close every gap enclosed by areas, so no area is left with holes. A gap
        inside one area joins that area. A gap between areas is split among its
        neighbours: grids carrying weight go to the lightest neighbour, empty
        cells to the neighbour they share most edges with. Cells with no input
        row join as zero-weight grids flagged ``empty``. Grids outside the
        areas that the orphan pass did not attach stay leftover.
    seed_order
        ``"heaviest"`` (default), ``"lightest"`` or ``"random"``: the order in
        which grids are tried as seeds.
    random_seed
        Seed for ``"random"`` ordering so runs are reproducible.
    geohash_column / weight_column
        Column names (or dict keys) used for pandas DataFrames and lists of
        dicts. CSV files ignore them: they are read by position, geohash in
        the first column and weight in the second.
    """

    min_area_weight: Number
    max_area_weight: Number
    max_grids_per_area: int = 100
    precision: int = 6
    greediness: int = 2
    max_areas: Optional[int] = None
    max_failures: int = 100
    fill_holes: bool = True
    seed_order: str = "heaviest"
    random_seed: Optional[int] = None
    geohash_column: str = "geohash"
    weight_column: str = "weight"

    def __post_init__(self) -> None:
        if self.min_area_weight < 0:
            raise ConfigError("min_area_weight must be >= 0")
        if self.max_area_weight <= 0:
            raise ConfigError("max_area_weight must be > 0")
        if self.min_area_weight > self.max_area_weight:
            raise ConfigError("min_area_weight cannot exceed max_area_weight")
        if self.max_grids_per_area < 1:
            raise ConfigError("max_grids_per_area must be >= 1")
        if not 1 <= self.precision <= 12:
            raise ConfigError("precision must be between 1 and 12")
        if self.greediness < 0:
            raise ConfigError("greediness must be >= 0")
        if self.max_areas is not None and self.max_areas < 1:
            raise ConfigError("max_areas must be >= 1 or None")
        if self.max_failures < 1:
            raise ConfigError("max_failures must be >= 1")
        if self.seed_order not in SEED_ORDERS:
            raise ConfigError(f"seed_order must be one of {SEED_ORDERS}, got {self.seed_order!r}")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PartitionResult:
    """Outcome of a run: the areas, the grids left over, and run statistics."""

    areas: List[Area]
    leftover: List[Grid]
    stats: Dict[str, object]
    config: PartitionConfig
    grids: Dict[str, Grid] = field(default_factory=dict, repr=False)

    # -- convenience ---------------------------------------------------------

    @property
    def area_count(self) -> int:
        return len(self.areas)

    def assignments(self) -> List[Tuple[str, str, Number]]:
        """``(geohash, area_id, weight)`` for every grid; area_id is ``""`` for leftovers."""
        rows: List[Tuple[str, str, Number]] = []
        for area in self.areas:
            rows.extend((grid.id, area.id, grid.weight) for grid in area.grids)
        rows.extend((grid.id, "", grid.weight) for grid in self.leftover)
        return rows

    # -- conversions ---------------------------------------------------------

    def to_dict(self, include_geometry: bool = True) -> dict:
        return {
            "config": self.config.to_dict(),
            "stats": dict(self.stats),
            "areas": [area.to_dict(include_geometry=include_geometry) for area in self.areas],
            "leftover": [grid.to_dict() for grid in self.leftover],
        }

    def to_geojson(self, include_leftover: bool = False) -> dict:
        """A FeatureCollection ready for geojson.io, QGIS, Leaflet, Mapbox, ..."""
        low, high = weight_range(area.weight for area in self.areas)
        features = [
            area_feature(
                area.id,
                area.seed.id,
                area.weight,
                [grid.id for grid in area.grids],
                area.geometry(),
                low,
                high,
                area.empty_grid_count,
            )
            for area in self.areas
        ]
        if include_leftover:
            features.extend(leftover_feature(grid.id, grid.weight) for grid in self.leftover)
        return feature_collection(features)

    # -- files ---------------------------------------------------------------

    def save_json(self, path: str, include_geometry: bool = True) -> str:
        write_json(self.to_dict(include_geometry=include_geometry), path)
        return path

    def save_geojson(self, path: str, include_leftover: bool = False) -> str:
        write_json(self.to_geojson(include_leftover=include_leftover), path)
        return path

    def save_csv(self, path: str) -> str:
        write_assignments_csv(self.assignments(), path)
        return path

    def save_map(
        self,
        path: str,
        title: Optional[str] = None,
        include_leftover: bool = True,
        tiles: str = "auto",
        tiles_attribution: Optional[str] = None,
    ) -> str:
        """Write a static interactive Leaflet map (single HTML file).

        ``tiles="auto"`` uses OpenStreetMap, switching to OpenTopoMap when the
        file is opened from disk. Pass a preset name or a tile URL template
        (with ``tiles_attribution``) to choose another base map.
        """
        from .leaflet_map import save_map

        return save_map(
            self, path, title=title, include_leftover=include_leftover, tiles=tiles, tiles_attribution=tiles_attribution
        )

    def save(
        self,
        directory: str,
        name: str = "areas",
        formats: Iterable[str] = ("geojson", "json", "map"),
        include_leftover: bool = False,
        title: Optional[str] = None,
        tiles: str = "auto",
        tiles_attribution: Optional[str] = None,
    ) -> Dict[str, str]:
        """Write several outputs at once; returns ``{format: path}``.

        ``geojson`` → ``<name>.geojson``, ``json`` → ``<name>.json``,
        ``csv`` → ``<name>-assignments.csv``, ``map`` → ``<name>-map.html``.
        """
        chosen = list(dict.fromkeys(formats))
        unknown = [fmt for fmt in chosen if fmt not in OUTPUT_FORMATS]
        if unknown:
            raise ValueError(f"unknown output format(s) {unknown}; choose from {OUTPUT_FORMATS}")
        os.makedirs(directory, exist_ok=True)
        paths: Dict[str, str] = {}
        if "geojson" in chosen:
            paths["geojson"] = self.save_geojson(os.path.join(directory, f"{name}.geojson"), include_leftover)
        if "json" in chosen:
            paths["json"] = self.save_json(os.path.join(directory, f"{name}.json"))
        if "csv" in chosen:
            paths["csv"] = self.save_csv(os.path.join(directory, f"{name}-assignments.csv"))
        if "map" in chosen:
            paths["map"] = self.save_map(
                os.path.join(directory, f"{name}-map.html"),
                title=title,
                tiles=tiles,
                tiles_attribution=tiles_attribution,
            )
        return paths


class Partitioner:
    """Assemble geohash grids into connected, weight-balanced areas.

    Example::

        from geohash_partition import Partitioner

        result = Partitioner(min_area_weight=3000, max_area_weight=6000).partition("data.csv")
        result.save("out/")  # out/areas.geojson, out/areas.json, out/areas-map.html
    """

    def __init__(self, config: Optional[PartitionConfig] = None, **kwargs) -> None:
        if config is not None and kwargs:
            raise ConfigError("pass either a PartitionConfig or keyword arguments, not both")
        self.config = config if config is not None else PartitionConfig(**kwargs)

    # -- public --------------------------------------------------------------

    def partition(self, source: Source, log: Optional[Logger] = None) -> PartitionResult:
        """Run the full pipeline on ``source`` and return a :class:`PartitionResult`."""
        emit = log or (lambda message: None)
        config = self.config
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc)

        rows = iter_rows(source, config.geohash_column, config.weight_column)
        weights, row_count = aggregate(rows, config.precision)
        grids = {grid_id: Grid(grid_id, weight) for grid_id, weight in weights.items()}
        total_weight = sum(weights.values())
        emit(f"Loaded {row_count} rows -> {len(grids)} grids at precision {config.precision}")

        pool: Dict[str, Grid] = dict(grids)
        assigned: Dict[str, Area] = {}

        areas, rejected = self._seed_and_grow(pool, assigned, emit)
        absorbed = self._absorb_orphans(areas, pool, assigned, emit)
        filled, empty_filled = self._fill_gaps(areas, pool, assigned, emit) if config.fill_holes else (0, 0)

        leftover = sorted(pool.values(), key=lambda grid: (-grid.weight, grid.id))
        grouped_grids = sum(1 for area in areas for grid in area.grids if not grid.empty)
        grouped_weight = sum(area.weight for area in areas)
        duration = time.perf_counter() - started
        stats: Dict[str, object] = {
            "input_rows": row_count,
            "total_grids": len(grids),
            "grouped_grids": grouped_grids,
            "leftover_grids": len(leftover),
            "total_areas": len(areas),
            "rejected_seeds": rejected,
            "absorbed_grids": absorbed,
            "filled_grids": filled,
            "empty_grids_filled": empty_filled,
            "total_weight": total_weight,
            "grouped_weight": grouped_weight,
            "area_average_weight": (grouped_weight / len(areas)) if areas else 0,
            "area_average_grids": (sum(area.grid_count for area in areas) / len(areas)) if areas else 0,
            "started_at": started_at.isoformat(timespec="seconds"),
            "duration_seconds": round(duration, 3),
        }
        emit(
            f"Done in {duration:.1f}s: {len(areas)} areas, "
            f"{grouped_grids}/{len(grids)} grids grouped, {len(leftover)} left over"
        )
        return PartitionResult(areas=areas, leftover=leftover, stats=stats, config=config, grids=grids)

    # -- stages --------------------------------------------------------------

    def _ordered_seeds(self, pool: Dict[str, Grid]) -> List[Grid]:
        config = self.config
        grids = list(pool.values())
        if config.seed_order == "heaviest":
            grids.sort(key=lambda grid: (-grid.weight, grid.id))
        elif config.seed_order == "lightest":
            grids.sort(key=lambda grid: (grid.weight, grid.id))
        else:
            grids.sort(key=lambda grid: grid.id)
            random.Random(config.random_seed).shuffle(grids)
        return grids

    def _seed_and_grow(self, pool: Dict[str, Grid], assigned: Dict[str, Area], emit: Logger) -> Tuple[List[Area], int]:
        config = self.config
        areas: List[Area] = []
        rejected = 0
        consecutive_failures = 0
        emit(f"1/3 Building areas from {len(pool)} grids")
        for seed in self._ordered_seeds(pool):
            if seed.id not in pool:
                continue  # already taken by an earlier area
            if config.max_areas is not None and len(areas) >= config.max_areas:
                emit(f"    reached max_areas={config.max_areas}")
                break
            area = self._grow_area(seed, pool)
            if area.weight < config.min_area_weight:
                rejected += 1
                consecutive_failures += 1
                if consecutive_failures >= config.max_failures:
                    emit(f"    stopped after {consecutive_failures} consecutive rejected seeds")
                    break
                continue
            consecutive_failures = 0
            areas.append(area)
            for grid in area.grids:
                del pool[grid.id]
                assigned[grid.id] = area
        emit(f"    {len(areas)} areas formed, {rejected} seeds rejected")
        return areas, rejected

    def _grow_area(self, seed: Grid, pool: Dict[str, Grid]) -> Area:
        """Grow an area from ``seed``. The pool is only read; grids are claimed on acceptance."""
        config = self.config
        area = Area(seed)
        while area.needs_expansion(config.max_grids_per_area, config.max_area_weight):
            if area.grow(pool) is None:
                break
        area.release_growth_cache()
        return area

    def _absorb_orphans(self, areas: List[Area], pool: Dict[str, Grid], assigned: Dict[str, Area], emit: Logger) -> int:
        config = self.config
        emit(f"2/3 Absorbing orphan grids ({config.greediness} passes)")
        absorbed = 0
        for _ in range(config.greediness):
            # Every grid of an area lists each free neighbour once per touching
            # side, so the same area can appear several times for one grid
            # (a corner counts 2, a bay counts 3).
            touching: Dict[str, List[Area]] = {}
            for area in areas:
                for member in area.grids:
                    for grid_id in member.neighbors:
                        if grid_id in pool:
                            touching.setdefault(grid_id, []).append(area)
            orphans = [grid_id for grid_id, owners in touching.items() if len(owners) >= 2]
            if not orphans:
                break
            orphans.sort(key=lambda grid_id: (-pool[grid_id].weight, grid_id))
            for grid_id in orphans:
                grid = pool.pop(grid_id)
                lightest = min(touching[grid_id], key=lambda area: (area.weight, area.id))
                lightest.add(grid)
                assigned[grid_id] = lightest
                absorbed += 1
        emit(f"    {absorbed} grids absorbed")
        return absorbed

    def _fill_gaps(
        self, areas: List[Area], pool: Dict[str, Grid], assigned: Dict[str, Area], emit: Logger
    ) -> Tuple[int, int]:
        """Close every gap enclosed by areas.

        A gap is a hole in the outline of the union of all areas: cells with no
        input row, or leftover grids, surrounded on every side by areas. Gap
        cells are found by ray casting their centers against each hole ring.
        Each connected gap is then handed to the areas around it, cell by cell
        from its edges inward, so every area stays 4-connected.

        Returns ``(leftover_grids_filled, empty_grids_filled)``.
        """
        emit("3/3 Filling gaps inside and between areas")
        gap_ids = self._gap_cells(areas, assigned)
        cells: Dict[str, Grid] = {
            grid_id: pool.pop(grid_id) if grid_id in pool else Grid(grid_id, 0, empty=True) for grid_id in gap_ids
        }
        filled_data = filled_empty = 0
        for component in _components(gap_ids, cells):
            for grid_id in _split_gap(component, cells, assigned):
                grid = cells[grid_id]  # defensive: an unreachable cell returns to the pool
                if not grid.empty:
                    pool[grid_id] = grid
            for grid_id in component:
                if grid_id in assigned:
                    if cells[grid_id].empty:
                        filled_empty += 1
                    else:
                        filled_data += 1
        emit(f"    {filled_data + filled_empty} gap grids filled ({filled_data} with data, {filled_empty} empty)")
        return filled_data, filled_empty

    def _gap_cells(self, areas: List[Area], assigned: Dict[str, Area]) -> Set[str]:
        """Cells not in any area whose center lies inside a hole of the union of all areas."""
        precision = self.config.precision
        polygons = polygons_from_boxes((grid.bbox for area in areas for grid in area.grids), connect_diagonal=True)
        gaps: Set[str] = set()
        for polygon in polygons:
            for hole in polygon[1:]:
                min_lon, min_lat, max_lon, max_lat = _ring_bounds(hole)
                for cell in cells_in_box(min_lat, min_lon, max_lat, max_lon, precision):
                    if cell in assigned or cell in gaps:
                        continue
                    lat, lon = center(cell)
                    if point_in_ring((lon, lat), hole):
                        gaps.add(cell)
        return gaps


def _ring_bounds(ring: Ring) -> Tuple[float, float, float, float]:
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _components(ids: Set[str], cells: Dict[str, Grid]) -> List[List[str]]:
    """4-connected components of ``ids``, in a deterministic order."""
    seen: Set[str] = set()
    components: List[List[str]] = []
    for start in sorted(ids):
        if start in seen:
            continue
        seen.add(start)
        stack, component = [start], []
        while stack:
            grid_id = stack.pop()
            component.append(grid_id)
            for neighbor_id in cells[grid_id].neighbors:
                if neighbor_id in ids and neighbor_id not in seen:
                    seen.add(neighbor_id)
                    stack.append(neighbor_id)
        components.append(component)
    return components


def _choose_area(grid: Grid, touching: Dict[Area, int]) -> Area:
    """Pick the area a free grid joins, given the areas it touches and on how many sides.

    A grid carrying weight joins the lightest area, keeping weights balanced.
    An empty cell cannot change any weight, so it joins the area it shares
    most edges with, lightest on a tie, which keeps shapes compact.
    """
    if grid.weight > 0:
        return min(touching, key=lambda area: (area.weight, area.id))
    return min(touching, key=lambda area: (-touching[area], area.weight, area.id))


def _split_gap(component: List[str], cells: Dict[str, Grid], assigned: Dict[str, Area]) -> List[str]:
    """Hand one gap to the areas around it, keeping weights balanced and areas connected.

    Only cells touching an area can be placed, so placement grows inward from
    the gap's edges. Cells carrying weight are placed first, heaviest first,
    each going to the lightest area it touches. Empty cells cannot change any
    weight, so each goes to the area it shares most edges with (lightest on a
    tie), which keeps shapes compact. Returns ids that could not be placed.
    """
    remaining = set(component)
    while remaining:
        best = None
        for grid_id in remaining:
            grid = cells[grid_id]
            touching: Dict[Area, int] = {}
            for neighbor_id in grid.neighbors:
                area = assigned.get(neighbor_id)
                if area is not None:
                    touching[area] = touching.get(area, 0) + 1
            if not touching:
                continue
            target = _choose_area(grid, touching)
            rank = (0, -grid.weight, grid.id) if grid.weight > 0 else (1, -touching[target], grid.id)
            if best is None or rank < best[0]:
                best = (rank, grid, target)
        if best is None:
            break
        _, grid, target = best
        remaining.discard(grid.id)
        target.add(grid)
        assigned[grid.id] = target
    return sorted(remaining)


def partition(source: Source, log: Optional[Logger] = None, **kwargs) -> PartitionResult:
    """Shorthand for ``Partitioner(**kwargs).partition(source)``."""
    return Partitioner(**kwargs).partition(source, log=log)
