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
