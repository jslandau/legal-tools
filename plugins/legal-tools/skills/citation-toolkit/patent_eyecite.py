#!/usr/bin/env python3
"""
patent_eyecite.py — extract patent citations from document text.

Structural sibling to eyecite_extract.py: takes raw text (a brief, an office
action) and returns a document-ordered JSON array of every patent citation
with its span, parsed structural fields (via patent_ref.py), any pincite
(column:line, paragraph, or claim), and short-form resolution linking
"the '642 patent" back to the full citation that introduced it.

Mirrors eyecite's three-layer public API:

    clean_patent_text(text)         -> str     # 1:1 normalization, offsets preserved
    get_patent_citations(text)      -> list    # span finding + parsing + pincites
    resolve_patent_citations(cites) -> list    # stateful short-form resolution

Usage:

    # From a file:
    python3 patent_eyecite.py --input brief.txt

    # From stdin:
    cat brief.txt | python3 patent_eyecite.py

Output: JSON array on stdout, one entry per citation in document order:

    {
      "citation_type": "patent" | "patent_short" | "patent_claim",
      "full_citation": "U.S. Patent No. 8,453,642",
      "span": [120, 146],
      "ref": {"kind": "grant", "canonical_number": "8453642", ...} | null,
      "pincite": {"kind": "column_line", ...} | null,
      "nickname": "the '642 patent" | null,
      "resolved_to": {"index": 0, "full_citation": "..."} | null,
      "flags": []
    }

Spans index the ORIGINAL text: cleaning is strictly one-to-one character
replacement (curly quotes, dashes, newlines), so [start, end) offsets are
valid against both the original and cleaned strings.

Default run is fully offline and stdlib-only (imports only patent_ref.py).
The --resolve-metadata flag (later phase) is the single network opt-in and
sends only patent numbers — never document text — over the wire.

Dependencies: stdlib only. No `pip install` required.

# pattern: Mixed (Functional Core + Imperative Shell)
#   Functional Core: clean_patent_text, get_patent_citations,
#                    resolve_patent_citations and all helpers.
#   Imperative Shell: main(argv) — file/stdin/stdout I/O only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import TypedDict

from patent_ref import parse_patent_ref


class PatentCitation(TypedDict):
    """One extracted patent citation, eyecite_extract-compatible."""
    citation_type: str          # "patent" | "patent_short" | "patent_claim"
    full_citation: str          # matched text (cleaned form)
    span: list[int]             # [start, end) in the original text
    ref: dict | None            # PatentRef from patent_ref.py (None for short forms)
    pincite: dict | None        # {"kind": "column_line"|"paragraph"|"claims", ...}
    nickname: str | None        # from a nickname parenthetical
    resolved_to: dict | None    # {"index": int, "full_citation": str}
    flags: list[str]            # unresolved_short_form, ambiguous_pincite, needs_metadata


# ---------------------------------------------------------------------------
# Layer 1: text cleaning (Functional Core)
# ---------------------------------------------------------------------------

# Strictly 1:1 character translation. Never inserts or deletes characters,
# so every span computed on the cleaned text is valid in the original.
_CLEAN_TABLE = str.maketrans({
    0x2018: 0x27,  # left single curly quote → '
    0x2019: 0x27,  # right single curly quote → '
    0x0060: 0x27,  # backtick → '
    0x201C: 0x22,  # left double curly quote → "
    0x201D: 0x22,  # right double curly quote → "
    0x2013: 0x2D,  # en dash → -
    0x2014: 0x2D,  # em dash → -
    0x00A0: 0x20,  # no-break space → space
    0x000A: 0x20,  # newline → space
    0x000D: 0x20,  # carriage return → space
    0x0009: 0x20,  # tab → space
})


def clean_patent_text(text: str) -> str:
    """Normalize text for matching. One-to-one replacement only:
    len(result) == len(text) and offsets map identically."""
    return text.translate(_CLEAN_TABLE)


def main(argv: list[str]) -> int:
    """CLI shell — wired fully in a later task of this phase."""
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
