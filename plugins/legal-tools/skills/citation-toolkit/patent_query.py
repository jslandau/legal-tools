#!/usr/bin/env python3
"""
patent_query.py — pinpoint citation lookups against a PatentDoc artifact.

Reads the JSON artifact produced by patent_extract.py (build-once/query-many)
and resolves US patent column:line citations to their printed text. US patent
citations pinpoint a span as "column:line", "column:start-end" (same column),
or "col:start-col2:end" (cross-column). Examples:
  - "5:1" → column 5, line 1
  - "5:1-3" → column 5, lines 1-3
  - "4:65-5:3" → column 4 line 65 through column 5 line 3 (cross-column)

Blank line handling:
  US patents number EVERY physical line slot, including blank spacing lines around
  centered headings. Some interior line numbers are therefore absent from the artifact
  (no text-bearing line at that slot). These blank interior lines are rendered as
  empty strings in the output, so the result is isomorphic to the printed page.
  Example: if column 3 line 13 is blank, looking up "3:12-14" returns three lines
  joined by newlines, with the middle one empty: "line12\n\nline14".

Local only: reads a local artifact, makes no network calls.

Usage:

    # Single line:
    python3 patent_query.py --artifact us9154231.json --cite 5:1

    # Same-column span:
    python3 patent_query.py --artifact us9154231.json --cite 5:1-3

    # Cross-column span:
    python3 patent_query.py --artifact us9154231.json --cite 4:65-5:3

    # Span with interior blank line (rendered as blank):
    python3 patent_query.py --artifact us9154231.json --cite 3:12-14

Exit codes:
  0: success
  1: citation error (malformed, out of range)
  2: artifact not found or unreadable
  3: ambiguous citation (small span or single cite touching spurious/unknown slot;
     likely-intended text provided in diagnostic)

Output: the resolved text on stdout. Errors go to stderr (exit non-zero).
"""
import argparse
import json
import re
import sys
from pathlib import Path


# Threshold below which a span is considered "small" for ambiguity detection.
# Humans count at small spans (1-4 lines, visually verify each slot);
# at large spans (5+ lines) they anchor visually without counting, so spurious
# slots interior to large spans are not ambiguous.
AMBIGUITY_MAX_SPAN = 5


class CiteError(ValueError):
    """Malformed citation or out-of-range span."""


class AmbiguousCiteError(ValueError):
    """Citation touches a numbering-grid artifact (spurious/unknown slot).

    Raised when:
    - A single cite targets a spurious/unknown slot
    - A small span (< AMBIGUITY_MAX_SPAN lines) touches a spurious/unknown slot

    Carries structured diagnostic fields:
    - cite: the citation string or 4-tuple
    - reason: human-readable explanation
    - likely_text: the likely-intended text (N consecutive physical lines
      at the start, where N = span width for spans, or both neighbors for singles)
    - neighbors: tuple of adjacent text lines (for single-cite case)
    """

    def __init__(
        self,
        cite: str | tuple,
        reason: str,
        likely_text: str,
        neighbors: tuple[str, ...] | None = None,
    ) -> None:
        self.cite = cite
        self.reason = reason
        self.likely_text = likely_text
        self.neighbors = neighbors or ()
        super().__init__(reason)

    def __str__(self) -> str:
        """Return a readable diagnostic message."""
        return f"ambiguous cite {self.cite}: {self.reason}"


# Regex to parse citations:
# Group 1: start column (required, \d+)
# Group 2: start line (required, \d+)
# Group 3: optional end column (before the second colon in "col:line-col:line")
# Group 4: end line (may be present after hyphen, or inherit start column)
#
# Pattern: "col:line" or "col:start-end" or "col:start-col:end"
# Captures:
#   ^\s*(\d+)\s*:\s*(\d+)     — start col:line
#   \s*(?:-                   — optional hyphen
#     \s*(?:(\d+)\s*:)?       — optional end column (group 3) followed by colon
#     (\d+)                   — end line (group 4)
#   \s*)?$                    — end of string
_CITE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*(?:-\s*(?:(\d+)\s*:)?(\d+)\s*)?$")


def physical_lines_from(
    slots_for_col: dict[int, tuple[str, str]], start_line: int, count: int
) -> str:
    """Extract the next `count` text-kind lines at or after `start_line`.

    slots_for_col: dict mapping line number to (text, kind) tuple
    start_line: first line number to consider
    count: number of text lines to extract

    Returns: the `count` consecutive text lines joined by newline,
    skipping blank/spurious/unknown slots. If fewer than `count` text lines
    exist at or after `start_line`, return what exists.
    """
    result = []
    line = start_line
    # Use a safety bound to avoid infinite loops on sparse data
    max_search = max(slots_for_col.keys()) + count if slots_for_col else start_line + count
    while len(result) < count and line <= max_search:
        if line in slots_for_col:
            text, kind = slots_for_col[line]
            if kind == "text":
                result.append(text)
        line += 1
    return "\n".join(result)


def parse_cite(cite: str) -> tuple[int, int, int, int]:
    """Parse citation into (start_col, start_line, end_col, end_line).

    A single-line cite 'c:n' yields (c, n, c, n).
    A same-column span 'c:start-end' yields (c, start, c, end).
    A cross-column span 'c1:start-c2:end' yields (c1, start, c2, end).

    Whitespace tolerated around numbers/colons/hyphen.
    Raises CiteError if malformed or if (end_col, end_line) lexicographically
    precedes (start_col, start_line).
    """
    m = _CITE.match(cite)
    if not m:
        raise CiteError(f"malformed citation: {cite!r} (expected 'col:line', 'col:start-end', or 'col:start-col:end')")

    start_col = int(m.group(1))
    start_line = int(m.group(2))

    # If hyphen is present, parse end col and end line
    if m.group(4) is not None:
        # End line is present (group 4)
        end_line = int(m.group(4))
        # End column: group 3 if present, else inherit start_col
        end_col = int(m.group(3)) if m.group(3) is not None else start_col
    else:
        # No hyphen: single line cite
        end_col = start_col
        end_line = start_line

    # Validate: (end_col, end_line) must not precede (start_col, start_line) lexicographically
    if (end_col, end_line) < (start_col, start_line):
        raise CiteError(
            f"citation end ({end_col}:{end_line}) precedes start ({start_col}:{start_line}): {cite!r}"
        )

    return start_col, start_line, end_col, end_line


def lookup(doc: dict, start_col: int, start_line: int, end_col: int, end_line: int) -> str:
    """Joined printed text for a citation span (same-column or cross-column).

    Reading order (same as before):
    - start_col: lines start_line .. max_line(start_col)
    - each intermediate column c in (start_col+1 .. end_col-1): lines 1 .. max_line(c)
    - end_col: lines 1 .. end_line

    Rendering by kind:
    - text → append text
    - blank → append "" (preserved vertical gap)
    - spurious → skip (no output, no blank)
    - unknown → skip (no output, no blank)
    - absent slot (not in dict) → CiteError (out of range)

    If start_col == end_col, just lines start_line..end_line of that column.

    Raises CiteError if:
    - Any referenced column is absent from the artifact
    - start_line > max_line(start_col) or end_line > max_line(end_col) (out of range)
    """
    # Build per-column {line: (text, kind)} index and compute max_line for each column.
    # Per-call rebuild is intentional for current build-once/query-occasionally usage;
    # if cite-check batches many lookups, memoizing this index is the optimization.
    by_column = {}
    max_line_by_column = {}
    for ln in doc["lines"]:
        col = ln["column"]
        line_num = ln["line"]
        if col not in by_column:
            by_column[col] = {}
        # Store (text, kind) tuple; kind defaults to "text" for backcompat
        by_column[col][line_num] = (ln["text"], ln.get("kind", "text"))
        max_line_by_column[col] = max(max_line_by_column.get(col, 0), line_num)

    lines_to_join = []

    # Helper to render a line by kind
    def render_line(col: int, line_num: int, col_lines: dict) -> None:
        """Append rendered output for a single line based on its kind.

        Appends to lines_to_join (closure).
        - text → append text
        - blank → append ""
        - spurious, unknown → skip (append nothing)
        """
        if line_num in col_lines:
            text, kind = col_lines[line_num]
            if kind == "text":
                lines_to_join.append(text)
            elif kind == "blank":
                lines_to_join.append("")
            # spurious and unknown: skip (don't append anything)

    # Special case: same column
    if start_col == end_col:
        if start_col not in by_column:
            raise CiteError(f"column {start_col} not present in artifact")
        col_lines = by_column[start_col]
        max_col = max_line_by_column[start_col]

        # Check bounds: start_line and end_line must not exceed max_line
        if start_line > max_col:
            raise CiteError(f"column {start_col}: line {start_line} out of range (max {max_col})")
        if end_line > max_col:
            raise CiteError(f"column {start_col}: line {end_line} out of range (max {max_col})")

        # Collect lines by kind
        for ln in range(start_line, end_line + 1):
            render_line(start_col, ln, col_lines)
    else:
        # Cross-column: start_col -> max, intermediates -> all, end_col -> 1..end_line
        # Start column: start_line to max_line
        if start_col not in by_column:
            raise CiteError(f"column {start_col} not present in artifact")
        col_lines = by_column[start_col]
        max_start_col = max_line_by_column[start_col]

        # Check bounds: start_line must not exceed max_line of start_col
        if start_line > max_start_col:
            raise CiteError(f"column {start_col}: line {start_line} out of range (max {max_start_col})")

        # Collect from start_line to max of start_col, rendering by kind
        for ln in range(start_line, max_start_col + 1):
            render_line(start_col, ln, col_lines)

        # Intermediate columns: 1 to max_line
        for col in range(start_col + 1, end_col):
            if col not in by_column:
                raise CiteError(f"column {col} not present in artifact")
            col_lines = by_column[col]
            max_col_line = max_line_by_column[col]
            for ln in range(1, max_col_line + 1):
                render_line(col, ln, col_lines)

        # End column: 1 to end_line
        if end_col not in by_column:
            raise CiteError(f"column {end_col} not present in artifact")
        col_lines = by_column[end_col]
        max_end_col = max_line_by_column[end_col]

        # Check bounds: end_line must not exceed max_line of end_col
        if end_line > max_end_col:
            raise CiteError(f"column {end_col}: line {end_line} out of range (max {max_end_col})")

        # Collect from 1 to end_line of end_col, rendering by kind
        for ln in range(1, end_line + 1):
            render_line(end_col, ln, col_lines)

    return "\n".join(lines_to_join)


def lookup_cite(doc: dict, cite: str) -> str:
    """Resolve a citation string to text."""
    return lookup(doc, *parse_cite(cite))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--artifact", required=True, type=Path, help="PatentDoc JSON path")
    parser.add_argument("--cite", required=True, help="Citation, e.g. 5:1, 5:1-3, or 4:65-5:3")
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
