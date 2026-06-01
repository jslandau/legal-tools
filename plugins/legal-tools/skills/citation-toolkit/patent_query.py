#!/usr/bin/env python3
"""
patent_query.py — pinpoint citation lookups against a PatentDoc artifact.

Reads the JSON artifact produced by patent_extract.py (build-once/query-many)
and resolves US patent column:line citations to their printed text. US patent
citations pinpoint a span as "column:line" or "column:start-end" — e.g.
"4:32-38" means column 4, lines 32 through 38.

Local only: reads a local artifact, makes no network calls.

Usage:

    # Single line:
    python3 patent_query.py --artifact us9154231.json --cite 5:1

    # Span:
    python3 patent_query.py --artifact us9154231.json --cite 4:32-38

Output: the resolved text on stdout. Errors go to stderr (exit non-zero).
"""
import argparse
import json
import re
import sys
from pathlib import Path


class CiteError(ValueError):
    """Malformed citation or out-of-range span."""


_CITE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")


def parse_cite(cite: str) -> tuple[int, int, int]:
    """Parse 'col:line' or 'col:start-end' into (column, start_line, end_line).

    A single-line cite 'c:n' yields (c, n, n). Raises CiteError if malformed
    or if end < start.
    """
    m = _CITE.match(cite)
    if not m:
        raise CiteError(f"malformed citation: {cite!r} (expected 'col:line' or 'col:start-end')")
    column = int(m.group(1))
    start = int(m.group(2))
    end = int(m.group(3)) if m.group(3) is not None else start
    if end < start:
        raise CiteError(f"citation end line {end} precedes start line {start}: {cite!r}")
    return column, start, end


def lookup(doc: dict, column: int, start_line: int, end_line: int) -> str:
    """Joined printed text for column, lines start_line..end_line inclusive.

    Raises CiteError if the column is absent or any requested line is missing.
    """
    by_line = {
        ln["line"]: ln["text"]
        for ln in doc["lines"]
        if ln["column"] == column
    }
    if not by_line:
        raise CiteError(f"column {column} not present in artifact")
    missing = [n for n in range(start_line, end_line + 1) if n not in by_line]
    if missing:
        raise CiteError(f"column {column}: line(s) {missing} not present")
    return "\n".join(by_line[n] for n in range(start_line, end_line + 1))


def lookup_cite(doc: dict, cite: str) -> str:
    return lookup(doc, *parse_cite(cite))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--artifact", required=True, type=Path, help="PatentDoc JSON path")
    parser.add_argument("--cite", required=True, help="Citation, e.g. 4:32-38")
    args = parser.parse_args(argv)

    if not args.artifact.exists():
        print(f"error: no such artifact: {args.artifact}", file=sys.stderr)
        return 2
    with open(args.artifact, encoding="utf-8") as f:
        doc = json.load(f)
    try:
        sys.stdout.write(lookup_cite(doc, args.cite) + "\n")
    except CiteError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
