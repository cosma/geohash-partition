import json

import pytest

from geohash_partition import partition, render_map
from geohash_partition.geojson import result_dict_to_geojson
from geohash_partition.leaflet_map import LEAFLET_JS, LEAFLET_JS_SRI, TILE_PRESETS, build_payload, resolve_tiles
from geohash_partition.outline import signed_area
from tests.conftest import block, uniform_block


def rings_of(geometry):
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    yield from polygons


def make_result():
    grids = uniform_block(6, 6, weight=10)
    grid = block(6, 6)
    del grids[grid[2][2]]  # a data gap, so some area outline has a hole
    return partition(grids, min_area_weight=40, max_area_weight=80)


def test_geojson_is_rfc7946_and_simplestyled():
    result = make_result()
    collection = json.loads(json.dumps(result.to_geojson(include_leftover=True)))
    assert collection["type"] == "FeatureCollection"
    kinds = {feature["properties"]["kind"] for feature in collection["features"]}
    assert "area" in kinds
    for feature in collection["features"]:
        assert feature["type"] == "Feature"
        props = feature["properties"]
        for key in ("fill", "fill-opacity", "stroke", "stroke-width", "stroke-opacity"):
            assert key in props
        assert props["fill"].startswith("#") and len(props["fill"]) == 7
        for polygon in rings_of(feature["geometry"]):
            outer, holes = polygon[0], polygon[1:]
            assert outer[0] == outer[-1] and len(outer) >= 4
            assert signed_area([tuple(p) for p in outer]) > 0  # counter-clockwise exterior
            for hole in holes:
                assert hole[0] == hole[-1]
                assert signed_area([tuple(p) for p in hole]) < 0  # clockwise holes
            for lon, lat in outer:
                assert -180 <= lon <= 180 and -90 <= lat <= 90
    areas = [f for f in collection["features"] if f["properties"]["kind"] == "area"]
    assert len(areas) == result.area_count
    assert (
        sum(f["properties"]["grid_count"] - f["properties"]["empty_grids"] for f in areas)
        == result.stats["grouped_grids"]
    )
    assert sum(f["properties"]["empty_grids"] for f in areas) == result.stats["empty_grids_filled"]
    assert all(len(f["properties"]["grids"].split(",")) == f["properties"]["grid_count"] for f in areas)


def test_geojson_from_saved_dict_matches_live_result():
    result = make_result()
    from_dict = result_dict_to_geojson(json.loads(json.dumps(result.to_dict())), include_leftover=False)
    assert from_dict == json.loads(json.dumps(result.to_geojson()))


def test_render_map_embeds_data_and_leaflet_safely():
    result = make_result()
    page = render_map(result, title="Dogs </script><b>per block</b>")
    assert LEAFLET_JS in page and LEAFLET_JS_SRI in page
    assert page.count("</script>") == 2  # leaflet include + inline script; data cannot close the tag
    assert "<title>Dogs &lt;/script&gt;&lt;b&gt;per block&lt;/b&gt;</title>" in page
    assert "const DATA = " in page


def test_payload_from_result_json_and_geojson_agree():
    result = make_result()
    live = build_payload(result)
    saved = build_payload(json.loads(json.dumps(result.to_dict())))
    geo = build_payload(json.loads(json.dumps(result.to_geojson(include_leftover=True))))
    assert live["areas"] == saved["areas"] == geo["areas"]
    assert len(live["leftover"]["features"]) == len(geo["leftover"]["features"]) == len(result.leftover)
    assert live["configRows"] and not geo["configRows"]  # a bare GeoJSON has no parameters
    assert live["seeds"] and len(live["seeds"]) == result.area_count


def test_auto_tiles_fall_back_when_opened_from_disk():
    settings = resolve_tiles("auto")
    assert "openstreetmap.org" in settings["primary"]["url"]
    assert "opentopomap.org" in settings["fileFallback"]["url"]
    page = render_map(make_result())
    assert 'window.location.protocol === "file:"' in page
    assert "strict-origin-when-cross-origin" in page
    payload = build_payload(make_result())
    assert payload["tiles"] == settings


def test_explicit_tiles_have_no_fallback_and_custom_urls_need_attribution():
    assert resolve_tiles("opentopomap") == {"primary": TILE_PRESETS["opentopomap"], "fileFallback": None}
    custom = resolve_tiles("https://tiles.example.com/{z}/{x}/{y}.png", "&copy; Example")
    assert custom["primary"]["url"].endswith("{z}/{x}/{y}.png") and custom["fileFallback"] is None
    with pytest.raises(ValueError, match="attribution"):
        resolve_tiles("https://tiles.example.com/{z}/{x}/{y}.png")
    with pytest.raises(ValueError, match="unknown tiles"):
        resolve_tiles("carto")
