"""Generate a synthetic weighted-geohash CSV of Berlin for trying GeohashPartition.

The grids cover Berlin at geohash precision 6, roughly 0.75 km x 0.6 km per
grid at this latitude, clipped to a circle around the city centre. The weights
are invented: a background level in every grid, a few Gaussian "hot spots"
placed on well-known districts, and about 8% of grids dropped to imitate patchy
real data.
They do not represent any real statistic. Run::

    uv run python examples/make_sample.py            # writes examples/sample.csv
    uv run python examples/make_sample.py --seed 7   # different noise and gaps
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import random

from geohash_partition.geohash import center, encode, neighbors
from geohash_partition.grid import haversine

PRECISION = 6
CITY_CENTER = (52.5200, 13.4050)  # Berlin Mitte
CITY_RADIUS_KM = 20.0  # rough city extent; grids farther out are skipped
SEARCH_BOX = (52.32, 13.08, 52.72, 13.74)  # south, west, north, east

# (name, lat, lon, extra peak weight per grid, spread in km). Invented values.
HOT_SPOTS = [
    ("Mitte", 52.5200, 13.4050, 360, 3.0),
    ("Kreuzberg", 52.4990, 13.4180, 260, 2.5),
    ("Prenzlauer Berg", 52.5390, 13.4240, 200, 2.5),
    ("Charlottenburg", 52.5050, 13.3040, 180, 2.5),
    ("Neukölln", 52.4810, 13.4350, 160, 2.0),
    ("Steglitz", 52.4570, 13.3200, 100, 2.5),
    ("Spandau", 52.5360, 13.2040, 80, 2.5),
    ("Köpenick", 52.4450, 13.5750, 72, 2.5),
]
BACKGROUND = (20, 60)  # every grid gets a uniform random base weight in this range
DROP_RATE = 0.08


def berlin_grids():
    """Walk the precision-6 geohash grid over the search box, keeping grids inside the city circle."""
    south, west, north, east = SEARCH_BOX
    row_start = encode(south, west, PRECISION)
    while center(row_start)[0] <= north:
        cell = row_start
        while center(cell)[1] <= east:
            lat, lon = center(cell)
            if haversine(lat, lon, *CITY_CENTER) <= CITY_RADIUS_KM * 1000:
                yield cell, lat, lon
            cell = neighbors(cell)["e"]
        row_start = neighbors(row_start)["n"]


def make_rows(seed: int):
    rng = random.Random(seed)
    rows = []
    for cell, lat, lon in berlin_grids():
        weight = rng.uniform(*BACKGROUND)
        for _, spot_lat, spot_lon, peak, spread_km in HOT_SPOTS:
            distance_km = haversine(lat, lon, spot_lat, spot_lon) / 1000
            weight += peak * math.exp(-(distance_km ** 2) / (2 * spread_km ** 2))
        value = int(round(weight))
        if value == 0 or rng.random() < DROP_RATE:
            continue  # keep some data gaps, like real data
        rows.append((cell, value))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seed", type=int, default=42, help="random seed for noise and gaps")
    parser.add_argument("-o", "--output", default=os.path.join(os.path.dirname(__file__), "sample.csv"))
    args = parser.parse_args()
    rows = make_rows(args.seed)
    with open(args.output, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["geohash", "weight"])
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
