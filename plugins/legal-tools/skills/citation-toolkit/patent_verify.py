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


def rejoin_hyphen_splits(lines: list[str]) -> list[str]:
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

    Args:
        lines: List of normalized line strings in reading order.

    Returns:
        List of line strings with hyphens rejoined where appropriate.
        One entry per original line (minus dropped empty remainders).
    """
    if not lines:
        return []

    result = []
    i = 0
    while i < len(lines):
        current = lines[i]
        i += 1

        # Process current line, potentially multiple times if it gains words
        # from successive splits
        while i < len(lines) and current.endswith("-"):
            next_line = lines[i]
            # Check if next line starts with lowercase ASCII letter
            if next_line and next_line[0].islower() and next_line[0].isascii():
                # This is a split: extract the first word from next line
                space_index = next_line.find(" ")
                if space_index == -1:
                    # Entire next line is one word; no remainder
                    moved_word = next_line
                    remainder = ""
                else:
                    # Split at first space
                    moved_word = next_line[:space_index]
                    remainder = next_line[space_index + 1:]  # Skip the space itself

                # Rejoin: drop the trailing hyphen, append the moved word
                current = current[:-1] + moved_word
                i += 1

                # If there's a remainder, we'll emit it and continue
                if remainder:
                    result.append(current)
                    current = remainder
                # If no remainder, keep extending current with next-next line
            else:
                # No split condition met: stop processing this line
                break

        # Emit the final form of current line
        result.append(current)

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
    3. Rejoin line-break hyphens while tracking index entries.
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

    # Step 3 & 4: Rejoin hyphens and build index in parallel
    # We redo the rejoin logic here to track which original line each output line
    # comes from, so we can build accurate index entries.
    emitted_lines = []
    index_entries = []

    i = 0
    while i < len(normalized_texts):
        current = normalized_texts[i]
        current_col, current_line = metadata[i]
        i += 1

        # Process current line, potentially merging with following lines
        while i < len(normalized_texts) and current.endswith("-"):
            next_text = normalized_texts[i]
            if next_text and next_text[0].islower() and next_text[0].isascii():
                # Merge: extract first word from next
                space_index = next_text.find(" ")
                if space_index == -1:
                    moved_word = next_text
                    remainder = ""
                else:
                    moved_word = next_text[:space_index]
                    remainder = next_text[space_index + 1:]

                # Rejoin current
                current = current[:-1] + moved_word
                i += 1

                # If there's a remainder, emit current and continue with remainder
                if remainder:
                    emitted_lines.append(current)
                    # Record this line's column and line number
                    index_entries.append((current_col, current_line))
                    current = remainder
                # If no remainder, continue extending current with next-next
            else:
                break

        # Emit final form of current
        emitted_lines.append(current)
        index_entries.append((current_col, current_line))

    # Step 5: Build blob and calculate offsets
    blob = " ".join(emitted_lines)
    index = []
    char_offset = 0
    for col, line in index_entries:
        index.append((char_offset, col, line))
        # Move offset forward by this line's length + 1 (for space separator)
        line_idx = len(index) - 1
        char_offset += len(emitted_lines[line_idx]) + 1

    # Remove the trailing +1 from the last offset (no space after last line)
    if index:
        last_char_offset, last_col, last_line = index[-1]
        index[-1] = (last_char_offset, last_col, last_line)

    return blob, index
