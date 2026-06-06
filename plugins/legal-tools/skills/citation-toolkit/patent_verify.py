#!/usr/bin/env python3
# pattern: Functional Core / Imperative Shell
"""
patent_verify.py — quote-location verification for patent citations.

Normalizes patent artifact text into a clean blob (newline-free concatenation
of normalized text-kind lines) plus an internal (char_offset, column, line)
index for mapping LLM match coordinates back to artifact column:line addresses.

This module performs pure normalization only: no matching, no I/O, no CLI.
The brief's quote and match logic reside in the Imperative Shell (Phase 2+).

Dependency: stdlib only (re, json, argparse, bisect, pathlib). No external packages.
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
from pathlib import Path
from typing import TypedDict

from patent_query import (
    lookup,
    parse_cite,
    AmbiguousCiteError,
    CiteError,
    AMBIGUITY_MAX_SPAN,
)


_WS = re.compile(r"\s+")


class Line(TypedDict):
    """A reconstructed printed line from patent_extract artifact.

    Invariant: text != "" iff kind == "text".
    """
    column: int
    line: int
    text: str
    bbox: tuple[float, float, float, float]
    page_index: int
    kind: str


def normalize_line(text: str) -> str:
    """Collapse internal whitespace runs to a single space and strip ends.

    AC1.1: Runs of spaces/tabs within a line collapse to a single space.
    Leading and trailing whitespace is stripped.
    """
    return _WS.sub(" ", text).strip()


def rejoin_hyphen_splits(
    lines: list[str],
) -> list[str]:
    """Rejoin line-break hyphen splits intelligently.

    AC1.2, AC1.3: When a line ends with `-` and the next line starts with a
    lowercase ASCII letter, this is a line-break word split: drop the trailing
    `-` and move only the next line's first word onto the current line (no space).
    The remainder of the next line (after that word) stays as the next line's entry.

    If the next line starts with uppercase, digit, punctuation, or there is no
    next line, the `-` is preserved (real hyphen / clause boundary / proper noun).

    Only the trailing (line-end) hyphen is considered. Mid-line hyphens are
    never at a line end, so they are inherently untouched.

    PINNED representation: Only the split word fragment moves up, never the
    entire next line. Empty remainders are dropped from the result so they
    don't contribute zero-width index entries.

    This is a thin wrapper over rejoin_hyphen_splits_with_metadata() that provides
    a clean string-list interface while reusing the canonical rejoin algorithm.

    Args:
        lines: List of normalized line strings in reading order.

    Returns:
        List of line strings with hyphens rejoined where appropriate.
        One entry per original line (minus dropped empty remainders).
    """
    # Create dummy metadata: each line tagged with a unique line number (column 0).
    # The metadata values don't matter for the rejoin logic; we only care about
    # the text sequences. Using (0, i) for each line keeps metadata uniform but distinct.
    metadata = [(0, i) for i in range(len(lines))]

    # Call the canonical helper with dummy metadata
    result_with_metadata = rejoin_hyphen_splits_with_metadata(lines, metadata)

    # Extract just the text from (text, column, line) tuples
    return [text for text, _, _ in result_with_metadata]


def rejoin_hyphen_splits_with_metadata(
    texts: list[str], metadata: list[tuple[int, int]]
) -> list[tuple[str, int, int]]:
    """Rejoin line-break hyphen splits while tracking source coordinates.

    This is the shared core for both rejoin_hyphen_splits and build_blob_and_index.
    It processes the same rejoin logic as rejoin_hyphen_splits, but emits
    (text, column, line) tuples so the caller knows which source line each
    output text came from.

    CRITICAL FIX: When a remainder is emitted (a line whose first word was
    pulled into the prior line), it is tagged with its own source line's
    metadata, NOT the prior line's metadata.

    Args:
        texts: List of normalized line texts in reading order.
        metadata: List of (column, line) tuples, one per text, in reading order.

    Returns:
        List of (text, column, line) tuples with hyphens rejoined.
        One entry per original text (minus dropped empty remainders).
    """
    if not texts:
        return []

    result = []
    i = 0
    while i < len(texts):
        current_text = texts[i]
        current_col, current_line = metadata[i]
        i += 1

        # Process current line, potentially merging with following lines
        while i < len(texts) and current_text.endswith("-"):
            next_text = texts[i]
            next_col, next_line = metadata[i]

            # Check if next line starts with lowercase ASCII letter
            if next_text and next_text[0].islower() and next_text[0].isascii():
                # This is a split: extract the first word from next line
                space_index = next_text.find(" ")
                if space_index == -1:
                    # Entire next line is one word; no remainder
                    moved_word = next_text
                    remainder = ""
                else:
                    # Split at first space
                    moved_word = next_text[:space_index]
                    remainder = next_text[space_index + 1:]

                # Rejoin: drop the trailing hyphen, append the moved word
                current_text = current_text[:-1] + moved_word
                i += 1

                # If there's a remainder, emit current and continue with remainder
                if remainder:
                    result.append((current_text, current_col, current_line))
                    # CRITICAL FIX: Remainder is tagged with the line it came from
                    current_text = remainder
                    current_col, current_line = next_col, next_line
                # If no remainder, keep extending current with next-next line
            else:
                # No split condition met: stop processing this line
                break

        # Emit final form of current
        result.append((current_text, current_col, current_line))

    return result


def build_blob_and_index(lines: list[Line]) -> tuple[str, list[tuple[int, int, int]]]:
    """Build a clean blob and offset index from artifact lines.

    AC1.4: Filters to text-kind lines only (blank/spurious/unknown omitted).
    AC2.1: Blob contains no newlines (lines joined with single space).
    AC2.2: Every character of every text line is preserved in reading order
           (modulo collapsed whitespace and dropped line-break hyphens).

    Steps:
    1. Filter to kind == "text" lines.
    2. Normalize each line's text (collapse whitespace, strip ends).
    3. Rejoin line-break hyphens using shared helper, tracking source coordinates.
    4. Concatenate into a single blob using space as separator.
    5. Return blob and index with strictly ascending char_offsets.

    The PINNED representation ensures that when a line is split and rejoined:
    - The moved word's characters are counted within the prior line's offset
    - The remainder (if any) gets an offset pointing to its first character
    - Empty remainders are dropped, preventing zero-width entries
    - Offsets are strictly ascending (one entry per non-empty text line)

    Args:
        lines: List of Line dicts from an artifact, in reading order.

    Returns:
        (blob, index) where:
        - blob: newline-free concatenation of normalized text lines
        - index: list of (char_offset, column, line) tuples, one per emitted line
    """
    if not lines:
        return "", []

    # Step 1: Filter to text-kind lines
    text_lines_raw = [line for line in lines if line["kind"] == "text"]
    if not text_lines_raw:
        return "", []

    # Step 2: Normalize and collect metadata
    normalized_texts = [normalize_line(line["text"]) for line in text_lines_raw]
    metadata = [(line["column"], line["line"]) for line in text_lines_raw]

    # Step 3: Rejoin hyphens using shared helper
    # This returns (text, column, line) tuples with correct source coordinates
    emitted_with_metadata = rejoin_hyphen_splits_with_metadata(
        normalized_texts, metadata
    )

    # Extract just the texts for blob building
    emitted_lines = [text for text, _, _ in emitted_with_metadata]

    # Step 4: Build blob
    blob = " ".join(emitted_lines)

    # Step 5: Build index with correct offsets
    index = []
    char_offset = 0
    for text, col, line in emitted_with_metadata:
        index.append((char_offset, col, line))
        # Move offset forward by this line's length + 1 (for space separator)
        char_offset += len(text) + 1

    return blob, index


def resolve_offset(index: list[tuple[int, int, int]], offset: int) -> tuple[int, int]:
    """Resolve a blob character offset to its (column, line) coordinate.

    AC3.1, AC3.2, AC3.5: Map a blob character offset to the (column, line) coordinate
    of the index entry with the greatest char_offset <= offset.

    Uses binary search (bisect_right) to efficiently locate the index entry.
    The entry's column and line fields are returned.

    Args:
        index: List of (char_offset, column, line) tuples, strictly ascending by char_offset.
        offset: The blob character offset to resolve.

    Returns:
        (column, line) from the index entry with the greatest char_offset <= offset.

    Raises:
        ValueError: If index is empty or offset precedes the first index entry (pos < 0).
    """
    if not index:
        raise ValueError("index is empty")

    offsets = [e[0] for e in index]
    return _resolve_in(index, offsets, offset)


def _resolve_in(
    index: list[tuple[int, int, int]], offsets: list[int], offset: int
) -> tuple[int, int]:
    """Resolve an offset against a precomputed offsets list (shared core).

    Lets resolve_span build the offsets list once for both endpoint lookups
    instead of rebuilding it per resolve_offset call.
    """
    pos = bisect.bisect_right(offsets, offset) - 1
    if pos < 0:
        raise ValueError(f"offset {offset} precedes the first index entry")
    return (index[pos][1], index[pos][2])


def resolve_span(
    index: list[tuple[int, int, int]], start: int, end: int
) -> tuple[int, int, int, int]:
    """Resolve an offset span to a coordinate range.

    AC3.3, AC3.4: Map a blob character span [start, end) to a coordinate range
    (start_col, start_line, end_col, end_line).

    The span is half-open: [start, end), where end is exclusive. To ensure
    the span's inclusive last character is resolved correctly, we use end-1
    when resolving the end coordinate. This prevents a span ending exactly at
    a line boundary from "bleeding" into the next line.

    For a single-line match, start and end coordinates will be equal; formatting
    of the output (e.g., "6:59" vs "6:59-6:59") is a caller concern.

    AC3.4 invariant: If an offset falls inside a rejoined word (characters that
    were moved from a later line during hyphenation), the resolve_offset function
    correctly returns the starting line's coordinate (the line where the word
    started), not the source line it was moved from.

    Args:
        index: List of (char_offset, column, line) tuples, strictly ascending by char_offset.
        start: The blob character offset of the span's start (inclusive).
        end: The blob character offset of the span's end (exclusive).

    Returns:
        (start_col, start_line, end_col, end_line) where each is from the respective
        index entry's (column, line) fields.

    Raises:
        ValueError: If index is empty or any offset precedes the first index entry.
    """
    if not index:
        raise ValueError("index is empty")

    offsets = [e[0] for e in index]
    start_col, start_line = _resolve_in(index, offsets, start)
    end_col, end_line = _resolve_in(index, offsets, end - 1)
    return (start_col, start_line, end_col, end_line)


# PHASE 4: QUOTE-LOCATION RESOLUTION WITH DUPLICATE HANDLING


def _find_all(blob: str, needle: str) -> list[int]:
    """Find all non-overlapping start offsets of needle in blob.

    AC6.6: Returns a list of all non-overlapping start offsets of the needle
    in the blob. If needle is empty, returns empty list (defends against
    infinite loop). Matches are non-overlapping: after each match, the search
    continues from the position after the matched text.

    Args:
        blob: The text to search in.
        needle: The substring to search for (may be empty).

    Returns:
        List of start offsets of non-overlapping matches, or empty if none found.
    """
    if not needle:  # Empty needle: return empty list
        return []

    hits = []
    pos = 0
    while True:
        i = blob.find(needle, pos)
        if i == -1:
            break
        hits.append(i)
        pos = i + len(needle)  # Non-overlapping: continue after this match

    return hits


def _fmt(span: tuple[int, int, int, int]) -> str:
    """Format a coordinate span as a string.

    Renders a (start_col, start_line, end_col, end_line) tuple. If it's a
    single line (start_col == end_col and start_line == end_line), renders as
    "c:l". Otherwise renders as "sc:sl-ec:el".

    Args:
        span: Tuple of (start_col, start_line, end_col, end_line).

    Returns:
        Formatted string representation.
    """
    start_col, start_line, end_col, end_line = span
    if start_col == end_col and start_line == end_line:
        return f"{start_col}:{start_line}"
    return f"{start_col}:{start_line}-{end_col}:{end_line}"


def resolve(
    window_blob: str,
    window_index: list[tuple[int, int, int]],
    body_blob: str,
    body_index: list[tuple[int, int, int]],
    substring: str,
    retried: bool = False,
) -> dict:
    """Resolve an LLM-supplied substring to a coordinate via duplicate ladder.

    AC6: Implements a four-step ladder:
    1. Normalize the substring via normalize_line (whitespace collapse, case preserved).
       If normalization yields empty string, return no match.
    2. Search window blob. If exactly one hit, return the coordinate.
    3. If window has no hits, search body blob.
       - Exactly one hit: return the coordinate (body scope).
       - No hits: return no match.
       - Multiple hits: fall through to step 4.
    4. Multiple hits in either scope:
       - If not retried: return ambiguous_match with retry instruction (no found_at).
       - If retried: return ambiguous_match with list of all matched coordinates.

    Args:
        window_blob: Normalized blob text of the window scope.
        window_index: Index for window blob (list of (char_offset, column, line)).
        body_blob: Normalized blob text of the body scope.
        body_index: Index for body blob (list of (char_offset, column, line)).
        substring: The LLM-supplied substring to resolve.
        retried: Flag indicating this is a retry attempt (LLM extended the anchor).

    Returns:
        Dictionary with keys:
        - "found_at": Coordinate string (e.g., "6:59" or "6:59-7:3"), or list of
          coordinate strings if ambiguous_match with retried=True. None if not found.
        - "match_scope": "window" or "body" (only present if found_at is set).
        - "ambiguous_match": True if multiple hits (only if ambiguous).
        - "hits": Count of ambiguous hits (only if ambiguous).
        - "retry": Instruction string (only if ambiguous and not retried).
    """
    # Step 1: Normalize substring
    needle = normalize_line(substring)

    if not needle:
        return {"found_at": None}

    # Step 2: Search window
    window_hits = _find_all(window_blob, needle)

    if len(window_hits) == 1:
        # Unique in window: resolve and return
        span = resolve_span(window_index, window_hits[0], window_hits[0] + len(needle))
        return {
            "found_at": _fmt(span),
            "match_scope": "window",
        }

    # Step 3: If window has no hits, search body
    if len(window_hits) == 0:
        body_hits = _find_all(body_blob, needle)

        if len(body_hits) == 1:
            # Unique in body: resolve and return
            span = resolve_span(body_index, body_hits[0], body_hits[0] + len(needle))
            return {
                "found_at": _fmt(span),
                "match_scope": "body",
            }

        if len(body_hits) == 0:
            # No match anywhere
            return {"found_at": None}

        # Multiple hits in body: fall through to step 4 with body scope
        hits_to_resolve = body_hits
        index_to_use = body_index
    else:
        # Multiple hits in window: fall through to step 4 with window scope
        hits_to_resolve = window_hits
        index_to_use = window_index

    # Step 4: Multiple hits in chosen scope
    if not retried:
        return {
            "ambiguous_match": True,
            "hits": len(hits_to_resolve),
            "retry": "pass a longer/more distinctive substring",
        }

    # Retried: return all hits as list of coordinate strings
    found_at_list = [
        _fmt(resolve_span(index_to_use, hit, hit + len(needle)))
        for hit in hits_to_resolve
    ]
    return {
        "ambiguous_match": True,
        "found_at": found_at_list,
    }


# PHASE 3: WINDOW COMPUTATION AND AMBIGUITY EXPANSION


def _max_line_by_column(doc: dict) -> dict[int, int]:
    """Compute maximum line number for each column in document.

    Args:
        doc: Patent document dict with "lines" key.

    Returns:
        Dictionary mapping column number to its maximum line number.
    """
    max_line_by_column: dict[int, int] = {}
    for ln in doc["lines"]:
        col = ln["column"]
        line_num = ln["line"]
        max_line_by_column[col] = max(max_line_by_column.get(col, 0), line_num)
    return max_line_by_column


def span_width(
    doc: dict, start_col: int, start_line: int, end_col: int, end_line: int
) -> int:
    """Compute the number of slots in a citation span.

    For same-column spans, returns the line count. For cross-column spans,
    counts all slots across the columns in reading order.

    Args:
        doc: Patent document dict.
        start_col, start_line, end_col, end_line: Span coordinates.

    Returns:
        Number of slots (lines) in the span.
    """
    max_line = _max_line_by_column(doc)

    if start_col == end_col:
        # Same column: count lines from start_line to end_line (inclusive)
        return end_line - start_line + 1

    # Cross-column: sum all lines in each column
    width = 0
    # Lines from start_col (start_line to its max)
    width += max_line[start_col] - start_line + 1
    # All lines in intermediate columns
    for col in range(start_col + 1, end_col):
        width += max_line[col]
    # Lines in end_col (1 to end_line)
    width += end_line

    return width


def window_bounds(
    doc: dict, cited: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """Compute the search window for a citation (±10%, min ±1, clamped).

    AC4.1, AC4.2, AC4.3: Expands the cited span by ±10% margin (minimum ±1 line),
    clamped to valid column line ranges.

    Args:
        doc: Patent document dict.
        cited: Citation tuple (start_col, start_line, end_col, end_line).

    Returns:
        Window bounds tuple (start_col, start_line, end_col, end_line).
    """
    start_col, start_line, end_col, end_line = cited
    width = span_width(doc, start_col, start_line, end_col, end_line)
    margin = max(1, int(width * 0.10))
    max_line = _max_line_by_column(doc)

    return (
        start_col,
        max(1, start_line - margin),
        end_col,
        min(max_line[end_col], end_line + margin),
    )


def expanded_bounds(
    doc: dict, cited: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """Compute expanded bounds for ambiguity-triggered widening.

    Uses a larger margin (max(AMBIGUITY_MAX_SPAN, 10% * 3)) to help clear
    the small-span ambiguity gate. This is best-effort grid-drift widening:
    on short columns (near top/bottom boundaries), bottom/top clamps can
    prevent the span from reaching width >= AMBIGUITY_MAX_SPAN. However,
    gather_window does not re-probe the expanded bounds, so the expanded span
    never re-raises the ambiguity gate (even if residual ambiguity persists).

    Args:
        doc: Patent document dict.
        cited: Citation tuple (start_col, start_line, end_col, end_line).

    Returns:
        Expanded bounds tuple (start_col, start_line, end_col, end_line).
    """
    start_col, start_line, end_col, end_line = cited
    width = span_width(doc, start_col, start_line, end_col, end_line)
    # Larger margin: max(AMBIGUITY_MAX_SPAN, 10% of width * 3)
    margin = max(AMBIGUITY_MAX_SPAN, int(width * 0.10) * 3)
    max_line = _max_line_by_column(doc)

    return (
        start_col,
        max(1, start_line - margin),
        end_col,
        min(max_line[end_col], end_line + margin),
    )


def _lines_in_bounds(doc: dict, bounds: tuple[int, int, int, int]) -> list[dict]:
    """Collect Line entries within coordinate bounds in reading order.

    Gathers all Line dicts from doc["lines"] whose (column, line) falls
    within the given bounds, in reading order (start_col from start_line to max,
    intermediate columns fully, end_col up to end_line).

    Args:
        doc: Patent document dict.
        bounds: Coordinate bounds tuple (start_col, start_line, end_col, end_line).

    Returns:
        List of Line dicts in reading order.
    """
    start_col, start_line, end_col, end_line = bounds
    max_line = _max_line_by_column(doc)

    result = []
    # Build a map for efficient lookup
    lines_by_coord = {}
    for ln in doc["lines"]:
        col = ln["column"]
        line_num = ln["line"]
        lines_by_coord[(col, line_num)] = ln

    # Same column: start_line to end_line
    if start_col == end_col:
        for ln in range(start_line, end_line + 1):
            if (start_col, ln) in lines_by_coord:
                result.append(lines_by_coord[(start_col, ln)])
    else:
        # Cross-column: start_col from start_line to its max
        for ln in range(start_line, max_line[start_col] + 1):
            if (start_col, ln) in lines_by_coord:
                result.append(lines_by_coord[(start_col, ln)])

        # Intermediate columns fully
        for col in range(start_col + 1, end_col):
            for ln in range(1, max_line[col] + 1):
                if (col, ln) in lines_by_coord:
                    result.append(lines_by_coord[(col, ln)])

        # End column from 1 to end_line
        for ln in range(1, end_line + 1):
            if (end_col, ln) in lines_by_coord:
                result.append(lines_by_coord[(end_col, ln)])

    return result


def gather_window(doc: dict, cited: tuple[int, int, int, int]) -> dict:
    """Gather window lines, with ambiguity detection and expansion.

    AC5.1: Probes ambiguity on the CITED span (not the widened window).
    If no ambiguity, returns normal window_bounds. If AmbiguousCiteError,
    returns expanded_bounds with ambiguity flags set.

    Args:
        doc: Patent document dict.
        cited: Citation tuple (start_col, start_line, end_col, end_line).

    Returns:
        Dictionary with:
        - window_coord_range: Bounds tuple
        - window_lines: List of Line dicts in the window
        - ambiguity: Boolean (True if ambiguous)
        - ambiguity_reason: String or None

    Raises:
        CiteError: Out-of-range or absent column. Caller (Imperative Shell,
        Phase 5+) handles and converts to error result object.
    """
    # Probe ambiguity on the CITED span only
    try:
        lookup(doc, *cited)
    except AmbiguousCiteError as e:
        # Ambiguity detected: use expanded bounds
        bounds = expanded_bounds(doc, cited)
        return {
            "window_coord_range": bounds,
            "window_lines": _lines_in_bounds(doc, bounds),
            "ambiguity": True,
            "ambiguity_reason": e.reason,
        }

    # No ambiguity: use normal window bounds
    bounds = window_bounds(doc, cited)
    return {
        "window_coord_range": bounds,
        "window_lines": _lines_in_bounds(doc, bounds),
        "ambiguity": False,
        "ambiguity_reason": None,
    }


# PHASE 5: IMPERATIVE SHELL (CLI PRIMITIVES)


def _body_lines(doc: dict) -> list[dict]:
    """Gather all text-kind body lines from document.

    Helper to collect the lines that form the "full document body" for
    quote verification. Filters to kind=="text" lines only.

    Args:
        doc: Patent document dict with "lines" key.

    Returns:
        List of Line dicts with kind=="text", in document order.
    """
    return [ln for ln in doc["lines"] if ln.get("kind", "text") == "text"]


def verify_emit(doc: dict, cite: str) -> dict:
    """Emit a normalized quote for verification.

    Given a patent document and a citation, normalizes the citation and
    computes the surrounding window blob for quote verification, along
    with the full body blob for duplicate detection.

    Args:
        doc: Patent document dict (from patent_extract artifact).
        cite: Citation string (e.g., "5:1-3").

    Returns:
        Dictionary with keys:
        - cite: The input citation string
        - cited_coord: List of 4 integers [start_col, start_line, end_col, end_line]
        - window_coord_range: List of 4 integers [start_col, start_line, end_col, end_line]
        - window_blob: Normalized text of window (no newlines)
        - body_blob: Normalized text of full body (no newlines)
        - ambiguity: Boolean flag
        - ambiguity_reason: String or None

    Raises:
        CiteError: Malformed citation or out-of-range.
    """
    cited = parse_cite(cite)
    gw = gather_window(doc, cited)

    # Build blobs for window and body
    window_blob, _ = build_blob_and_index(gw["window_lines"])
    body_blob, _ = build_blob_and_index(_body_lines(doc))

    return {
        "cite": cite,
        "cited_coord": list(cited),
        "window_coord_range": list(gw["window_coord_range"]),
        "window_blob": window_blob,
        "body_blob": body_blob,
        "ambiguity": gw["ambiguity"],
        "ambiguity_reason": gw["ambiguity_reason"],
    }


def verify_resolve(
    doc: dict, substring: str, within: str, retried: bool
) -> dict:
    """Resolve an LLM-supplied substring to a column:line coordinate.

    Given a document, a substring to find, and a coordinate range to search
    within, resolves the substring to its column:line location.

    Args:
        doc: Patent document dict.
        substring: The text to search for (may have whitespace variations).
        within: Citation string for the search bounds (e.g., "5:1-3").
        retried: Boolean flag indicating if this is a retry with expanded anchor.

    Returns:
        Dictionary from resolve() with keys:
        - found_at: Coordinate string, list of strings, or None
        - match_scope: "window" or "body" (if found_at is set)
        - ambiguous_match: Boolean (if multiple hits)
        - hits: Integer count (if ambiguous)
        - retry: String instruction (if ambiguous and not retried)

    Raises:
        CiteError: Malformed or out-of-range citation bounds.
    """
    bounds = parse_cite(within)
    window_blob, window_index = build_blob_and_index(_lines_in_bounds(doc, bounds))
    body_blob, body_index = build_blob_and_index(_body_lines(doc))

    return resolve(window_blob, window_index, body_blob, body_index, substring, retried)


def process(entries: list[dict]) -> list[dict]:
    """Batch process quote-verification entries.

    Reads a list of entry dicts, each with:
    - id: unique identifier
    - mode: "emit" or "resolve"
    - artifact_path: path to patent_extract artifact JSON
    - (per mode) cite (emit) or substring/within/retried (resolve)

    For each entry:
    1. Load artifact from artifact_path (or error if missing/unreadable)
    2. Dispatch by mode:
       - "emit": call verify_emit(doc, cite)
       - "resolve": call verify_resolve(doc, substring, within, retried)
    3. Append result with id echoed

    A missing artifact or dispatch error yields error result object (not hard exit).

    Args:
        entries: List of entry dicts (each must be a dict, or ValueError raised).

    Returns:
        List of result dicts, one per entry, with id echoed.

    Raises:
        ValueError: If any entry is not a dict.
    """
    results = []

    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(
                f"array element at index {i} is not a dict (got {type(entry).__name__})"
            )

        entry_id = entry.get("id")
        mode = entry.get("mode")

        # Load artifact
        path = Path(entry.get("artifact_path", ""))
        if not path.exists():
            results.append(
                {
                    "id": entry_id,
                    "status": "error",
                    "error": f"no such artifact: {path}",
                }
            )
            continue

        # Try to load artifact JSON
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            results.append(
                {
                    "id": entry_id,
                    "status": "error",
                    "error": f"failed to load artifact: {e}",
                }
            )
            continue

        # Dispatch by mode
        try:
            if mode == "emit":
                result = verify_emit(doc, entry["cite"])
            elif mode == "resolve":
                result = verify_resolve(
                    doc,
                    entry["substring"],
                    entry["within"],
                    bool(entry.get("retried", False)),
                )
            else:
                result = {"status": "error", "error": f"unknown mode: {mode!r}"}
        except (CiteError, KeyError) as e:
            result = {"status": "error", "error": str(e)}

        # Append result with id
        results.append({"id": entry_id, **result})

    return results


def main(argv: list[str]) -> int:
    """CLI entry point for batch quote-verification.

    Reads JSON array from --input file or stdin, processes via process(),
    outputs JSON array to stdout.

    Args:
        argv: Command-line arguments (sys.argv[1:]).

    Returns:
        0 on success, 2 on input/validation error.
    """
    parser = argparse.ArgumentParser(
        description="Verify patent quote location: emit normalized blobs or resolve a matched substring to column:line. Reads a JSON array of requests; writes a JSON array of results to stdout."
    )
    parser.add_argument(
        "--input", help="Path to input JSON file. If omitted, read stdin."
    )
    args = parser.parse_args(argv)

    # Read input
    payload = (
        open(args.input, encoding="utf-8").read()
        if args.input
        else sys.stdin.read()
    )

    # Parse JSON
    try:
        entries = json.loads(payload)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"ERROR: input is not valid JSON: {e}\n")
        return 2

    # Validate array
    if not isinstance(entries, list):
        sys.stderr.write("ERROR: input JSON must be an array of request objects.\n")
        return 2

    # Process
    try:
        results = process(entries)
    except ValueError as e:
        sys.stderr.write(f"ERROR: invalid array element: {e}\n")
        return 2

    # Output
    json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
