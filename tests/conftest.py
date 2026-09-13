from typing import Dict, List

import pytest

from geohash_partition.geohash import neighbors

ORIGIN = "u4pruy"  # precision 6, somewhere in the North Sea: far from poles and the antimeridian


def block(rows: int, cols: int, origin: str = ORIGIN) -> List[List[str]]:
    """A rows x cols block of geohashes; ``grid[r][c]`` moves north with r, east with c."""
    result = []
    row_start = origin
    for _ in range(rows):
        row = [row_start]
        for _ in range(cols - 1):
            row.append(neighbors(row[-1])["e"])
        result.append(row)
        row_start = neighbors(row_start)["n"]
    return result


def uniform_block(rows: int, cols: int, weight=10, origin: str = ORIGIN) -> Dict[str, int]:
    return {cell: weight for row in block(rows, cols, origin) for cell in row}


@pytest.fixture
def block10() -> Dict[str, int]:
    return uniform_block(10, 10)
