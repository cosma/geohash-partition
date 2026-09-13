"""An area: a 4-connected group of grids assembled around a seed."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from .grid import Grid, Number
from .outline import geojson_geometry


class Area:
    """A connected group of grids grown from a seed grid.

    Growth always adds the free edge-neighbour whose mean distance to the
    grids already in the area is smallest, which keeps areas compact. Running
    distance sums are cached per candidate so growth stays linear per step.
    """

    __slots__ = ("_candidates", "_ids", "grids", "id", "seed", "weight")

    def __init__(self, seed: Grid) -> None:
        self.id: str = seed.id
        self.seed: Grid = seed
        self.grids: List[Grid] = [seed]
        self.weight: Number = seed.weight
        self._ids: Set[str] = {seed.id}
        self._candidates: Dict[str, Tuple[Grid, float]] = {}

    # -- basic accessors -----------------------------------------------------

    @property
    def grid_count(self) -> int:
        return len(self.grids)

    @property
    def empty_grid_count(self) -> int:
        """Zero-weight grids added to close gaps."""
        return sum(1 for grid in self.grids if grid.empty)

    @property
    def grid_ids(self) -> Set[str]:
        return self._ids

    def __contains__(self, grid_id: str) -> bool:
        return grid_id in self._ids

    def __repr__(self) -> str:
        return f"Area(id={self.id!r}, grids={self.grid_count}, weight={self.weight})"

    # -- growth --------------------------------------------------------------

    def add(self, grid: Grid) -> None:
        """Attach a grid to the area and update cached candidate distances."""
        self.grids.append(grid)
        self.weight += grid.weight
        self._ids.add(grid.id)
        self._candidates.pop(grid.id, None)
        for candidate_id, (candidate, total) in self._candidates.items():
            self._candidates[candidate_id] = (candidate, total + candidate.distance_to(grid))

    def release_growth_cache(self) -> None:
        """Drop cached candidate distances once growth is finished."""
        self._candidates.clear()

    def needs_expansion(self, max_grids: int, max_weight: Number) -> bool:
        return self.grid_count < max_grids and self.weight < max_weight

    def boundary_ids(self) -> Set[str]:
        """Ids of all edge-neighbours of the area that are not part of it."""
        result: Set[str] = set()
        for grid in self.grids:
            for neighbor_id in grid.neighbors:
                if neighbor_id not in self._ids:
                    result.add(neighbor_id)
        return result

    def grow(self, pool: Dict[str, Grid]) -> Optional[Grid]:
        """Add the most compact free neighbour from ``pool``; return it or ``None``."""
        frontier = [grid_id for grid_id in self.boundary_ids() if grid_id in pool]
        if not frontier:
            return None
        for grid_id in frontier:
            if grid_id not in self._candidates:
                candidate = pool[grid_id]
                total = sum(candidate.distance_to(member) for member in self.grids)
                self._candidates[grid_id] = (candidate, total)
        best_id = min(
            frontier,
            key=lambda grid_id: (self._candidates[grid_id][1] / self.grid_count, grid_id),
        )
        best = self._candidates[best_id][0]
        self.add(best)
        return best

    # -- output --------------------------------------------------------------

    def geometry(self) -> dict:
        """GeoJSON geometry of the union of the area's grid boxes."""
        return geojson_geometry(grid.bbox for grid in self.grids)

    def to_dict(self, include_geometry: bool = True) -> dict:
        data: Dict[str, Any] = {
            "id": self.id,
            "seed": self.seed.id,
            "weight": self.weight,
            "grid_count": self.grid_count,
            "empty_grid_count": self.empty_grid_count,
            "grids": [grid.to_dict() for grid in self.grids],
        }
        if include_geometry:
            data["geometry"] = self.geometry()
        return data
