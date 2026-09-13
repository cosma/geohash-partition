"""The atom of a partition: one geohash grid carrying a weight."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Tuple, Union

from .geohash import BBox, bbox, neighbor_ids

Number = Union[int, float]

EARTH_RADIUS_M = 6_371_008.8


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two points."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


@dataclass(eq=False)
class Grid:
    """A geohash grid with its weight and pre-computed geometry."""

    id: str
    weight: Number
    empty: bool = False  # True for a zero-weight grid added to close a gap (no input row)
    lat: float = field(init=False)
    lon: float = field(init=False)
    bbox: BBox = field(init=False, repr=False)
    neighbors: Tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.bbox = bbox(self.id)
        min_lat, min_lon, max_lat, max_lon = self.bbox
        self.lat = (min_lat + max_lat) / 2
        self.lon = (min_lon + max_lon) / 2
        self.neighbors = neighbor_ids(self.id)

    def distance_to(self, other: "Grid") -> float:
        """Great-circle distance in metres between the two grid centers."""
        return haversine(self.lat, self.lon, other.lat, other.lon)

    def to_dict(self) -> dict:
        return {"id": self.id, "weight": self.weight, "lat": self.lat, "lon": self.lon, "empty": self.empty}
