"""Turn IFC element quantities into takeoff rows and grouped totals."""

from __future__ import annotations

import csv
from dataclasses import dataclass

from .ifc import Model

ELEMENT_TYPES = ["IFCWALL", "IFCDOOR", "IFCWINDOW", "IFCSLAB", "IFCCOLUMN", "IFCBEAM",
                 "IFCCOVERING", "IFCFURNISHINGELEMENT", "IFCSPACE"]
AREA_KEYS = ("NetSideArea", "NetArea", "GrossArea", "NetFloorArea", "GrossFloorArea", "GrossSideArea")
VOLUME_KEYS = ("NetVolume", "GrossVolume")
UNIT_TO_M = {"mm": 0.001, "cm": 0.01, "m": 1.0}


@dataclass(frozen=True)
class Row:
    id: int
    type: str
    name: str
    storey: str
    material: str
    length_m: float
    area_m2: float
    volume_m3: float

    def as_list(self) -> list:
        return [self.id, self.type, self.name, self.storey, self.material,
                self.length_m, self.area_m2, self.volume_m3]


HEADER = ["id", "type", "name", "storey", "material", "length_m", "area_m2", "volume_m3"]


def _first(quantities: dict[str, float], keys) -> float:
    for key in keys:
        if key in quantities:
            return quantities[key]
    return 0.0


def element_rows(model: Model, length_unit: str = "mm") -> list[Row]:
    """One row per element with length (m), area (m2) and volume (m3)."""
    if length_unit not in UNIT_TO_M:
        raise ValueError(f"unknown length unit {length_unit!r}, use one of {sorted(UNIT_TO_M)}")
    scale = UNIT_TO_M[length_unit]
    rows: list[Row] = []
    for kind in ELEMENT_TYPES:
        for e in model.by_type(kind):
            q = model.quantities(e)
            area = _first(q, AREA_KEYS)
            if not area and "Width" in q and "Height" in q and kind in ("IFCDOOR", "IFCWINDOW"):
                area = q["Width"] * q["Height"] * scale * scale
            storey = model.storey(e)
            material = model.material(e)
            rows.append(Row(
                id=e.id, type=e.type, name=e.name,
                storey=storey.name if storey else "(none)",
                material=material.label if material else "(none)",
                length_m=round(q.get("Length", 0.0) * scale, 3),
                area_m2=round(area, 3),
                volume_m3=round(_first(q, VOLUME_KEYS), 3),
            ))
    return rows


def group(rows: list[Row], by: str = "type") -> list[dict]:
    """Totals grouped by type, storey, material, or storey and type."""
    keys = {
        "type": lambda r: (r.type,),
        "storey": lambda r: (r.storey,),
        "material": lambda r: (r.material,),
        "storey-type": lambda r: (r.storey, r.type),
    }
    if by not in keys:
        raise ValueError(f"unknown grouping {by!r}, use one of {sorted(keys)}")
    out: dict[tuple, dict] = {}
    for r in rows:
        k = keys[by](r)
        g = out.setdefault(k, {"key": k, "count": 0, "length_m": 0.0, "area_m2": 0.0, "volume_m3": 0.0})
        g["count"] += 1
        g["length_m"] += r.length_m
        g["area_m2"] += r.area_m2
        g["volume_m3"] += r.volume_m3
    result = sorted(out.values(), key=lambda g: g["key"])
    for g in result:
        for field in ("length_m", "area_m2", "volume_m3"):
            g[field] = round(g[field], 3)
    return result


def format_table(groups: list[dict], by: str) -> str:
    labels = {"type": ["type"], "storey": ["storey"], "material": ["material"], "storey-type": ["storey", "type"]}[by]
    head = labels + ["count", "length_m", "area_m2", "volume_m3"]
    body = [list(g["key"]) + [g["count"], f"{g['length_m']:.2f}", f"{g['area_m2']:.2f}", f"{g['volume_m3']:.2f}"] for g in groups]
    # Areas of different element types mean different things (wall side area, floor area),
    # so the total row only sums the element count.
    total = ["TOTAL"] + [""] * (len(labels) - 1) + [sum(g["count"] for g in groups), "", "", ""]
    table = [head] + body + [total]
    widths = [max(len(str(row[i])) for row in table) for i in range(len(head))]
    lines = []
    for n, row in enumerate(table):
        cells = [str(c).ljust(widths[i]) if i < len(labels) else str(c).rjust(widths[i]) for i, c in enumerate(row)]
        lines.append("  ".join(cells).rstrip())
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def write_csv(rows: list[Row], path: str) -> int:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        for r in rows:
            writer.writerow(r.as_list())
    return len(rows)
