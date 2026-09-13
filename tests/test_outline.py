from geohash_partition.geohash import bbox
from geohash_partition.outline import geojson_geometry, polygons_from_boxes, rings_from_boxes, signed_area
from tests.conftest import block


def test_single_box_is_one_ccw_ring():
    rings = rings_from_boxes([bbox("u4pruy")])
    assert len(rings) == 1
    assert len(rings[0]) == 5 and rings[0][0] == rings[0][-1]
    assert signed_area(rings[0]) > 0


def test_block_union_is_one_rectangle():
    cells = [cell for row in block(3, 4) for cell in row]
    polygons = polygons_from_boxes(bbox(cell) for cell in cells)
    assert len(polygons) == 1
    outer = polygons[0][0]
    assert len(outer) == 5  # collinear points removed by edge cancellation: a plain rectangle
    assert len(polygons[0]) == 1  # no holes


def test_ring_with_hole():
    grid = block(3, 3)
    cells = [grid[r][c] for r in range(3) for c in range(3) if (r, c) != (1, 1)]
    geometry = geojson_geometry(bbox(cell) for cell in cells)
    assert geometry["type"] == "Polygon"
    assert len(geometry["coordinates"]) == 2  # outer + one hole
    assert signed_area([tuple(p) for p in geometry["coordinates"][1]]) < 0


def test_diagonal_touch_splits_into_multipolygon():
    grid = block(2, 2)
    geometry = geojson_geometry([bbox(grid[0][0]), bbox(grid[1][1])])
    assert geometry["type"] == "MultiPolygon"
    assert len(geometry["coordinates"]) == 2


def test_hole_touching_the_outside_at_a_corner():
    grid = block(3, 3)
    cells = [grid[r][c] for r in range(3) for c in range(3) if (r, c) not in {(1, 1), (0, 0)}]
    boxes = [bbox(cell) for cell in cells]
    assert sum(len(p) - 1 for p in polygons_from_boxes(boxes)) == 0  # merged into the outer ring at the corner
    joined = polygons_from_boxes(boxes, connect_diagonal=True)
    assert len(joined) == 1 and len(joined[0]) == 2  # the covered cell is a separate hole
