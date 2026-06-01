#!/usr/bin/env python3
"""
patent_extract.py — local US-patent column/line extraction for legal-tools.

Turns a US patent PDF into a structured, queryable artifact mapping every body
line to its printed column:line coordinates. This script BUILDS the artifact;
patent_query.py reads it. US patents number lines continuously within each
column (gutter tick marks every 5 lines); litigation cites them as e.g.
"4:32-38" (column 4, lines 32-38).

Extraction is entirely local — the PDF and its text never leave the machine,
consistent with the legal-tools confidentiality posture (see citation-toolkit
SKILL.md). pdfplumber reads the embedded text layer; no content is transmitted.

This phase implements the `probe` subcommand only (text-layer detection).
Later phases add `build` (full artifact assembly).

Usage:

    # Report whether a PDF has a usable text layer, with per-page word counts:
    python3 patent_extract.py probe --input US9154231.pdf

Output: JSON on stdout. Informational messages and errors go to stderr.

Dependency: `pip install pdfplumber`. The script imports pdfplumber lazily so
`--help` works without the dependency installed. On PEP-668 systems use a venv:
`python3 -m venv .venv && .venv/bin/pip install pdfplumber`.
"""
import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import TypedDict


# --- Source <-> Reconstruction seam -----------------------------------------
# The ONLY shape that differs between the embedded-text path and a future
# image-OCR path. Geometric layers consume Word, never pdfplumber directly.
class Word(TypedDict):
    text: str
    x0: float
    x1: float
    top: float      # distance from top of page (pdfplumber 'top')
    bottom: float


# Body pages carry hundreds of words; image/empty pages carry zero. A document
# with a usable text layer has a substantial total across its pages.
#
# NOTE: this is a DOCUMENT-LEVEL "is there any text layer at all" threshold, and
# is intentionally distinct from Phase 4's per-page MIN_BODY_WORDS (~400), which
# measures whether a single page is a dense two-column body page. Do not merge
# the two — they answer different questions at different scopes.
MIN_TOTAL_WORDS = 50


# linemodel tuning. Derived empirically (2026-05-31) from both sample patents.
CENTER_BAND_FRAC = 0.06     # |word_center_x - page_center| < CENTER_BAND_FRAC * page_width (coarse band for initial selection)
GUTTER_TOLERANCE = 3.0      # |word_center_x - gutter_x| <= GUTTER_TOLERANCE (tight refinement after gutter detection)
MAX_PLAUSIBLE_LINE = 99     # reject center digit tokens above this (body-text numbers like 100/200/300)
MIN_MARKERS_TO_FIT = 3      # need at least 3 distinct-x markers for a meaningful Theil-Sen fit

_DIGITS = re.compile(r"\d{1,3}")


# ============================================================================
# linemodel: Gutter detection and robust line model fitting
# ============================================================================


def _center_x(w: Word) -> float:
    """Horizontal center of a word."""
    return (w["x0"] + w["x1"]) / 2.0


def _y_center(w: Word) -> float:
    """Vertical center of a word."""
    return (w["top"] + w["bottom"]) / 2.0


def _marker_line(
    w: Word,
    page_width: float,
    *,
    band_frac: float = CENTER_BAND_FRAC,
    max_line: int = MAX_PLAUSIBLE_LINE,
) -> int | None:
    """The gutter-marker line value this token represents, or None if it is not
    a marker. THE single source of truth for marker-selection geometry — every
    consumer (select_markers, marker_center_xs, gutter_x, the Phase 5
    orchestrator) routes through this one predicate so the rule cannot drift.

    A token is a marker iff it is: (a) pure digits, (b) within band_frac*width
    of the page center, (c) a positive multiple of 5, (d) <= max_line (rejects
    body-text numbers like 100/200/300 that happen to sit near the center).
    """
    t = w["text"].strip()
    if not _DIGITS.fullmatch(t):
        return None
    if abs(_center_x(w) - page_width / 2.0) >= band_frac * page_width:
        return None
    v = int(t)
    if v <= 0 or v > max_line or v % 5 != 0:
        return None
    return v


def select_markers(
    words: list[Word],
    page_width: float,
    *,
    band_frac: float = CENTER_BAND_FRAC,
    max_line: int = MAX_PLAUSIBLE_LINE,
    gutter_tolerance: float = GUTTER_TOLERANCE,
) -> list[tuple[int, float]]:
    """Center-clustered multiple-of-5 line markers as (line, y_center) pairs.

    Returns sorted, de-duplicated (line, y) pairs. Two-pass selection:
    1. Coarse band filter via _marker_line (operates from page center)
    2. Tight gutter-relative refinement: identify the densest cluster of markers
       (the true gutter), and retain only markers in that cluster.

    The gutter-relative pass is a second-pass refinement that does not change the
    _marker_line predicate itself, allowing Phase 5 and other consumers of _marker_line
    to remain independent. This dual-pass structure separates coarse per-token geometric
    rules (band, digit, multiple-of-5) from page-level gutter-alignment robustness.
    """
    # Pass 1: Coarse selection via _marker_line predicate (band_frac from page center)
    candidates: dict[int, float] = {}
    candidate_xs: dict[int, float] = {}  # Track center-x for gutter refinement
    for w in words:
        v = _marker_line(w, page_width, band_frac=band_frac, max_line=max_line)
        if v is None:
            continue
        # If the same line value appears twice (rare OCR echo), keep the first
        # (the band filter guarantees both echoes sit near center).
        if v not in candidates:
            candidates[v] = _y_center(w)
            candidate_xs[v] = _center_x(w)

    # Pass 2: Gutter-relative refinement via density clustering.
    # Instead of median-then-filter (which fails when candidates split evenly),
    # group candidates into clusters and keep the densest cluster.
    if candidate_xs:
        xs_list = list(candidate_xs.values())
        xs_sorted = sorted(xs_list)

        # Cluster candidates: group xs where members are within gutter_tolerance of the cluster median
        clusters: list[list[float]] = []
        current_cluster: list[float] = []

        for x in xs_sorted:
            if current_cluster:
                # Compute median of current cluster (with new x tentatively added)
                test_cluster = current_cluster + [x]
                test_median = statistics.median(test_cluster)
                # Check if new x is within tolerance of cluster median
                if abs(x - test_median) <= gutter_tolerance:
                    current_cluster.append(x)
                else:
                    # Start a new cluster
                    clusters.append(current_cluster)
                    current_cluster = [x]
            else:
                # First element always starts the cluster
                current_cluster.append(x)

        if current_cluster:
            clusters.append(current_cluster)

        # Pick the densest cluster (largest membership; ties: leftmost/lowest x)
        if clusters:
            densest = max(clusters, key=lambda c: (len(c), -sum(c) / len(c)))
            densest_median = statistics.median(densest)

            # Retain only markers whose center-x is in the densest cluster
            candidates = {
                line: y
                for line, y in candidates.items()
                if abs(candidate_xs[line] - densest_median) <= gutter_tolerance
            }

    return sorted(candidates.items())


def marker_center_xs(
    words: list[Word],
    page_width: float,
    *,
    band_frac: float = CENTER_BAND_FRAC,
    max_line: int = MAX_PLAUSIBLE_LINE,
) -> list[float]:
    """Center-x of every retained gutter-marker token (same _marker_line rule as
    select_markers). Feeds the gutter median and the Phase 3 dead-zone.
    """
    return [
        _center_x(w)
        for w in words
        if _marker_line(w, page_width, band_frac=band_frac, max_line=max_line) is not None
    ]


def gutter_x(words: list[Word], page_width: float, *, band_frac: float = CENTER_BAND_FRAC) -> float | None:
    """Median center-x of the retained center digit tokens. None if none found.

    Derived per page because the gutter drifts page-to-page (and slightly within
    a page on scans — Phase 3 applies a dead-zone around this value).
    """
    xs = marker_center_xs(words, page_width, band_frac=band_frac)
    if not xs:
        return None
    return statistics.median(xs)


def fit_line_model(markers: list[tuple[int, float]]) -> tuple[float, float] | None:
    """Robust (pitch, intercept) for y = intercept + line*pitch via Theil-Sen.

    pitch  = median of all pairwise slopes (y_j - y_i)/(line_j - line_i)
    intercept = median of (y_i - pitch*line_i)
    Returns None if fewer than MIN_MARKERS_TO_FIT distinct-line markers.
    Tolerates missing markers and rejects outliers (29% breakdown point).
    """
    pts = sorted(set(markers))
    if len(pts) < MIN_MARKERS_TO_FIT:
        return None
    slopes = [
        (pts[j][1] - pts[i][1]) / (pts[j][0] - pts[i][0])
        for i in range(len(pts))
        for j in range(i + 1, len(pts))
        if pts[j][0] != pts[i][0]
    ]
    if not slopes:
        return None
    pitch = statistics.median(slopes)
    intercept = statistics.median([y - pitch * line for line, y in pts])
    return pitch, intercept


def line_at(y: float, pitch: float, intercept: float) -> int:
    """Inverse model: line number occupying vertical center y."""
    return round((y - intercept) / pitch)


def max_marker_residual(markers: list[tuple[int, float]], pitch: float, intercept: float) -> int:
    """Largest |printed_line - predicted_line| over the markers. 0 == perfect.

    This is the per-page self-validation signal (design's Self-validation note).
    The function is tested independently because a buggy residual expression
    once produced spurious nonzero values while extraction was correct.
    """
    return max(abs(line - line_at(y, pitch, intercept)) for line, y in markers)


def to_word(d: dict) -> Word:
    """Project a pdfplumber word dict onto the narrow Word seam."""
    return Word(
        text=d["text"],
        x0=float(d["x0"]),
        x1=float(d["x1"]),
        top=float(d["top"]),
        bottom=float(d["bottom"]),
    )


def page_word_counts(pdf_path: Path) -> list[int]:
    """Per-page extractable-word counts. Lazy-imports pdfplumber."""
    import pdfplumber

    counts: list[int] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            counts.append(len(page.extract_words()))
    return counts


def has_text_layer(counts: list[int], *, min_total: int = MIN_TOTAL_WORDS) -> bool:
    """Pure decision: does the document carry a usable text layer?

    Tested in isolation without a PDF — this is the AC1.2 decision boundary.
    """
    return sum(counts) >= min_total


def probe(pdf_path: Path) -> dict:
    counts = page_word_counts(pdf_path)
    return {
        "patent_id": pdf_path.stem,
        "source_path": str(pdf_path),
        "has_text_layer": has_text_layer(counts),
        "page_word_counts": counts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe", help="Report text-layer presence and per-page word counts")
    p_probe.add_argument("--input", required=True, type=Path, help="Path to the patent PDF")

    args = parser.parse_args(argv)

    if args.command == "probe":
        if not args.input.exists():
            print(f"error: no such file: {args.input}", file=sys.stderr)
            return 2
        result = probe(args.input)
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
