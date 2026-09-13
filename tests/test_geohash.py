import pytest

from geohash_partition.geohash import GeohashError, bbox, cells_in_box, center, encode, neighbors, validate


def test_bbox_of_known_geohash():
    min_lat, min_lon, max_lat, max_lon = bbox("ezs42")
    assert min_lat == pytest.approx(42.583, abs=1e-3)
    assert max_lat == pytest.approx(42.627, abs=1e-3)
    assert min_lon == pytest.approx(-5.625, abs=1e-3)
    assert max_lon == pytest.approx(-5.581, abs=1e-3)


def test_encode_roundtrip():
    lat, lon = center("ezs42")
    assert encode(lat, lon, 5) == "ezs42"
    assert encode(42.6, -5.6, 5) == "ezs42"
    for precision in (1, 3, 6, 9, 12):
        code = encode(48.85837, 2.294481, precision)
        assert len(code) == precision
        clat, clon = center(code)
        assert encode(clat, clon, precision) == code


def test_precision_one_adjacency():
    assert neighbors("s") == {"n": "u", "e": "t", "s": "k", "w": "e"}


def test_neighbors_are_symmetric_and_share_edges():
    cell = "u4pruy"
    around = neighbors(cell)
    assert neighbors(around["n"])["s"] == cell
    assert neighbors(around["e"])["w"] == cell
    assert neighbors(around["s"])["n"] == cell
    assert neighbors(around["w"])["e"] == cell
    # shared edges are bit-identical, which the outline builder relies on
    assert bbox(cell)[3] == bbox(around["e"])[1]
    assert bbox(cell)[2] == bbox(around["n"])[0]


def test_poles_and_antimeridian():
    assert neighbors("z")["n"] is None
    assert neighbors("0")["s"] is None
    assert neighbors("0")["w"] == "p"
    assert neighbors("z")["e"] == "b"
    assert neighbors("xz")["e"] == "8p"


def test_validate():
    assert validate(" EZS42 ") == "ezs42"
    with pytest.raises(GeohashError):
        validate("ezsa")  # 'a' is not in the geohash alphabet
    with pytest.raises(GeohashError):
        validate("")


def test_cells_in_box_covers_exactly_the_cells_inside():
    origin = "u4pruy"
    east = neighbors(origin)["e"]
    north = neighbors(origin)["n"]
    north_east = neighbors(east)["n"]
    min_lat, min_lon, _, _ = bbox(origin)
    _, _, max_lat, max_lon = bbox(north_east)
    assert sorted(cells_in_box(min_lat, min_lon, max_lat, max_lon, 6)) == sorted([origin, east, north, north_east])
