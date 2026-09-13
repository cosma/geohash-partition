"""Loading weighted geohashes from user data and exporting results."""

from __future__ import annotations

import csv
import json
import math
import os
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Tuple, Union

from .geohash import GeohashError, validate
from .grid import Number

Row = Tuple[str, Number]
Source = Union[str, "os.PathLike[str]", Mapping[str, Number], Iterable[Any]]


class InputError(ValueError):
    """Raised when the input data cannot be interpreted."""


def is_missing(value: Any) -> bool:
    """True for ``None``, blank strings, NaN, and pandas ``NA`` / ``NaT``."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if type(value).__name__ in ("NAType", "NaTType"):
        return True
    return isinstance(value, str) and not value.strip()


def parse_number(value: Any) -> Number:
    """Parse a weight, keeping integers as ``int`` and everything else as ``float``.

    Missing values (empty, ``None``, NaN, pandas ``NA``) and non-finite numbers
    raise :class:`InputError` instead of silently corrupting the totals.
    """
    if isinstance(value, bool):
        raise InputError(f"weight must be numeric, got {value!r}")
    if is_missing(value):
        raise InputError("weight is empty")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        number: Number = value
    else:
        text = str(value).strip()
        try:
            return int(text)
        except ValueError:
            try:
                number = float(text)
            except ValueError:
                raise InputError(f"weight must be numeric, got {value!r}") from None
    if not math.isfinite(number):
        raise InputError(f"weight must be a finite number, got {value!r}")
    return number


def _looks_numeric(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _rows_from_csv(path: Union[str, "os.PathLike[str]"]) -> Iterator[Row]:
    """Read a two-column CSV: geohash first, weight second.

    Columns are read by position, so header names are free (``geohash,weight``,
    ``geohash,orders``, ``cell,dogs`` ...). The header row is optional: a first
    row whose second cell is not a number is treated as a header. Blank lines
    are skipped. Any other row must have exactly two columns.
    """
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        first_row = True
        data_rows = 0
        for line_number, cells in enumerate(reader, start=1):
            cells = [cell.strip() for cell in cells]
            if not any(cells):
                continue  # blank line
            if len(cells) != 2:
                raise InputError(
                    f"{path}, line {line_number}: expected 2 columns (geohash, weight), "
                    f"found {len(cells)}: {cells!r}"
                )
            geohash, weight = cells
            if first_row:
                first_row = False
                if not _looks_numeric(weight):
                    continue  # header row
            if not geohash:
                raise InputError(f"{path}, line {line_number}: geohash is empty")
            try:
                yield geohash, parse_number(weight)
            except InputError as error:
                raise InputError(f"{path}, line {line_number}: {error}") from None
            data_rows += 1
        if data_rows == 0:
            raise InputError(f"{path}: no data rows; expected lines of geohash,weight")


def _checked(geohash: Any, weight: Any, where: str) -> Row:
    """Validate one record, naming where it came from in any error."""
    if is_missing(geohash):
        raise InputError(f"{where}: geohash is empty")
    try:
        return str(geohash), parse_number(weight)
    except InputError as error:
        raise InputError(f"{where}, geohash {str(geohash)!r}: {error}") from None


def _rows_from_dataframe(frame: Any, geohash_column: str, weight_column: str) -> Iterator[Row]:
    columns = list(frame.columns)
    missing = [column for column in (geohash_column, weight_column) if column not in columns]
    if missing:
        raise InputError(
            f"DataFrame is missing column(s) {missing}; found {columns}. "
            "Use geohash_column/weight_column to map your column names."
        )
    geohashes = frame[geohash_column].tolist()
    weights = frame[weight_column].tolist()
    index = getattr(frame, "index", None)
    labels = index.tolist() if hasattr(index, "tolist") else range(len(geohashes))
    for label, geohash, weight in zip(labels, geohashes, weights):
        yield _checked(geohash, weight, f"DataFrame row {label!r}")


def _rows_from_iterable(items: Iterable[Any], geohash_column: str, weight_column: str) -> Iterator[Row]:
    for index, item in enumerate(items):
        where = f"item {index}"
        if isinstance(item, Mapping):
            absent = [key for key in (geohash_column, weight_column) if key not in item]
            if absent:
                raise InputError(f"{where}: missing key(s) {absent}")
            yield _checked(item[geohash_column], item[weight_column], where)
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            yield _checked(item[0], item[1], where)
        else:
            raise InputError(
                f"{where}: expected (geohash, weight) or a mapping with "
                f"{geohash_column!r} and {weight_column!r}, got {item!r}"
            )


def iter_rows(source: Source, geohash_column: str = "geohash", weight_column: str = "weight") -> Iterator[Row]:
    """Yield ``(geohash, weight)`` pairs from any supported source.

    * CSV path: two columns, geohash then weight, read by position.
    * pandas DataFrame or list of dicts: read by ``geohash_column`` / ``weight_column``.
    * ``{geohash: weight}`` dict or iterable of ``(geohash, weight)`` pairs.
    """
    if isinstance(source, (str, os.PathLike)):
        yield from _rows_from_csv(source)
    elif hasattr(source, "columns") and hasattr(source, "__getitem__"):
        yield from _rows_from_dataframe(source, geohash_column, weight_column)
    elif isinstance(source, Mapping):
        for geohash, weight in source.items():
            yield _checked(geohash, weight, "mapping entry")
    else:
        yield from _rows_from_iterable(source, geohash_column, weight_column)


def aggregate(rows: Iterable[Row], precision: int) -> Tuple[Dict[str, Number], int]:
    """Truncate geohashes to ``precision`` and sum weights per resulting grid.

    Returns ``(weights_by_grid, row_count)``.
    """
    weights: Dict[str, Number] = {}
    count = 0
    for geohash, weight in rows:
        count += 1
        try:
            clean = validate(geohash)
        except GeohashError as error:
            raise InputError(str(error)) from None
        if len(clean) < precision:
            raise InputError(
                f"geohash {geohash!r} has {len(clean)} characters but precision is {precision}; "
                "input geohashes must be at least as precise as the target precision"
            )
        grid_id = clean[:precision]
        weights[grid_id] = weights.get(grid_id, 0) + weight
    return weights, count


# -- exporters ---------------------------------------------------------------


def write_json(data: Mapping[str, Any], path: Union[str, "os.PathLike[str]"], indent: int = 2) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=indent, ensure_ascii=False)


def write_assignments_csv(rows: Iterable[Tuple[str, str, Number]], path: Union[str, "os.PathLike[str]"]) -> None:
    """Write ``geohash,area_id,weight`` rows (area_id empty for leftover grids)."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["geohash", "area_id", "weight"])
        writer.writerows(rows)


def read_result_json(path: Union[str, "os.PathLike[str]"]) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def as_list(items: Iterable[Any]) -> List[Any]:
    return list(items)
