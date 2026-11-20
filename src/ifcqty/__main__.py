"""Command line entry: python -m ifcqty summary|elements|csv."""

from __future__ import annotations

import argparse
import sys

from .extract import ELEMENT_TYPES, element_rows, format_table, group, write_csv
from .ifc import ParseError, load


def main(argv: list[str] | None = None) -> int:
    """Return 0 on success, 1 when no elements match, 2 on a bad or missing file."""
    parser = argparse.ArgumentParser(prog="ifcqty", description="Quantity takeoff from IFC STEP files")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("summary", "grouped totals"), ("elements", "one line per element"), ("csv", "write element rows to CSV")):
        p = sub.add_parser(name, help=text)
        p.add_argument("file")
        p.add_argument("--unit", default="mm", choices=["mm", "cm", "m"], help="length unit used in the file (default mm)")
        p.add_argument("--type", help="only this IFC type, for example IFCWALL")
        if name == "summary":
            p.add_argument("--by", default="type", choices=["type", "storey", "material", "storey-type"])
        if name == "csv":
            p.add_argument("--out", required=True, help="output CSV path")
    args = parser.parse_args(argv)

    try:
        rows = element_rows(load(args.file), args.unit)
    except FileNotFoundError:
        print(f"File not found: {args.file}", file=sys.stderr)
        return 2
    except ParseError as exc:
        print(f"Cannot read input: {exc}", file=sys.stderr)
        return 2
    if args.type:
        wanted = args.type.upper()
        if wanted not in ELEMENT_TYPES:
            print(f"Unsupported type {wanted}; use one of {', '.join(ELEMENT_TYPES)}", file=sys.stderr)
            return 2
        rows = [r for r in rows if r.type == wanted]
    if not rows:
        print("No matching elements")
        return 1
    if args.command == "summary":
        print(format_table(group(rows, args.by), args.by))
    elif args.command == "elements":
        for r in rows:
            print(f"#{r.id:<4} {r.type:<10} {r.name or '(no name)':<24} {r.storey:<8} "
                  f"L {r.length_m:>7.2f}  A {r.area_m2:>7.2f}  V {r.volume_m3:>6.2f}")
    else:
        print(f"wrote {write_csv(rows, args.out)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
