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

This phase implements the `probe` subcommand and `build` (full artifact assembly).

Usage:

    # Report whether a PDF has a usable text layer, with per-page word counts:
    python3 patent_extract.py probe --input US9154231.pdf

    # Build a PatentDoc JSON artifact:
    python3 patent_extract.py build --input US9154231.pdf --out artifact.json

Output: JSON on stdout (or to file). Informational messages and errors go to stderr.

Dependency: `pip install pdfplumber`. The script imports pdfplumber lazily so
`--help` works without the dependency installed. On PEP-668 systems use a venv:
`python3 -m venv .venv && .venv/bin/pip install pdfplumber`.
"""
import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import tempfile
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


class Line(TypedDict):
    """A reconstructed printed line with column and line number tags.

    Invariant: text != "" iff kind == "text". Other kinds (blank, spurious, unknown)
    have text == "".

    kind: One of "text" (rendered line with content), "blank" (real printed empty line),
    "spurious" (numbering-grid slot skipped by text; no real line), "unknown" (unable
    to classify due to missing grid markers).
    """
    column: int                                         # printed column number (1-based, global)
    line: int                                           # printed line number within the column
    text: str
    bbox: tuple[float, float, float, float]            # x0, top, x1, bottom
    page_index: int                                     # 0-based source PDF page
    kind: str                                           # one of LINE_KINDS


# Line kind enumeration
LINE_KINDS = ("text", "blank", "spurious", "unknown")


class PageFit(TypedDict):
    """Diagnostic for page-type classification (Phase 4).

    `is_body` drives extraction and the running column counter (is this a numbered
    column:line page whose text we extract?). `flagged` is an independent REVIEW
    signal (does this page warrant a human look?). They are usually opposites, but
    a body page with a gutter cross-check disagreement is both is_body=True AND
    flagged=True: extracted, but surfaced as suspect.
    """
    page_index: int
    left_column: int
    right_column: int
    gutter_x: float
    pitch: float
    max_marker_residual: int
    is_body: bool
    flagged: bool
    flag_reason: str | None


class PatentDoc(TypedDict):
    """Complete reconstructed patent document with lines and diagnostics."""
    patent_id: str
    source_path: str
    source_sha256: str
    has_text_layer: bool
    lines: list[Line]
    page_fits: list[PageFit]


# Body pages carry hundreds of words; image/empty pages carry zero. A document
# with a usable text layer has a substantial total across its pages.
#
# NOTE: this is a DOCUMENT-LEVEL "is there any text layer at all" threshold, and
# is intentionally distinct from the per-page body VOTE_MIN_WORDS (one of three
# voting signals; see is_body_page). Do not merge the two — they answer different
# questions at different scopes.
MIN_TOTAL_WORDS = 50


# linemodel tuning. Derived empirically (2026-05-31) from both sample patents.
CENTER_BAND_FRAC = 0.06     # |word_center_x - page_center| < CENTER_BAND_FRAC * page_width (coarse band for initial selection)
GUTTER_TOLERANCE = 3.0      # |word_center_x - gutter_x| <= GUTTER_TOLERANCE (tight refinement after gutter detection)
MAX_PLAUSIBLE_LINE = 99     # reject center digit tokens above this (body-text numbers like 100/200/300)
MIN_MARKERS_TO_FIT = 3      # need at least 3 distinct-x markers for a meaningful Theil-Sen fit

# Column reconstruction (Phase 3)
BASE_DEAD_ZONE = 6.0        # pt; minimum half-width of the gutter buffer (verified on born-digital)
DEAD_ZONE_MARGIN = 3.0      # pt; added on top of the measured intra-page gutter drift

# Page-type classification (Phase 4)
MIN_BODY_WORDS = 400        # (legacy) dense two-column floor — no longer a hard gate; see classify_page
MIN_BODY_MARKERS = 6        # (legacy) — no longer a hard gate; see classify_page
MIN_COLUMN_MASS_FRAC = 0.15 # each side must hold at least this fraction of words (else single-column)
SIDE_SPLIT_FRAC = 0.45      # words with center-x < 0.45*W are "left"; > 0.55*W are "right"

# Body-page voting rule (revised 2026-06-01 after US8131198 tiny-claims-page evidence).
# No single signal is sufficient: a multi-of-5 gutter marker only appears once a
# column has >=5 lines, so a 6-line claims tail (US8131198 idx29: cols 33/34) has
# ZERO markers — but it still carries column-number HEADERS. A page is body iff it
# has a clean line-model fit, OR both column headers, OR >=2 of three weak signals.
# Validated to 0 errors across 50 pages / 3 fixtures.
VOTE_MIN_MARKERS = 2        # gutter-marker count that earns a vote
VOTE_MIN_WORDS = 100        # word count that earns a vote
CLEAN_FIT_MAX_RESIDUAL = 1  # a fit is "clean" if its max marker residual <= this

# Column-number header detection (gutter-independent geometric anchor).
HEADER_TOP_MAX = 78.0       # pt; column-number headers sit within this distance of the page top
HEADER_MAX_VALUE = 999      # printed column numbers are small ints (reject body figure numbers)
HEADER_MIN_OFFSET = 60.0    # pt; a header digit must sit at least this far from the gutter (column-center region)
GUTTER_CROSSCHECK_TOL = 5.0 # pt; line-marker gutter vs header-midpoint must agree within this (OCR scans ~2pt)

# Line-numbering gap classification (dimensionless — multiples of the column's OWN gutter pitch).
# Derived empirically (2026-06-01) across US9154231 / US8131198 / US4731298 body columns:
# consecutive (no-blank) text-line gaps cluster at 0.76..1.40 pitch; one real blank line
# shows 1.68..2.16 pitch. The valley is at 1.5, so round(gap/pitch) cleanly separates them.
BLANK_GAP_LO = 0.7          # a gap below this (down to TINY) is still "one line" (tight leading)
BLANK_GAP_HI = 1.4          # a gap up to this is "one line"; above 1.5 it implies a blank slot
TINY_GAP_FRAC_CUTOFF = 0.6  # a gap below this * pitch is implausible -> OCR fragmentation

# Column quality gate (OCR robustness). A column's text-line signal is trustworthy for
# blank classification iff most consecutive gaps sit near one pitch and few are implausibly
# tiny. Measured: born-digital columns frac_clean >= 0.90, frac_tiny ~0; fragmented-OCR
# columns frac_clean 0.52..0.60, frac_tiny 0.29..0.36. Thresholds chosen in the gap.
CLEAN_GAP_FRAC = 0.75   # >= this fraction of gaps within [BLANK_GAP_LO, BLANK_GAP_HI] -> clean
TINY_GAP_FRAC = 0.05    # <= this fraction of gaps below TINY_GAP_FRAC_CUTOFF -> clean

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


def _filter_markers_by_gutter_cluster(
    xs: list[float],
    gutter_tolerance: float = GUTTER_TOLERANCE,
) -> set[float]:
    """Gutter-relative refinement: filter a list of x-coordinates to the densest cluster.

    Clusters xs where members are within gutter_tolerance of the cluster median.
    Returns the set of xs belonging to the densest cluster (largest membership; ties: leftmost).
    This is the shared refinement logic used by both select_markers and marker_center_xs.

    Args:
        xs: list of x-coordinates (center positions of marker tokens)
        gutter_tolerance: max distance from cluster median to belong to the cluster

    Returns:
        Set of x-coordinates belonging to the densest cluster
    """
    if not xs:
        return set()

    xs_sorted = sorted(xs)

    # Cluster xs where members are within gutter_tolerance of the cluster median
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
        return set(densest)

    return set()


def select_markers(
    words: list[Word],
    page_width: float,
    *,
    band_frac: float = CENTER_BAND_FRAC,
    max_line: int = MAX_PLAUSIBLE_LINE,
    gutter_tolerance: float = GUTTER_TOLERANCE,
) -> list[tuple[int, float]]:
    """Center-clustered multiple-of-5 line markers as (line, y_center) pairs.

    Returns sorted, de-duplicated (line, y) pairs. Three-pass selection:
    1. Coarse band filter via _marker_line (operates from page center)
    2. Gutter clustering on FULL coarse-selected xs (before line deduping)
    3. Dedupe by line value, keeping first occurrence within the gutter cluster

    The unified three-pass structure ensures select_markers and marker_center_xs
    operate on the same retained token set: both cluster on coarse_xs, then
    select_markers dedupes by line within the cluster, while marker_center_xs
    returns all xs in the cluster. This eliminates divergence.
    """
    # Pass 1: Coarse selection via _marker_line predicate (band_frac from page center)
    coarse_tokens: list[tuple[int, float, float]] = []  # (line_value, cx, yc)
    for w in words:
        v = _marker_line(w, page_width, band_frac=band_frac, max_line=max_line)
        if v is not None:
            coarse_tokens.append((v, _center_x(w), _y_center(w)))

    # Pass 2: Gutter clustering on the FULL list of coarse xs
    coarse_xs = [cx for _, cx, _ in coarse_tokens]
    refined_xs_set = _filter_markers_by_gutter_cluster(coarse_xs, gutter_tolerance)

    # Pass 3: Dedupe by line, keeping first occurrence within refined cluster
    candidates: dict[int, float] = {}
    for line_val, cx, yc in coarse_tokens:
        if cx in refined_xs_set and line_val not in candidates:
            candidates[line_val] = yc

    return sorted(candidates.items())


def marker_center_xs(
    words: list[Word],
    page_width: float,
    *,
    band_frac: float = CENTER_BAND_FRAC,
    max_line: int = MAX_PLAUSIBLE_LINE,
    gutter_tolerance: float = GUTTER_TOLERANCE,
) -> list[float]:
    """Center-x of every retained gutter-marker token, post-gutter-clustering.

    Uses the same three-pass selection as select_markers:
    1. Coarse _marker_line filter (band_frac from page center)
    2. Gutter clustering on FULL coarse xs
    3. Return all xs within the refined cluster (preserves duplicates/multiples)

    Feeds gutter_x (median) and dead_zone_halfwidth (the spread).
    Critical: uses the SAME clustering logic as select_markers so both operate
    on the same retained token set.
    """
    # Pass 1: Coarse selection via _marker_line predicate
    coarse_xs = []
    for w in words:
        v = _marker_line(w, page_width, band_frac=band_frac, max_line=max_line)
        if v is not None:
            coarse_xs.append(_center_x(w))

    # Pass 2: Gutter clustering on the FULL coarse xs
    refined_xs_set = _filter_markers_by_gutter_cluster(coarse_xs, gutter_tolerance)

    # Pass 3: Return all xs in the refined set (preserves duplicates)
    return [cx for cx in coarse_xs if cx in refined_xs_set]


def gutter_x(words: list[Word], page_width: float, *, band_frac: float = CENTER_BAND_FRAC) -> float | None:
    """Median center-x of the retained center digit tokens. None if none found.

    Derived per page because the gutter drifts page-to-page (and slightly within
    a page on scans — Phase 3 applies a dead-zone around this value).
    """
    xs = marker_center_xs(words, page_width, band_frac=band_frac)
    if not xs:
        return None
    return statistics.median(xs)


def _header_digit_xs(words: list[Word]) -> list[float]:
    """Center-x of every plausible column-number HEADER digit token.

    Column-number headers (e.g. "33" / "34") are printed at the top of each body
    page, one per column, sitting at the column centers. Unlike gutter markers
    they are NOT multiples of 5 and do NOT depend on the column having >=5 lines —
    so they exist even on a short claims tail with no gutter markers at all.

    A token qualifies iff it is: (a) pure digits, (b) within HEADER_TOP_MAX of the
    page top, (c) a small positive int (<= HEADER_MAX_VALUE). Pure function.
    """
    out: list[float] = []
    for w in words:
        t = w["text"].strip()
        if not _DIGITS.fullmatch(t):
            continue
        if w["top"] >= HEADER_TOP_MAX:
            continue
        v = int(t)
        if v <= 0 or v > HEADER_MAX_VALUE:
            continue
        out.append(_center_x(w))
    return out


def header_midpoint_gutter(words: list[Word], page_width: float) -> float | None:
    """Gutter estimate from column-number header digits, independent of line markers.

    The two column headers straddle the gutter symmetrically, so the midpoint of a
    left-of-center and a right-of-center header digit estimates the gutter x. When
    several candidates exist we pick the pair whose midpoint is closest to the page
    center (the true gutter is near center; stray header text is not).

    Returns None if there is not at least one header digit on each side of center.
    This is the only gutter anchor available on a marker-less short claims page
    (verified 302.94 vs line-marker gutter 303 on US8131198 idx29).
    """
    center = page_width / 2.0
    xs = _header_digit_xs(words)
    left = [x for x in xs if x < center]
    right = [x for x in xs if x > center]
    if not left or not right:
        return None
    best_mid: float | None = None
    best_sym = float("inf")
    for lx in left:
        for rx in right:
            mid = (lx + rx) / 2.0
            sym = abs(mid - center)
            if sym < best_sym:
                best_sym = sym
                best_mid = mid
    return best_mid


def column_labels(words: list[Word], page_width: float, gutter: float | None) -> int:
    """Number of column-number headers present (0, 1, or 2), anchored on the gutter.

    A header counts on a side iff there is a header digit at least HEADER_MIN_OFFSET
    away from the gutter on that side (i.e. out at the column center, not a stray
    digit hugging the gutter). Gutter-anchored rather than fixed 1/4-3/4 width
    because page margins shift the column centers inward (US8131198 headers sit at
    cx~186/420, not the naive 0.25/0.75 * width targets).

    Returns 0 if gutter is None (cannot anchor). Pure function.
    """
    if gutter is None:
        return 0
    xs = _header_digit_xs(words)
    has_left = any(gutter - x >= HEADER_MIN_OFFSET for x in xs)
    has_right = any(x - gutter >= HEADER_MIN_OFFSET for x in xs)
    return int(has_left) + int(has_right)


def resolve_gutter(words: list[Word], page_width: float) -> tuple[float | None, bool]:
    """Best gutter estimate plus a cross-check disagreement flag.

    Strategy (decided 2026-06-01: "header-midpoint as a cross-check everywhere"):
    - line-marker gutter is PRIMARY (unchanged for normal body pages),
    - header-midpoint is the FALLBACK when no line markers exist (short claims tails),
    - when BOTH exist they must agree within GUTTER_CROSSCHECK_TOL; if they disagree
      we keep the line-marker value (more precise) but raise the disagreement flag so
      the page can be surfaced as suspect rather than silently mis-cropped.

    Returns (gutter_x_or_None, disagreement). disagreement is always False when
    fewer than both estimates are available.
    """
    g_line = gutter_x(words, page_width)
    g_header = header_midpoint_gutter(words, page_width)
    if g_line is not None and g_header is not None:
        disagree = abs(g_line - g_header) > GUTTER_CROSSCHECK_TOL
        return g_line, disagree
    if g_line is not None:
        return g_line, False
    return g_header, False


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


def line_gaps_in_pitch(y_centers: list[float], pitch: float) -> list[float]:
    """Consecutive gaps between text-line y-centers, expressed as multiples of the gutter pitch.

    Requires y_centers to be sorted in ascending order. Returns the list of gaps
    [(y_centers[i+1] - y_centers[i]) / pitch for i in range(len-1)]. Empty list
    if fewer than 2 y-centers.

    Args:
        y_centers: sorted list of text-line vertical centers (points, in ascending order)
        pitch: gutter pitch (distance per line, in same units as y_centers). Must be > 0.

    Returns:
        List of gap ratios (dimensionless).

    Raises:
        ValueError: if pitch <= 0.
    """
    if pitch <= 0:
        raise ValueError("pitch must be positive (a caller bug to pass pitch <= 0)")
    if len(y_centers) < 2:
        return []
    return [(y_centers[i + 1] - y_centers[i]) / pitch for i in range(len(y_centers) - 1)]


def slots_spanned(gap_ratio: float) -> int:
    """Number of line slots a single inter-line gap spans.

    Given a gap expressed as a multiple of the column's gutter pitch, returns the
    count of printed-line slots it spans: 1 = consecutive (normal leading), 2 = one
    blank line between, etc. Computed as max(1, round(gap_ratio)), so a tight gap
    or any sub-1 OCR artifact cannot collapse two lines onto one slot.

    Args:
        gap_ratio: inter-line gap as multiple of gutter pitch (dimensionless).

    Returns:
        Integer number of slots (always >= 1).
    """
    return max(1, round(gap_ratio))


def column_signal_is_clean(gap_ratios: list[float]) -> bool:
    """Decide whether a column's text-line signal is clean enough to classify blanks.

    A column's text-line signal is trustworthy for blank classification (born-digital
    with stable line spacing) iff most consecutive gaps sit near one pitch (clean)
    and few are implausibly tiny (OCR fragmentation). Columns with < 3 gaps are too
    small to judge reliably, so we don't penalize legitimate short columns like claims
    tails; Phase 2's classifier will still only emit blanks it can justify geometrically.

    Args:
        gap_ratios: list of gap/pitch ratios for a single column's consecutive text lines.

    Returns:
        True if the column's signal is clean (classifiable); False if noisy (fragmented OCR).
    """
    # Short columns (< 3 gaps): too few to judge — return True (do not penalize)
    if len(gap_ratios) < 3:
        return True

    # Compute fractions
    frac_clean = sum(1 for g in gap_ratios if BLANK_GAP_LO <= g <= BLANK_GAP_HI) / len(gap_ratios)
    frac_tiny = sum(1 for g in gap_ratios if g < TINY_GAP_FRAC_CUTOFF) / len(gap_ratios)

    # Clean iff frac_clean >= threshold AND frac_tiny <= threshold
    return frac_clean >= CLEAN_GAP_FRAC and frac_tiny <= TINY_GAP_FRAC


def dead_zone_halfwidth(marker_xs: list[float]) -> float:
    """Half-width of the gutter buffer. Covers the page's measured gutter drift.

    On scans the gutter skews top-to-bottom (~4 pt observed); the marker tokens
    reveal that drift directly via their center-x spread. We buffer the full
    spread plus a margin, floored at BASE_DEAD_ZONE.

    For robustness: trims one extreme from each end before computing spread.
    For 1-2 points, uses the raw spread; for 3+ points, excludes the min and max.
    This handles a single outlier while preserving the true drift. (Note: not
    a full IQR implementation; the upstream gutter clustering already removes
    outliers, so this is a lightweight secondary protection.)
    """
    if not marker_xs:
        return BASE_DEAD_ZONE

    if len(marker_xs) == 1:
        return BASE_DEAD_ZONE

    if len(marker_xs) == 2:
        drift = max(marker_xs) - min(marker_xs)
        return max(BASE_DEAD_ZONE, drift + DEAD_ZONE_MARGIN)

    # For 3+ points: trim min and max, then compute drift from the remaining central points.
    # This handles the case of one outlier while preserving the true drift.
    sorted_xs = sorted(marker_xs)
    central = sorted_xs[1:-1]  # Exclude min and max

    if central:
        drift = max(central) - min(central)
    else:
        # Should not happen, but fallback to full range
        drift = max(marker_xs) - min(marker_xs)

    # Cap drift at 50pt (reasonable maximum for real gutter drift)
    # to handle pathological cases. On born-digital and OCR scans,
    # real drift is <= 5pt.
    drift = min(drift, 50.0)

    return max(BASE_DEAD_ZONE, drift + DEAD_ZONE_MARGIN)


def reconstruct_page(
    page,                       # pdfplumber Page (for .crop / .extract_text_lines)
    page_width: float,
    page_height: float,
    gutter: float,
    marker_xs: list[float],
    pitch: float,
    intercept: float,
    left_column: int,
    right_column: int,
    page_index: int,
) -> list[Line]:
    """Crop LEFT and RIGHT columns around the dead-zoned gutter, line-extract
    each in isolation, drop the header band (predicted line < 1), and tag every
    surviving line with its column and printed line number.

    IMPORTANT #3 guard: Clamp crop bounds to [0, page_width] to prevent inverted/empty
    crops if the dead-zone is miscalibrated or the gutter is at a page edge.
    """
    dz = dead_zone_halfwidth(marker_xs)
    out: list[Line] = []

    # Clamp crop bounds to valid page coordinates
    left_x0 = 0
    left_x1 = max(0, min(gutter - dz, page_width))
    right_x0 = max(0, min(gutter + dz, page_width))
    right_x1 = page_width

    # Skip columns with non-positive width (degenerate crop)
    crops = []
    if left_x1 > left_x0:
        crops.append((left_column, page.crop((left_x0, 0, left_x1, page_height))))
    if right_x1 > right_x0:
        crops.append((right_column, page.crop((right_x0, 0, right_x1, page_height))))

    for column, crop in crops:
        for ln in crop.extract_text_lines():
            yc = (ln["top"] + ln["bottom"]) / 2.0
            line_no = line_at(yc, pitch, intercept)
            if line_no < 1:
                continue   # running header / column-number header band
            out.append(Line(
                column=column,
                line=line_no,
                text=ln["text"],
                bbox=(ln["x0"], ln["top"], ln["x1"], ln["bottom"]),
                page_index=page_index,
                kind="text",
            ))
    return out


def column_mass_fractions(words: list[Word], page_width: float) -> tuple[float, float]:
    """Fraction of words whose center-x falls clearly left vs. clearly right.

    Left: center-x < SIDE_SPLIT_FRAC * page_width
    Right: center-x > (1 - SIDE_SPLIT_FRAC) * page_width
    Center band: in between (ignored)

    Pure function, no side effects.
    """
    n = len(words)
    if n == 0:
        return 0.0, 0.0
    left = sum(1 for w in words if _center_x(w) < SIDE_SPLIT_FRAC * page_width)
    right = sum(1 for w in words if _center_x(w) > (1 - SIDE_SPLIT_FRAC) * page_width)
    return left / n, right / n


def is_body_page(
    word_count: int,
    marker_count: int,
    label_count: int,
    fit: tuple[float, float] | None,
    residual: int,
) -> bool:
    """Voting decision: is this a numbered column:line body page?

    Decided 2026-06-01 after the US8131198 tiny-claims-page evidence. No single
    signal is sufficient (a 6-line claims tail has zero gutter markers), so a page
    is body iff ANY of:
      - clean line-model fit (>= MIN_MARKERS_TO_FIT markers, residual <= CLEAN_FIT_MAX_RESIDUAL)
      - both column-number headers present (label_count >= 2)
      - >= 2 of three weak votes: markers>=VOTE_MIN_MARKERS, label>=1, words>=VOTE_MIN_WORDS

    Validated to 0 errors across 50 pages / 3 fixtures. Drawings, figure pages and
    the dense "References Cited" front-matter page all fail (the last earns only the
    word vote — no markers, no column-center headers — so it stays below 2 votes).

    Pure function of scalars: trivially unit-testable, no PDF required.
    """
    clean_fit = fit is not None and marker_count >= MIN_MARKERS_TO_FIT and 0 <= residual <= CLEAN_FIT_MAX_RESIDUAL
    if clean_fit:
        return True
    if label_count >= 2:
        return True
    votes = (marker_count >= VOTE_MIN_MARKERS) + (label_count >= 1) + (word_count >= VOTE_MIN_WORDS)
    return votes >= 2


def classify_page(
    words: list[Word],
    page_width: float,
    markers: list[tuple[int, float]],
    fit: tuple[float, float] | None,
    gutter: float | None,
    page_index: int,
    left_column: int,
    right_column: int,
    *,
    gutter_disagreement: bool = False,
) -> PageFit:
    """Build the PageFit diagnostic, flagging non-body pages with a reason.

    Body membership is decided by is_body_page (voting rule). A non-body page is
    flagged and NOT extracted as body content downstream. A body page whose
    gutter cross-check disagreed is still admitted but flagged-as-suspect in its
    reason (so it surfaces for review without losing its column numbers).

    Pure function, no side effects. No pdfplumber required.
    """
    residual = max_marker_residual(markers, *fit) if (fit and markers) else -1
    label_count = column_labels(words, page_width, gutter)
    body = is_body_page(len(words), len(markers), label_count, fit, residual)

    reason: str | None = None
    if not body:
        lf, rf = column_mass_fractions(words, page_width)
        reason = (
            f"not a numbered body page (words={len(words)}, markers={len(markers)}, "
            f"headers={label_count}, mass L={lf:.2f} R={rf:.2f})"
        )
    elif gutter is None:
        # A body page with no gutter anchor at all cannot be cropped; flag it.
        reason = "body page but no gutter anchor (no markers and no column headers)"
        body = False
    elif gutter_disagreement:
        # Admitted as body, but the two gutter estimates disagree — surface it.
        reason = "gutter cross-check disagreement (line-marker vs header midpoint)"

    flagged = reason is not None
    pitch = fit[0] if fit else 0.0
    # residual (computed above) uses the sentinel -1 to mean "no fit / not
    # applicable" (the page could not be fitted), distinct from a real residual
    # where 0 == perfect. Consumers must treat negative residuals as "no
    # measurement", never as a fit quality.
    return PageFit(
        page_index=page_index,
        left_column=left_column,
        right_column=right_column,
        gutter_x=gutter if gutter is not None else 0.0,
        pitch=pitch,
        max_marker_residual=residual,
        is_body=body,
        flagged=flagged,
        flag_reason=reason,
    )


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


# ============================================================================
# Document orchestration and persistence (Phase 5)
# ============================================================================


def sha256_file(path: Path) -> str:
    """SHA256 hash of a file's contents as a 64-char hex string."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_document(pdf_path: Path) -> PatentDoc:
    """Parse the PDF once into a PatentDoc. Lazy-imports pdfplumber.

    The running column counter advances for every BODY page (PageFit.is_body),
    so drawing/front-matter pages do not consume column numbers. A body page
    consumes its two column numbers even when its lines cannot yet be extracted
    (e.g. a short claims tail with column headers but no line-model markers —
    line-number assignment for marker-less pages is deferred to the issue-#1
    rework). Such a page is recorded with its correct columns but contributes
    no Line rows.
    """
    import pdfplumber

    lines: list[Line] = []
    page_fits: list[PageFit] = []
    counts: list[int] = []
    body_pages_seen = 0   # k: this many body pages processed so far

    with pdfplumber.open(str(pdf_path)) as pdf:
        for idx, page in enumerate(pdf.pages):
            words = [to_word(d) for d in page.extract_words()]
            counts.append(len(words))
            markers = select_markers(words, page.width)
            fit = fit_line_model(markers)
            gutter, gutter_disagreement = resolve_gutter(words, page.width)

            # Provisional column numbers for THIS page if it turns out to be body.
            left_col = 2 * body_pages_seen + 1
            right_col = 2 * body_pages_seen + 2

            page_fit = classify_page(
                words, page.width, markers, fit, gutter,
                page_index=idx, left_column=left_col, right_column=right_col,
                gutter_disagreement=gutter_disagreement,
            )

            if page_fit["is_body"]:
                # Body page: consume its column numbers (counter advances).
                if fit is not None and gutter is not None:
                    # Reuse the Phase 2 marker-selection helper — do NOT re-inline
                    # the selection rule (single source of truth for the geometry).
                    marker_xs = marker_center_xs(words, page.width)
                    pitch, intercept = fit
                    lines.extend(reconstruct_page(
                        page, page.width, page.height, gutter, marker_xs,
                        pitch, intercept, left_col, right_col, idx,
                    ))
                # else: body page with no line-model (marker-less short claims
                # tail). Columns are consumed; line extraction deferred (issue #1).
                body_pages_seen += 1
            else:
                # Non-body page: keep its diagnostic but zero its columns so it
                # is clear no column numbers were consumed.
                page_fit["left_column"] = 0
                page_fit["right_column"] = 0

            page_fits.append(page_fit)

    return PatentDoc(
        patent_id=pdf_path.stem,
        source_path=str(pdf_path),
        source_sha256=sha256_file(pdf_path),
        has_text_layer=has_text_layer(counts),
        lines=lines,
        page_fits=page_fits,
    )


def write_document(doc: PatentDoc, out_path: Path) -> None:
    """Write PatentDoc to JSON file with trailing newline (house convention).

    Uses atomic write: writes to a temp file in the same directory, then
    os.replace() to atomically move it into place. This prevents truncated
    artifacts on crash mid-write.
    """
    out_path = Path(out_path)  # ensure Path object
    # Create temp file in same directory for atomic os.replace()
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=out_path.parent,
        delete=False,
        encoding="utf-8",
        suffix=".tmp",
    ) as tmp:
        tmp_path = Path(tmp.name)
        try:
            json.dump(doc, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())  # ensure data is on disk before rename
        except Exception:
            # Clean up temp file on any error
            try:
                tmp_path.unlink()
            except Exception:
                pass
            raise
    # Atomic rename: tmp -> out_path (same filesystem)
    os.replace(str(tmp_path), str(out_path))


def load_document(path: Path) -> PatentDoc:
    """Load PatentDoc from JSON, normalizing bbox lists to tuples."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # JSON has no tuples: bbox round-trips as a list. Normalize back to tuple
    # so the in-memory shape matches Line's contract exactly.
    for ln in data["lines"]:
        ln["bbox"] = tuple(ln["bbox"])
        # Backfill kind for old artifacts (pre-kind schema): all existing lines
        # in old artifacts are text lines (Task 1 creates them all as kind="text").
        ln.setdefault("kind", "text")
    # Backfill is_body for artifacts written before the field existed: a page that
    # consumed column numbers (non-zero columns) was a body page.
    for pf in data.get("page_fits", []):
        if "is_body" not in pf:
            pf["is_body"] = pf.get("left_column", 0) > 0
    return data  # type: ignore[return-value]


def build_or_load(pdf_path: Path, artifact_path: Path, *, force: bool = False) -> PatentDoc:
    """Build or reuse cached PatentDoc based on source PDF's SHA256.

    Cache hit when stored source_sha256 matches current PDF sha256.
    force=True always triggers a rebuild.
    """
    if not force and artifact_path.exists():
        cached = load_document(artifact_path)
        if cached.get("source_sha256") == sha256_file(pdf_path):
            return cached   # cache hit: no re-parse
    doc = build_document(pdf_path)
    write_document(doc, artifact_path)
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe", help="Report text-layer presence and per-page word counts")
    p_probe.add_argument("--input", required=True, type=Path, help="Path to the patent PDF")

    p_build = sub.add_parser("build", help="Build (or reuse) the PatentDoc JSON artifact")
    p_build.add_argument("--input", required=True, type=Path, help="Path to the patent PDF")
    p_build.add_argument("--out", required=True, type=Path, help="Artifact JSON path")
    p_build.add_argument("--force", action="store_true", help="Rebuild even if a valid cache exists")

    args = parser.parse_args(argv)

    if args.command == "probe":
        if not args.input.exists():
            print(f"error: no such file: {args.input}", file=sys.stderr)
            return 2
        result = probe(args.input)
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.command == "build":
        if not args.input.exists():
            print(f"error: no such file: {args.input}", file=sys.stderr)
            return 2
        doc = build_or_load(args.input, args.out, force=args.force)
        print(f"wrote {len(doc['lines'])} lines, {len(doc['page_fits'])} pages -> {args.out}", file=sys.stderr)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
