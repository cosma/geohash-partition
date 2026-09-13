"""Colours shared by the GeoJSON export and the Leaflet map.

Areas use a single-hue sequential ramp, light for low weight and dark for high
weight, so colour always means magnitude and never identity.
"""

from __future__ import annotations

from typing import Iterable, Sequence, Tuple

SEQUENTIAL_BLUE: Sequence[str] = (
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
    "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
)
AREA_STROKE = "#0d366b"
AREA_FILL_OPACITY = 0.55
LEFTOVER_FILL = "#c3c2b7"
LEFTOVER_STROKE = "#898781"
LEFTOVER_FILL_OPACITY = 0.3


def weight_range(weights: Iterable[float]) -> Tuple[float, float]:
    """Smallest and largest weight, or ``(0.0, 0.0)`` when there are none."""
    values = [float(weight) for weight in weights]
    if not values:
        return 0.0, 0.0
    return min(values), max(values)


def ramp_color(value: float, low: float, high: float, ramp: Sequence[str] = SEQUENTIAL_BLUE) -> str:
    """Map ``value`` in ``[low, high]`` onto a ramp step."""
    if high <= low:
        return ramp[len(ramp) // 2]
    position = (float(value) - low) / (high - low)
    index = min(len(ramp) - 1, max(0, int(round(position * (len(ramp) - 1)))))
    return ramp[index]
