"""Minimal IFC STEP (ISO 10303-21) reader built on the standard library."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

GUID_CHARS = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$")

ALIASES = {
    "IFCWALL": {"IFCWALL", "IFCWALLSTANDARDCASE"},
    "IFCDOOR": {"IFCDOOR", "IFCDOORSTANDARDCASE"},
    "IFCWINDOW": {"IFCWINDOW", "IFCWINDOWSTANDARDCASE"},
    "IFCSLAB": {"IFCSLAB", "IFCSLABSTANDARDCASE", "IFCSLABELEMENTEDCASE"},
    "IFCBEAM": {"IFCBEAM", "IFCBEAMSTANDARDCASE"},
    "IFCCOLUMN": {"IFCCOLUMN", "IFCCOLUMNSTANDARDCASE"},
}

_REF = re.compile(r"#(\d+)")
_ENUM = re.compile(r"\.([A-Z0-9_]+)\.")
_NUM = re.compile(r"-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?")
_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
_HEAD = re.compile(r"#(\d+)\s*=\s*([A-Za-z0-9_]+)\s*\(")


@dataclass(frozen=True)
class Ref:
    id: int


@dataclass(frozen=True)
class Enum:
    name: str


@dataclass(frozen=True)
class Typed:
    type: str
    value: object


@dataclass
class Entity:
    id: int
    type: str
    args: list = field(default_factory=list)

    def arg(self, index: int):
        return self.args[index] if index < len(self.args) else None

    @property
    def name(self) -> str:
        value = self.arg(2)
        return value if isinstance(value, str) else ""

    @property
    def label(self) -> str:
        """First string argument, used by IfcMaterial and property entities."""
        value = self.arg(0)
        return value if isinstance(value, str) else ""

    @property
    def global_id(self) -> str:
        value = self.arg(0)
        return value if isinstance(value, str) else ""


class ParseError(ValueError):
    pass


def _decode(text: str) -> str:
    """Decode the STEP escapes X2 (UTF-16 hex) and X (one byte)."""
    text = re.sub(r"\\X2\\((?:[0-9A-Fa-f]{4})+)\\X0\\",
                  lambda m: "".join(chr(int(m.group(1)[i:i + 4], 16)) for i in range(0, len(m.group(1)), 4)), text)
    return re.sub(r"\\X\\([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), text)


class _Reader:
    def __init__(self, text: str):
        self.t = text
        self.i = 0

    def ws(self):
        while self.i < len(self.t) and self.t[self.i] in " \t\r\n":
            self.i += 1

    def value(self):
        self.ws()
        if self.i >= len(self.t):
            raise ParseError("unexpected end of arguments")
        c = self.t[self.i]
        if c == "(":
            return self.list()
        if c == "'":
            return self.string()
        if c == "#":
            m = _REF.match(self.t, self.i)
            if not m:
                raise ParseError("bad reference")
            self.i = m.end()
            return Ref(int(m.group(1)))
        if c == "$":
            self.i += 1
            return None
        if c == "*":
            self.i += 1
            return "*"
        if c == ".":
            m = _ENUM.match(self.t, self.i)
            if not m:
                raise ParseError("bad enumeration")
            self.i = m.end()
            return Enum(m.group(1))
        m = _NUM.match(self.t, self.i)
        if m:
            self.i = m.end()
            raw = m.group(0)
            return float(raw) if any(ch in raw for ch in ".eE") else int(raw)
        m = _NAME.match(self.t, self.i)
        if m:
            self.i = m.end()
            self.ws()
            if self.i < len(self.t) and self.t[self.i] == "(":
                inner = self.list()
                return Typed(m.group(0), inner[0] if len(inner) == 1 else inner)
            return Enum(m.group(0))
        raise ParseError(f"unexpected character {c!r}")

    def string(self):
        self.i += 1
        out = []
        while self.i < len(self.t):
            c = self.t[self.i]
            if c == "'":
                if self.t[self.i + 1:self.i + 2] == "'":
                    out.append("'")
                    self.i += 2
                    continue
                self.i += 1
                return _decode("".join(out))
            out.append(c)
            self.i += 1
        raise ParseError("unterminated string")

    def list(self):
        self.i += 1
        items = []
        self.ws()
        if self.t[self.i:self.i + 1] == ")":
            self.i += 1
            return items
        while True:
            items.append(self.value())
            self.ws()
            c = self.t[self.i:self.i + 1]
            self.i += 1
            if c == ")":
                return items
            if c != ",":
                raise ParseError("expected comma or close bracket")


def _statements(data: str):
    """Split the DATA section into statements on semicolons outside strings."""
    buf, in_str, i = [], False, 0
    while i < len(data):
        c = data[i]
        if not in_str and data.startswith("/*", i):
            end = data.find("*/", i + 2)
            i = len(data) if end < 0 else end + 2
            continue
        if c == "'":
            in_str = not in_str
        if c == ";" and not in_str:
            yield "".join(buf).strip()
            buf = []
        else:
            buf.append(c)
        i += 1


class Model:
    """Parsed IFC file with lookups for the relationships these tools need."""

    def __init__(self, entities: dict[int, Entity], header: str = "", schema: str = ""):
        self.entities = entities
        self.header = header
        self.schema = schema
        self._by_type: dict[str, list[Entity]] = {}
        for e in entities.values():
            self._by_type.setdefault(e.type, []).append(e)
        self._rel_index()

    def by_type(self, *types: str) -> list[Entity]:
        wanted: set[str] = set()
        for t in types:
            t = t.upper()
            wanted |= ALIASES.get(t, {t})
        out = [e for t in wanted for e in self._by_type.get(t, [])]
        return sorted(out, key=lambda e: e.id)

    def get(self, ref) -> Entity | None:
        return self.entities.get(ref.id) if isinstance(ref, Ref) else None

    def _rel_index(self):
        self._psets: dict[int, list[Entity]] = {}
        self._container: dict[int, Entity] = {}
        self._material: dict[int, Entity] = {}
        self._parent: dict[int, Entity] = {}
        for rel in self.by_type("IFCRELDEFINESBYPROPERTIES"):
            target = self.get(rel.arg(5))
            for r in rel.arg(4) or []:
                if target is not None and isinstance(r, Ref):
                    self._psets.setdefault(r.id, []).append(target)
        for rel in self.by_type("IFCRELCONTAINEDINSPATIALSTRUCTURE"):
            holder = self.get(rel.arg(5))
            for r in rel.arg(4) or []:
                if holder is not None and isinstance(r, Ref):
                    self._container[r.id] = holder
        for rel in self.by_type("IFCRELASSOCIATESMATERIAL"):
            mat = self.get(rel.arg(5))
            for r in rel.arg(4) or []:
                if mat is not None and isinstance(r, Ref):
                    self._material[r.id] = mat
        for rel in self.by_type("IFCRELAGGREGATES"):
            parent = self.get(rel.arg(4))
            for r in rel.arg(5) or []:
                if parent is not None and isinstance(r, Ref):
                    self._parent[r.id] = parent

    def container(self, e: Entity) -> Entity | None:
        return self._container.get(e.id) or self._parent.get(e.id)

    def material(self, e: Entity) -> Entity | None:
        return self._material.get(e.id)

    def properties(self, e: Entity) -> dict[str, dict[str, object]]:
        """Property sets as {set name: {property name: value}}."""
        out: dict[str, dict[str, object]] = {}
        for pset in self._psets.get(e.id, []):
            if pset.type != "IFCPROPERTYSET":
                continue
            props: dict[str, object] = {}
            for r in pset.arg(4) or []:
                p = self.get(r)
                if p is not None and p.type == "IFCPROPERTYSINGLEVALUE":
                    v = p.arg(2)
                    if isinstance(v, Typed):
                        v = v.value
                    if isinstance(v, Enum):
                        v = {"T": True, "F": False}.get(v.name, v.name)
                    props[str(p.arg(0))] = v
            out.setdefault(pset.name, {}).update(props)
        return out

    def quantities(self, e: Entity) -> dict[str, float]:
        """Quantities from IfcElementQuantity as {quantity name: number}."""
        out: dict[str, float] = {}
        for qset in self._psets.get(e.id, []):
            if qset.type != "IFCELEMENTQUANTITY":
                continue
            for r in qset.arg(5) or []:
                q = self.get(r)
                if q is not None and q.type.startswith("IFCQUANTITY"):
                    v = q.arg(3)
                    if isinstance(v, (int, float)):
                        out[str(q.arg(0))] = float(v)
        return out

    def storey(self, e: Entity) -> Entity | None:
        node, seen = self.container(e), 0
        while node is not None and node.type != "IFCBUILDINGSTOREY" and seen < 20:
            node, seen = self.container(node), seen + 1
        return node if node is not None and node.type == "IFCBUILDINGSTOREY" else None


def parse(text: str) -> Model:
    if "ISO-10303-21" not in text[:200]:
        raise ParseError("not an IFC STEP file (missing ISO-10303-21 header)")
    start = text.find("DATA;")
    end = text.rfind("ENDSEC;")
    if start < 0 or end < start:
        raise ParseError("missing DATA section")
    header = text[:start]
    schema = ""
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", header)
    if m:
        schema = m.group(1)
    entities: dict[int, Entity] = {}
    for stmt in _statements(text[start + 5:end]):
        if not stmt:
            continue
        m = _HEAD.match(stmt)
        if not m:
            continue
        reader = _Reader(stmt)
        reader.i = m.end() - 1
        try:
            args = reader.list()
        except (ParseError, IndexError) as exc:
            raise ParseError(f"entity #{m.group(1)}: {exc}") from exc
        entities[int(m.group(1))] = Entity(int(m.group(1)), m.group(2).upper(), args)
    return Model(entities, header, schema)


def load(path: str) -> Model:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return parse(handle.read())
