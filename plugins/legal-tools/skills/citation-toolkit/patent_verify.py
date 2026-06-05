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
