"""Build polygon outlines from a set of axis-aligned grid boxes, without shapely.

Every box contributes four directed edges (counter-clockwise). An edge shared
by two adjacent boxes appears once in each direction and cancels out, so only
boundary edges survive. Those are chained into closed rings. Rings with
positive signed area are outer boundaries; negative ones are holes.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Sequence, Tuple

from .geohash import BBox

Point = Tuple[float, float]  # (lon, lat), GeoJSON order
Ring = List[Point]
Polygon = List[Ring]  # [outer, hole, hole, ...]


def _box_edges(box: BBox) -> List[Tuple[Point, Point]]:
    min_lat, min_lon, max_lat, max_lon = box
    corners = [(min_lon, min_lat), (max_lon, min_lat), (max_lon, max_lat), (min_lon, max_lat)]
    return [(corners[i], corners[(i + 1) % 4]) for i in range(4)]


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])


def signed_area(ring: Sequence[Point]) -> float:
    """Shoelace area in degree² (sign only matters: positive is counter-clockwise)."""
    total = 0.0
    count = len(ring)
    for i in range(count):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % count]
        total += x1 * y2 - x2 * y1
    return total / 2


def point_in_ring(point: Point, ring: Sequence[Point]) -> bool:
    """Ray-casting point-in-polygon test."""
    x, y = point
    inside = False
    count = len(ring)
    j = count - 1
    for i in range(count):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def rings_from_boxes(boxes: Iterable[BBox], connect_diagonal: bool = False) -> List[Ring]:
    """Chain the boundary edges of the union of ``boxes`` into closed rings.

    Where two boxes touch only at a corner (a pinch vertex) the rings can be
    joined in two ways. With ``connect_diagonal=False`` the boxes are treated as
    separate, so each gets its own ring; this gives clean GeoJSON outlines. With
    ``connect_diagonal=True`` the boxes are treated as joined, so an empty cell
    whose four sides are covered stays a separate hole even when it touches the
    outside at a corner; gap detection uses this.
    """
    edges: Dict[Tuple[Point, Point], None] = {}
    for box in boxes:
        for start, end in _box_edges(box):
            if (end, start) in edges:
                del edges[(end, start)]
            else:
                edges[(start, end)] = None

    outgoing: Dict[Point, List[Point]] = defaultdict(list)
    for start, end in edges:
        outgoing[start].append(end)
    for ends in outgoing.values():
        ends.sort()

    rings: List[Ring] = []
    remaining = dict(edges)
    while remaining:
        start, current = next(iter(remaining))
        del remaining[(start, current)]
        outgoing[start].remove(current)
        ring: Ring = [start, current]
        previous = start
        while current != start:
            options = outgoing[current]
            if not options:  # dangling edge; should not happen for box unions
                break
            if len(options) == 1:
                nxt = options[0]
            else:
                # At a pinch vertex the interior is on the left of the ring. The
                # sharpest left turn keeps hugging the current box, splitting boxes
                # that touch at a corner; the sharpest right turn crosses to the
                # diagonal box, keeping them in one ring and holes separate.
                turns = [(_cross(previous, current, candidate), candidate) for candidate in options]
                nxt = (min if connect_diagonal else max)(turns)[1]
            options.remove(nxt)
            del remaining[(current, nxt)]
            ring.append(nxt)
            previous, current = current, nxt
        rings.append(_drop_collinear(ring))
    return rings


def _drop_collinear(ring: Ring) -> Ring:
    """Remove vertices that lie on a straight line between their neighbours."""
    points = ring[:-1]  # open ring
    kept: Ring = []
    count = len(points)
    for i in range(count):
        previous, current, nxt = points[i - 1], points[i], points[(i + 1) % count]
        if _cross(previous, current, nxt) != 0:
            kept.append(current)
    if len(kept) < 3:
        return ring
    kept.append(kept[0])
    return kept


def polygons_from_boxes(boxes: Iterable[BBox], connect_diagonal: bool = False) -> List[Polygon]:
    """Group rings into polygons: each outer ring with the holes it contains."""
    rings = rings_from_boxes(boxes, connect_diagonal=connect_diagonal)
    outers = [ring for ring in rings if signed_area(ring) > 0]
    holes = [ring for ring in rings if signed_area(ring) < 0]
    polygons: List[Polygon] = [[outer] for outer in outers]
    for hole in holes:
        probe = hole[0]
        for polygon in polygons:
            if point_in_ring(probe, polygon[0]) or probe in polygon[0]:
                polygon.append(hole)
                break
    return polygons


def geojson_geometry(boxes: Iterable[BBox]) -> dict:
    """GeoJSON ``Polygon`` or ``MultiPolygon`` for the union of the boxes."""
    polygons = polygons_from_boxes(boxes)
    coords = [[[list(point) for point in ring] for ring in polygon] for polygon in polygons]
    if len(coords) == 1:
        return {"type": "Polygon", "coordinates": coords[0]}
    return {"type": "MultiPolygon", "coordinates": coords}
