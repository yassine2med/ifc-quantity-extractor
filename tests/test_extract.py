import csv
from pathlib import Path

import pytest

from ifcqty.__main__ import main
from ifcqty.extract import element_rows, format_table, group, write_csv
from ifcqty.ifc import ParseError, parse

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample_office.ifc"


@pytest.fixture(scope="module")
def model():
    return parse(SAMPLE.read_text())


@pytest.fixture(scope="module")
def rows(model):
    return element_rows(model)


def by_type(rows, kind):
    return [r for r in rows if r.type == kind]


def test_row_count(rows):
    assert len(rows) == 26


def test_wall_length_in_metres(rows):
    first = by_type(rows, "IFCWALL")[0]
    assert first.name == "Exterior Wall N1"
    assert first.length_m == 12.0


def test_wall_volume_and_area(rows):
    first = by_type(rows, "IFCWALL")[0]
    assert (first.area_m2, first.volume_m3) == (43.2, 8.64)


def test_door_area_from_width_and_height(rows):
    assert [r.area_m2 for r in by_type(rows, "IFCDOOR")] == [1.89, 1.89, 2.1]


def test_space_area(rows):
    assert sum(r.area_m2 for r in by_type(rows, "IFCSPACE")) == 125.5


def test_storey_assigned_through_aggregation(rows):
    spaces = {r.name: r.storey for r in by_type(rows, "IFCSPACE")}
    assert spaces["Conference Hall"] == "Level 2"


def test_orphan_wall_has_no_storey(rows):
    assert [r.storey for r in rows if r.name == "Orphan Wall X1"] == ["(none)"]


def test_material_shown(rows):
    assert {r.material for r in by_type(rows, "IFCWINDOW")} == {"Glass"}


def test_group_by_type_counts(rows):
    totals = {g["key"][0]: g["count"] for g in group(rows, "type")}
    assert totals["IFCWALL"] == 8 and totals["IFCCOLUMN"] == 2


def test_group_by_storey(rows):
    totals = {g["key"][0]: g["count"] for g in group(rows, "storey")}
    assert totals == {"(none)": 1, "Level 1": 16, "Level 2": 9}


def test_unit_metres_changes_scale(model):
    rows_m = element_rows(model, "m")
    assert by_type(rows_m, "IFCWALL")[0].length_m == 12000.0


def test_bad_unit_and_group(model, rows):
    with pytest.raises(ValueError):
        element_rows(model, "ft")
    with pytest.raises(ValueError):
        group(rows, "colour")


def test_table_has_total_count(rows):
    text = format_table(group(rows, "type"), "type")
    assert text.splitlines()[-1].split()[:2] == ["TOTAL", "26"]


def test_csv_written(rows, tmp_path):
    out = tmp_path / "q.csv"
    assert write_csv(rows, str(out)) == 26
    with open(out, newline="") as handle:
        data = list(csv.DictReader(handle))
    assert data[0]["name"] == "Exterior Wall N1"


def test_cli_codes(capsys, tmp_path):
    assert main(["summary", str(SAMPLE)]) == 0
    assert main(["summary", str(SAMPLE.parent / "none.ifc")]) == 2
    assert main(["elements", str(SAMPLE), "--type", "IFCCOLUMN"]) == 0
    assert main(["elements", str(SAMPLE), "--type", "IFCPUMP"]) == 2
    bad = tmp_path / "bad.ifc"
    bad.write_text("not ifc")
    assert main(["summary", str(bad)]) == 2


def test_parser_rejects_non_ifc():
    with pytest.raises(ParseError):
        parse("hello")
