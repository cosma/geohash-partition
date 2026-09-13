"""GeohashPartition: assemble geohash grids into connected, weight-balanced areas.

Quick start::

    from geohash_partition import Partitioner

    result = Partitioner(min_area_weight=3000, max_area_weight=6000).partition("data.csv")
    result.save("out/")  # areas.geojson (for geojson.io), areas.json, areas-map.html (Leaflet)
"""

from .area import Area
from .geohash import GeohashError, bbox, center, encode, neighbors
from .grid import Grid, haversine
from .io import InputError
from .leaflet_map import render_map, save_map
from .outline import point_in_ring
from .partitioner import ConfigError, PartitionConfig, Partitioner, PartitionResult, partition

__version__ = "0.1.0"

__all__ = [
    "Area",
    "ConfigError",
    "GeohashError",
    "Grid",
    "InputError",
    "PartitionConfig",
    "PartitionResult",
    "Partitioner",
    "__version__",
    "bbox",
    "center",
    "encode",
    "haversine",
    "neighbors",
    "partition",
    "point_in_ring",
    "render_map",
    "save_map",
]
