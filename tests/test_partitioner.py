import random
from collections import deque

import pytest

from geohash_partition import Area, ConfigError, Grid, PartitionConfig, Partitioner, partition
from geohash_partition.io import InputError
from geohash_partition.outline import polygons_from_boxes
from tests.conftest import block, uniform_block


def is_connected(area: Area) -> bool:
    ids = area.grid_ids
    seen = {area.seed.id}
    queue = deque([area.seed])
    by_id = {grid.id: grid for grid in area.grids}
    while queue:
        grid = queue.popleft()
        for neighbor_id in grid.neighbors:
            if neighbor_id in ids and neighbor_id not in seen:
                seen.add(neighbor_id)
                queue.append(by_id[neighbor_id])
    return seen == ids


def check_invariants(result, config: PartitionConfig):
    data_ids = []
    for area in result.areas:
        assert is_connected(area)
        assert area.weight >= config.min_area_weight
        assert area.weight == sum(grid.weight for grid in area.grids)
        assert all(grid.weight == 0 for grid in area.grids if grid.empty)
        data_ids.extend(grid.id for grid in area.grids if not grid.empty)
    data_ids.extend(grid.id for grid in result.leftover)
    assert len(data_ids) == len(set(data_ids)) == result.stats["total_grids"]
    # a geohash belongs to at most one area, filled empty grids included
    area_ids = [grid.id for area in result.areas for grid in area.grids]
    assert len(area_ids) == len(set(area_ids))
    assert not set(area_ids) & {grid.id for grid in result.leftover}
    # areas are founded heaviest seed first, and each area is named after its seed
    seed_weights = [area.seed.weight for area in result.areas]
    assert seed_weights == sorted(seed_weights, reverse=True)
    assert all(area.id == area.seed.id == area.grids[0].id for area in result.areas)


def make_area(cells, weight):
    area = Area(Grid(cells[0], weight))
    for cell in cells[1:]:
        area.add(Grid(cell, weight))
    return area


def owners(*areas):
    return {grid.id: area for area in areas for grid in area.grids}


def union_hole_count(areas):
    boxes = (g.bbox for a in areas for g in a.grids)
    return sum(len(polygon) - 1 for polygon in polygons_from_boxes(boxes, connect_diagonal=True))


def ring_area(size: int, skip=()):
    """An area made of the outer ring of a size x size block, minus ``skip`` positions."""
    grid = block(size, size)
    cells = [
        grid[r][c]
        for r in range(size)
        for c in range(size)
        if (r in (0, size - 1) or c in (0, size - 1)) and (r, c) not in skip
    ]
    area = Area(Grid(cells[0], 10))
    for cell in cells[1:]:
        area.add(Grid(cell, 10))
    return grid, area


def test_uniform_block_forms_balanced_areas(block10):
    partitioner = Partitioner(
        min_area_weight=50, max_area_weight=100, max_grids_per_area=10, greediness=0, fill_holes=False
    )
    result = partitioner.partition(block10)
    check_invariants(result, partitioner.config)
    assert result.area_count >= 8
    for area in result.areas:
        assert area.grid_count <= 10
        assert 50 <= area.weight <= 100


def test_full_pipeline_keeps_areas_connected(block10):
    grids = dict(block10)
    for index, cell in enumerate(sorted(grids)):
        grids[cell] = 1 + (index * 37) % 23  # uneven weights
    partitioner = Partitioner(min_area_weight=40, max_area_weight=90, greediness=3)
    check_invariants(partitioner.partition(grids), partitioner.config)


def test_max_weight_may_be_exceeded_by_last_grid_only():
    grids = uniform_block(4, 4, weight=30)
    result = partition(grids, min_area_weight=10, max_area_weight=100, greediness=0)
    for area in result.areas:
        assert area.weight - area.grids[-1].weight < 100


def test_rejected_seeds_and_max_failures():
    grids = uniform_block(3, 3, weight=1)
    result = Partitioner(min_area_weight=1000, max_area_weight=2000, max_failures=3).partition(grids)
    assert result.area_count == 0
    assert result.stats["rejected_seeds"] == 3
    assert len(result.leftover) == 9


def test_max_areas_cap(block10):
    result = partition(block10, min_area_weight=20, max_area_weight=40, max_areas=2, greediness=0, fill_holes=False)
    assert result.area_count == 2


def test_seed_order_heaviest_first():
    grids = uniform_block(3, 3, weight=1)
    heavy = block(3, 3)[1][1]
    grids[heavy] = 100
    result = partition(grids, min_area_weight=1, max_area_weight=1000, max_grids_per_area=4)
    assert result.areas[0].seed.id == heavy


def test_random_seed_is_reproducible(block10):
    kwargs = {"min_area_weight": 30, "max_area_weight": 60, "seed_order": "random", "random_seed": 7}

    def run(**overrides):
        data = partition(block10, **dict(kwargs, **overrides)).to_dict(include_geometry=False)
        data["stats"].pop("started_at")
        data["stats"].pop("duration_seconds")
        return data

    first = run()
    assert first == run()
    assert [a["seed"] for a in run(random_seed=8)["areas"]] != [a["seed"] for a in first["areas"]]


def test_precision_truncation_sums_weights():
    cell = block(1, 1)[0][0]
    rows = [(cell + "0", 3), (cell + "1", 4), (cell + "z", 5)]
    result = partition(rows, min_area_weight=1, max_area_weight=100, precision=6)
    assert result.stats["total_grids"] == 1
    assert result.areas[0].weight == 12
    with pytest.raises(InputError):
        partition(rows, min_area_weight=1, max_area_weight=100, precision=8)


def test_fill_gaps_absorbs_enclosed_data_grid():
    grid, area = ring_area(3)
    center = grid[1][1]
    pool = {center: Grid(center, 1)}
    partitioner = Partitioner(min_area_weight=1, max_area_weight=1000)
    assert partitioner._fill_gaps([area], pool, owners(area), lambda _: None) == (1, 0)
    assert center in area and not pool


def test_fill_gaps_ignores_notch_open_to_the_outside():
    # the ring is open on the east side, so the middle grid is not enclosed
    grid, area = ring_area(3, skip={(1, 2)})
    center = grid[1][1]
    pool = {center: Grid(center, 1)}
    assert Partitioner(min_area_weight=1, max_area_weight=1000)._fill_gaps(
        [area], pool, owners(area), lambda _: None
    ) == (0, 0)
    assert center in pool and area.grid_count == 7


def test_fill_gaps_fills_whole_hole_including_empty_cells():
    # 5x5 ring; of the 3x3 interior only the middle grid has data
    grid, area = ring_area(5)
    middle = grid[2][2]
    pool = {middle: Grid(middle, 4)}
    result = Partitioner(min_area_weight=1, max_area_weight=1000)._fill_gaps([area], pool, owners(area), lambda _: None)
    assert result == (1, 8)
    assert area.grid_count == 25 and area.empty_grid_count == 8 and area.weight == 160 + 4
    assert is_connected(area) and union_hole_count([area]) == 0


def test_gap_between_areas_gives_weight_to_the_lightest_neighbour():
    g = block(5, 5)
    # A: columns 0-1 plus the top of column 2; B: columns 3-4 plus the bottom of column 2
    a_cells = [g[r][c] for r in range(5) for c in (0, 1)] + [g[4][2]]
    b_cells = [g[r][c] for r in range(5) for c in (3, 4)] + [g[0][2]]
    heavy, light = make_area(a_cells, 10), make_area(b_cells, 5)
    top, middle, bottom = g[3][2], g[2][2], g[1][2]
    pool = {top: Grid(top, 8), bottom: Grid(bottom, 8)}  # middle has no data
    assigned = owners(heavy, light)
    filled = Partitioner(min_area_weight=1, max_area_weight=1000)._fill_gaps(
        [heavy, light], pool, assigned, lambda _: None
    )
    assert filled == (2, 1)
    assert top in light and bottom in light and middle in light
    assert heavy.weight == 110 and light.weight == 55 + 16
    assert is_connected(heavy) and is_connected(light)
    assert union_hole_count([heavy, light]) == 0


def test_empty_gap_cell_goes_to_area_sharing_most_edges():
    g = block(3, 3)
    a_cells = [g[0][0], g[0][1], g[0][2], g[1][0], g[2][0], g[2][1]]  # touches the center on 3 sides
    b_cells = [g[1][2], g[2][2]]  # touches the center on 1 side
    heavy, light = make_area(a_cells, 100), make_area(b_cells, 1)
    filled = Partitioner(min_area_weight=1, max_area_weight=1000)._fill_gaps(
        [heavy, light], {}, owners(heavy, light), lambda _: None
    )
    assert filled == (0, 1)
    assert g[1][1] in heavy and heavy.weight == 600 and heavy.empty_grid_count == 1


def test_pipeline_leaves_no_gaps_and_switch_turns_it_off():
    g = block(14, 14)
    rng = random.Random(3)
    data = {g[r][c]: rng.randint(5, 30) for r in range(14) for c in range(14) if rng.random() >= 0.12}
    kwargs = {"min_area_weight": 150, "max_area_weight": 300, "max_grids_per_area": 20}
    filled = Partitioner(**kwargs)
    result = filled.partition(data)
    check_invariants(result, filled.config)
    assert result.stats["empty_grids_filled"] > 0
    assert union_hole_count(result.areas) == 0

    unfilled = partition(data, fill_holes=False, **kwargs)
    assert unfilled.stats["empty_grids_filled"] == 0
    assert union_hole_count(unfilled.areas) > 0


def test_fill_gaps_finds_hole_touching_the_outside_at_a_corner():
    grid = block(3, 3)
    cells = [grid[r][c] for r in range(3) for c in range(3) if (r, c) not in {(1, 1), (0, 0)}]
    area = make_area(cells, 10)
    filled = Partitioner(min_area_weight=1, max_area_weight=1000)._fill_gaps([area], {}, owners(area), lambda _: None)
    assert filled == (0, 1)
    assert grid[1][1] in area and is_connected(area)


def test_orphan_pass_keeps_the_original_rule_of_two_areas():
    # a free grid touching only one area stays leftover, however many passes run
    row = block(1, 3)[0]
    area = make_area([row[0]], 100)
    pool = {cell: Grid(cell, 5) for cell in row[1:]}
    partitioner = Partitioner(min_area_weight=1, max_area_weight=1000, greediness=5)
    assert partitioner._absorb_orphans([area], pool, owners(area), lambda _: None) == 0
    assert area.grid_count == 1 and len(pool) == 2


def test_orphans_go_to_lightest_neighbouring_area():
    left, middle, right = block(1, 3)[0]
    heavy, light = Area(Grid(left, 50)), Area(Grid(right, 20))
    pool = {middle: Grid(middle, 5)}
    absorbed = Partitioner(min_area_weight=1, max_area_weight=1000, greediness=1)._absorb_orphans(
        [heavy, light], pool, {}, lambda _: None
    )
    assert absorbed == 1 and middle in light and light.weight == 25

    pool = {middle: Grid(middle, 5)}
    zero = Partitioner(min_area_weight=1, max_area_weight=1000, greediness=0)
    assert zero._absorb_orphans([heavy, light], pool, {}, lambda _: None) == 0
    assert middle in pool


def test_config_validation():
    with pytest.raises(ConfigError):
        PartitionConfig(min_area_weight=10, max_area_weight=5)
    with pytest.raises(ConfigError):
        PartitionConfig(min_area_weight=1, max_area_weight=5, precision=13)
    with pytest.raises(ConfigError):
        PartitionConfig(min_area_weight=1, max_area_weight=5, seed_order="biggest")
    with pytest.raises(ConfigError):
        Partitioner(PartitionConfig(min_area_weight=1, max_area_weight=5), greediness=1)


def test_save_writes_requested_formats(tmp_path, block10):
    result = partition(block10, min_area_weight=30, max_area_weight=60)
    paths = result.save(str(tmp_path / "out"), formats=("geojson", "json", "csv", "map"))
    assert set(paths) == {"geojson", "json", "csv", "map"}
    assert paths["geojson"].endswith("areas.geojson") and paths["map"].endswith("areas-map.html")
    lines = (tmp_path / "out" / "areas-assignments.csv").read_text().splitlines()
    assert lines[0] == "geohash,area_id,weight"
    assert len(lines) == 1 + result.stats["total_grids"] + result.stats["empty_grids_filled"]
    with pytest.raises(ValueError):
        result.save(str(tmp_path), formats=("shapefile",))
