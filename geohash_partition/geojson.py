"""GeoJSON features for areas and leftover grids.

Features follow RFC 7946: coordinates are ``[lon, lat]``, outer rings run
counter-clockwise and holes clockwise. Each feature also carries simplestyle
properties (``fill``, ``stroke``, ...) so geojson.io and other simplestyle-aware
viewers colour areas by weight without any extra setup.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .geohash import bbox
from .outline import geojson_geometry
from .style import (
    AREA_FILL_OPACITY,
    AREA_STROKE,
    LEFTOVER_FILL,
    LEFTOVER_FILL_OPACITY,
    LEFTOVER_STROKE,
    ramp_color,
    weight_range,
)


def area_feature(
    area_id: str,
    seed: str,
    weight: float,
    grid_ids: Sequence[str],
    geometry: Mapping[str, Any],
    low: float,
    high: float,
    empty_grids: int = 0,
) -> Dict[str, Any]:
    """One area as a GeoJSON Feature, coloured by its weight within ``[low, high]``."""
    return {
        "type": "Feature",
        "id": area_id,
        "properties": {
            "kind": "area",
            "area_id": area_id,
            "seed": seed,
            "weight": weight,
            "grid_count": len(grid_ids),
            "empty_grids": empty_grids,
            "grids": ",".join(grid_ids),
            "fill": ramp_color(weight, low, high),
            "fill-opacity": AREA_FILL_OPACITY,
            "stroke": AREA_STROKE,
            "stroke-width": 1,
            "stroke-opacity": 1,
        },
        "geometry": dict(geometry),
    }


def leftover_feature(grid_id: str, weight: float) -> Dict[str, Any]:
    """A grid that belongs to no area, as a square GeoJSON Feature."""
    min_lat, min_lon, max_lat, max_lon = bbox(grid_id)
    ring = [[min_lon, min_lat], [max_lon, min_lat], [max_lon, max_lat], [min_lon, max_lat], [min_lon, min_lat]]
    return {
        "type": "Feature",
        "id": grid_id,
        "properties": {
            "kind": "leftover",
            "grid": grid_id,
            "weight": weight,
            "fill": LEFTOVER_FILL,
            "fill-opacity": LEFTOVER_FILL_OPACITY,
            "stroke": LEFTOVER_STROKE,
            "stroke-width": 0.5,
            "stroke-opacity": 1,
        },
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def feature_collection(features: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    return {"type": "FeatureCollection", "features": list(features)}


def result_dict_to_geojson(data: Mapping[str, Any], include_leftover: bool = False) -> Dict[str, Any]:
    """Convert a saved partition result (``PartitionResult.to_dict()``) to a FeatureCollection."""
    areas: List[Mapping[str, Any]] = list(data.get("areas", []))
    low, high = weight_range(area["weight"] for area in areas)
    features = []
    for area in areas:
        grid_ids = [grid["id"] for grid in area["grids"]]
        geometry = area.get("geometry") or geojson_geometry(bbox(grid_id) for grid_id in grid_ids)
        empty = sum(1 for grid in area["grids"] if grid.get("empty"))
        features.append(
            area_feature(area["id"], area.get("seed", area["id"]), area["weight"], grid_ids, geometry, low, high, empty)
        )
    if include_leftover:
        features.extend(leftover_feature(grid["id"], grid["weight"]) for grid in data.get("leftover", []))
    return feature_collection(features)
