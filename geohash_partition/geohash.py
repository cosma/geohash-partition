"""Minimal, dependency-free geohash arithmetic.

Only what GeohashPartition needs: decode a geohash to its bounding box, encode a
point, and find the four edge neighbours (north, east, south, west).

Bounding boxes are computed by interval halving, so every edge coordinate is a
dyadic rational that is represented exactly as a float. Two grids that share
an edge therefore produce bit-identical edge coordinates, which the outline
builder relies on.
"""

from __future__ import annotations

from typing import Dict, Iterator, Optional, Tuple

BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
_DECODE = {char: index for index, char in enumerate(BASE32)}
_BITS = (16, 8, 4, 2, 1)

BBox = Tuple[float, float, float, float]  # (min_lat, min_lon, max_lat, max_lon)


class GeohashError(ValueError):
    """Raised for malformed geohash strings."""


def validate(geohash: str) -> str:
    """Return the geohash lower-cased, or raise ``GeohashError``."""
    if not isinstance(geohash, str) or not geohash:
        raise GeohashError(f"geohash must be a non-empty string, got {geohash!r}")
    lowered = geohash.strip().lower()
    for char in lowered:
        if char not in _DECODE:
            raise GeohashError(f"invalid character {char!r} in geohash {geohash!r}")
    return lowered


def bbox(geohash: str) -> BBox:
    """Bounding box of a geohash as ``(min_lat, min_lon, max_lat, max_lon)``."""
    lat_lo, lat_hi = -90.0, 90.0
    lon_lo, lon_hi = -180.0, 180.0
    even = True
    for char in geohash:
        try:
            value = _DECODE[char]
        except KeyError:
            raise GeohashError(f"invalid character {char!r} in geohash {geohash!r}") from None
        for bit in _BITS:
            if even:
                mid = (lon_lo + lon_hi) / 2
                if value & bit:
                    lon_lo = mid
                else:
                    lon_hi = mid
            else:
                mid = (lat_lo + lat_hi) / 2
                if value & bit:
                    lat_lo = mid
                else:
                    lat_hi = mid
            even = not even
    return lat_lo, lon_lo, lat_hi, lon_hi


def center(geohash: str) -> Tuple[float, float]:
    """Center ``(lat, lon)`` of a geohash."""
    lat_lo, lon_lo, lat_hi, lon_hi = bbox(geohash)
    return (lat_lo + lat_hi) / 2, (lon_lo + lon_hi) / 2


def encode(lat: float, lon: float, precision: int) -> str:
    """Encode a point into a geohash of the given length."""
    if not 1 <= precision <= 12:
        raise GeohashError(f"precision must be between 1 and 12, got {precision}")
    lat_lo, lat_hi = -90.0, 90.0
    lon_lo, lon_hi = -180.0, 180.0
    chars = []
    value = 0
    bit_index = 0
    even = True
    while len(chars) < precision:
        if even:
            mid = (lon_lo + lon_hi) / 2
            if lon >= mid:
                value = (value << 1) | 1
                lon_lo = mid
            else:
                value <<= 1
                lon_hi = mid
        else:
            mid = (lat_lo + lat_hi) / 2
            if lat >= mid:
                value = (value << 1) | 1
                lat_lo = mid
            else:
                value <<= 1
                lat_hi = mid
        even = not even
        bit_index += 1
        if bit_index == 5:
            chars.append(BASE32[value])
            value = 0
            bit_index = 0
    return "".join(chars)


def neighbors(geohash: str) -> Dict[str, Optional[str]]:
    """The four edge neighbours of a geohash, keyed ``n``, ``e``, ``s``, ``w``.

    A neighbour is ``None`` when it would cross a pole. Longitude wraps around
    the antimeridian.
    """
    lat_lo, lon_lo, lat_hi, lon_hi = bbox(geohash)
    height = lat_hi - lat_lo
    width = lon_hi - lon_lo
    clat = (lat_lo + lat_hi) / 2
    clon = (lon_lo + lon_hi) / 2
    precision = len(geohash)

    def shifted(lat: float, lon: float) -> Optional[str]:
        if lat >= 90.0 or lat <= -90.0:
            return None
        if lon >= 180.0:
            lon -= 360.0
        elif lon < -180.0:
            lon += 360.0
        return encode(lat, lon, precision)

    return {
        "n": shifted(clat + height, clon),
        "e": shifted(clat, clon + width),
        "s": shifted(clat - height, clon),
        "w": shifted(clat, clon - width),
    }


def neighbor_ids(geohash: str) -> Tuple[str, ...]:
    """Existing edge neighbours as a tuple (pole-crossing ones are dropped)."""
    return tuple(value for value in neighbors(geohash).values() if value is not None)


def cells_in_box(min_lat: float, min_lon: float, max_lat: float, max_lon: float, precision: int) -> Iterator[str]:
    """Every geohash of ``precision`` whose center lies inside the box.

    The walk steps from cell center to cell center, so when the box edges sit
    on cell boundaries (as area outlines do) each covered cell is yielded once.
    """
    probe_min_lat, probe_min_lon, probe_max_lat, probe_max_lon = bbox(encode(min_lat, min_lon, precision))
    height = probe_max_lat - probe_min_lat
    width = probe_max_lon - probe_min_lon
    lat = probe_min_lat + height / 2
    while lat < max_lat:
        if lat > min_lat:
            lon = probe_min_lon + width / 2
            while lon < max_lon:
                if lon > min_lon:
                    yield encode(lat, lon, precision)
                lon += width
        lat += height
