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
