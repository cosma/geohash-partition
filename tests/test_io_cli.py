import csv
import json

import pytest

from geohash_partition.cli import main
from geohash_partition.io import InputError, aggregate, iter_rows, parse_number
from tests.conftest import uniform_block


def write_csv(path, rows, header=("geohash", "weight")):
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def test_parse_number_keeps_ints():
    assert parse_number("12") == 12 and isinstance(parse_number("12"), int)
    assert parse_number("1.5") == 1.5
    assert parse_number(3) == 3
    with pytest.raises(InputError):
        parse_number("abc")
    with pytest.raises(InputError):
        parse_number(True)


def test_csv_reads_two_columns_by_position(tmp_path):
    path = tmp_path / "dogs.csv"
    write_csv(path, [("u4pruy", "3"), ("", ""), ("u4pruz", "4.5")], header=("cell", "dogs"))
    assert list(iter_rows(path)) == [("u4pruy", 3), ("u4pruz", 4.5)]


def test_csv_header_names_are_free(tmp_path):
    path = tmp_path / "visits.csv"
    write_csv(path, [("u33db2", "240"), ("u33db3", "75")], header=("geohash", "visits"))
    assert list(iter_rows(path)) == [("u33db2", 240), ("u33db3", 75)]


def test_csv_header_is_optional(tmp_path):
    path = tmp_path / "plain.csv"
    path.write_text("u4pruy,3\nu4pruz,4\n")
    assert list(iter_rows(path)) == [("u4pruy", 3), ("u4pruz", 4)]


def test_csv_rejects_other_column_counts(tmp_path):
    wide = tmp_path / "wide.csv"
    wide.write_text("geohash,weight,note\nu4pruy,3,1\n")
    with pytest.raises(InputError, match="line 1: expected 2 columns"):
        list(iter_rows(wide))
    narrow = tmp_path / "narrow.csv"
    narrow.write_text("geohash,weight\nu4pruy\n")
    with pytest.raises(InputError, match="line 2: expected 2 columns"):
        list(iter_rows(narrow))


def test_csv_reports_bad_values_and_empty_files(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("geohash,weight\nu4pruy,3\nu4pruz,lots\n")
    with pytest.raises(InputError, match="line 3: weight must be numeric"):
        list(iter_rows(bad))
    missing = tmp_path / "missing.csv"
    missing.write_text("geohash,weight\nu4pruy,\n")
    with pytest.raises(InputError, match="line 2: weight is empty"):
        list(iter_rows(missing))
    empty = tmp_path / "empty.csv"
    empty.write_text("geohash,weight\n\n")
    with pytest.raises(InputError, match="no data rows"):
        list(iter_rows(empty))


def test_dataframe_like_and_mapping_sources():
    class FakeFrame:
        columns = ("geohash", "weight")

        def __init__(self, data):
            self._data = data

        def __getitem__(self, column):
            values = self._data[column]

            class Column:
                def tolist(self_inner):
                    return list(values)

            return Column()

    frame = FakeFrame({"geohash": ["u4pruy", "u4pruz"], "weight": [1, 2]})
    assert list(iter_rows(frame)) == [("u4pruy", 1), ("u4pruz", 2)]
    assert list(iter_rows({"u4pruy": 5})) == [("u4pruy", 5)]
    assert list(iter_rows([{"geohash": "u4pruy", "weight": 7}])) == [("u4pruy", 7)]
    with pytest.raises(InputError):
        list(iter_rows([("u4pruy",)]))


class FakeColumn:
    def __init__(self, values):
        self._values = list(values)

    def tolist(self):
        return list(self._values)


class FakeFrame:
    """Just enough of the pandas DataFrame interface: columns, index, column access."""

    def __init__(self, data, index=None):
        self._data = data
        self.columns = list(data)
        size = len(next(iter(data.values())))
        self.index = FakeColumn(index if index is not None else range(size))

    def __getitem__(self, column):
        return FakeColumn(self._data[column])


class NAType:  # mimics pandas.NA by type name
    def __repr__(self):
        return "<NA>"


@pytest.mark.parametrize("empty", [None, float("nan"), NAType(), "", "  "])
def test_dataframe_empty_weight_raises_clear_error(empty):
    frame = FakeFrame({"geohash": ["u4pruy", "u4pruz"], "weight": [5, empty]}, index=["a", "b"])
    with pytest.raises(InputError, match=r"DataFrame row 'b', geohash 'u4pruz': weight is empty"):
        list(iter_rows(frame))


def test_dataframe_empty_geohash_and_non_finite_weight_raise():
    frame = FakeFrame({"geohash": ["u4pruy", None], "weight": [5, 6]})
    with pytest.raises(InputError, match=r"DataFrame row 1: geohash is empty"):
        list(iter_rows(frame))
    frame = FakeFrame({"geohash": ["u4pruy"], "weight": [float("inf")]})
    with pytest.raises(InputError, match="weight must be a finite number"):
        list(iter_rows(frame))


def test_dicts_and_pairs_empty_weight_raise_clear_error():
    with pytest.raises(InputError, match=r"item 1, geohash 'u4pruz': weight is empty"):
        list(iter_rows([{"geohash": "u4pruy", "weight": 1}, {"geohash": "u4pruz", "weight": None}]))
    with pytest.raises(InputError, match=r"item 0: missing key\(s\) \['weight'\]"):
        list(iter_rows([{"geohash": "u4pruy"}]))
    with pytest.raises(InputError, match=r"item 0, geohash 'u4pruy': weight is empty"):
        list(iter_rows([("u4pruy", float("nan"))]))
    with pytest.raises(InputError, match=r"mapping entry, geohash 'u4pruy': weight is empty"):
        list(iter_rows({"u4pruy": None}))


def test_aggregate_validates_and_truncates():
    weights, count = aggregate([("U4PRUY1", 1), ("u4pruy2", 2), ("u4pruz", 3)], precision=6)
    assert count == 3 and weights == {"u4pruy": 3, "u4pruz": 3}
    with pytest.raises(InputError):
        aggregate([("u4pr", 1)], precision=6)
    with pytest.raises(InputError):
        aggregate([("u4pral", 1)], precision=6)


def test_cli_build_writes_geojson_json_and_map(tmp_path):
    source = tmp_path / "in.csv"
    write_csv(source, uniform_block(6, 6).items())
    out = tmp_path / "out"
    code = main(
        [
            "build",
            "-i",
            str(source),
            "-o",
            str(out),
            "--min-area-weight",
            "30",
            "--max-area-weight",
            "60",
            "--max-grids-per-area",
            "6",
            "--csv",
            "--include-leftover",
            "--title",
            "Test run",
            "-q",
        ]
    )
    assert code == 0
    data = json.loads((out / "areas.json").read_text())
    assert data["config"]["min_area_weight"] == 30 and data["stats"]["total_grids"] == 36
    geo = json.loads((out / "areas.geojson").read_text())
    assert geo["type"] == "FeatureCollection" and geo["features"]
    assert (out / "areas-assignments.csv").exists()
    page = (out / "areas-map.html").read_text()
    assert "leaflet@1.9.4" in page and "<title>Test run</title>" in page


def test_cli_build_can_skip_outputs(tmp_path):
    source = tmp_path / "in.csv"
    write_csv(source, uniform_block(4, 4).items())
    code = main(
        [
            "build",
            "-i",
            str(source),
            "-o",
            str(tmp_path),
            "--name",
            "dogs",
            "--min-area-weight",
            "30",
            "--max-area-weight",
            "60",
            "--no-json",
            "--no-map",
            "-q",
        ]
    )
    assert code == 0
    assert (tmp_path / "dogs.geojson").exists()
    assert not (tmp_path / "dogs.json").exists() and not (tmp_path / "dogs-map.html").exists()


def test_cli_view_from_json_and_geojson(tmp_path):
    source = tmp_path / "in.csv"
    write_csv(source, uniform_block(6, 6).items())
    assert (
        main(
            [
                "build",
                "-i",
                str(source),
                "-o",
                str(tmp_path),
                "--no-map",
                "--min-area-weight",
                "30",
                "--max-area-weight",
                "60",
                "-q",
            ]
        )
        == 0
    )
    assert main(["view", "-i", str(tmp_path / "areas.json")]) == 0
    assert (tmp_path / "areas-map.html").stat().st_size > 2000
    assert main(["view", "-i", str(tmp_path / "areas.geojson"), "-o", str(tmp_path / "from-geojson.html")]) == 0
    assert (tmp_path / "from-geojson.html").stat().st_size > 2000


def test_cli_reports_config_errors(tmp_path, capsys):
    source = tmp_path / "in.csv"
    write_csv(source, [("u4pruy", 1)])
    code = main(
        ["build", "-i", str(source), "-o", str(tmp_path), "--min-area-weight", "10", "--max-area-weight", "5", "-q"]
    )
    assert code == 2
    assert "min_area_weight" in capsys.readouterr().err


def test_cli_tiles_option(tmp_path, capsys):
    source = tmp_path / "in.csv"
    write_csv(source, uniform_block(4, 4).items())
    assert (
        main(
            [
                "build",
                "-i",
                str(source),
                "-o",
                str(tmp_path),
                "--min-area-weight",
                "30",
                "--max-area-weight",
                "60",
                "--no-json",
                "--tiles",
                "opentopomap",
                "-q",
            ]
        )
        == 0
    )
    page = (tmp_path / "areas-map.html").read_text()
    assert "opentopomap.org" in page and '"fileFallback":null' in page
    code = main(
        [
            "build",
            "-i",
            str(source),
            "-o",
            str(tmp_path),
            "--min-area-weight",
            "30",
            "--max-area-weight",
            "60",
            "--no-json",
            "--tiles",
            "https://t.example.com/{z}/{x}/{y}.png",
            "-q",
        ]
    )
    assert code == 2 and "attribution" in capsys.readouterr().err
