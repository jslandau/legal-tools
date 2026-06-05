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


_WS = re.compile(r"\s+")


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
