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


# ---------------------------------------------------------------------------
# Layer 2: span finding + parsing (Functional Core)
# ---------------------------------------------------------------------------

# A single patent number: comma-grouped (tolerating one space after each
# comma — soft line breaks become spaces in clean) or a bare 7-10 digit run.
# Optional D/PP/RE prefix; optional trailing kind code (B2, A1, C1, E1...).
_NUM = r"(?:D|PP|RE)?(?:\d{1,3}(?:,\s?\d{3})+|\d{7,10})"
# Same kind-code vocabulary as patent_ref._strip_kind_code: A1/A2/A9,
# B1/B2/B9, C1, E1. Keep the two in sync.
_KIND_CODE = r"(?:\s?(?:[AB][129]|C1|E1))?"

US_LONG_RE = re.compile(
    rf"(?:(?:U\.?\s?S\.?|United\s+States)\s+)?"
    rf"Pat(?:ent)?\.?\s+(?:Nos?\.?\s*)?"
    rf"(?P<numbers>{_NUM}{_KIND_CODE}"
    rf"(?:(?:,\s?(?:and\s+)?|\s+and\s+|\s?&\s?){_NUM}{_KIND_CODE})*)",
    re.IGNORECASE,
)

APPPUB_RE = re.compile(
    rf"(?:U\.?\s?S\.?\s+)?(?:Pat(?:ent)?\.?\s+)?(?:Application\s+|App\.\s+)?"
    rf"Pub(?:lication)?\.?\s+(?:Nos?\.?\s*)?(?:US\s?)?"
    rf"(?P<number>(?:19|20)\d{{2}}/\d{{7}}|(?:19|20)\d{{9}}){_KIND_CODE}",
    re.IGNORECASE,
)

# "US 2009/0151718 A1" — apppub with no label words at all.
APPPUB_BARE_RE = re.compile(
    rf"\bUS\s?(?P<number>(?:19|20)\d{{2}}/\d{{7}}){_KIND_CODE}",
)

EP_RE = re.compile(r"\bEP\s?\d(?:\s?\d){6}(?:\s?[A-C]\d)?\b")
WO_RE = re.compile(r"\bWO\s?(?:19|20)\d{2}/?\d{6}(?:\s?A\d)?\b")
PCT_RE = re.compile(r"\bPCT/[A-Z]{2}(?:19|20)?\d{2}/\d{5,6}\b")

SHORT_NUM_RE = re.compile(
    r"\b[Tt]he\s+'(?P<digits>\d{3})\s+(?P<noun>patent|publication|application)\b",
    re.IGNORECASE,
)

# "the Kwok patent" — a capitalized single word before "patent". Common
# capitalized adjectives that are not surnames are excluded.
SHORT_INVENTOR_RE = re.compile(
    r"\b[Tt]he\s+(?P<name>[A-Z][a-zA-Z]+)\s+patent\b",
)
_NOT_INVENTOR_NAMES = frozenset({
    "Asserted", "Subject", "Instant", "Disputed", "Same", "Said",
    "First", "Second", "Third", "Original", "Parent", "Patented",
})

# Nickname parenthetical right after a long form:
#   ("the '642 patent")   (the Kwok patent)   ("'642 patent")
NICKNAME_RE = re.compile(
    r"""\(\s*"?\s*(?:the\s+)?
        (?P<label>'\d{3}|[A-Z][a-zA-Z]+)\s+
        (?P<noun>patent|publication|application)\s*"?\s*\)""",
    re.VERBOSE | re.IGNORECASE,
)
# Max gap (chars) between a citation's end and its nickname parenthetical.
NICKNAME_MAX_GAP = 20

# Single-number iterator used to expand "Nos." lists.
_NUM_ITER_RE = re.compile(rf"{_NUM}")


def _normalize_number(number: str) -> str:
    """Remove whitespace after comma groups before handing a matched number
    to parse_patent_ref. A soft line break inside a number ("8,453,\\n642")
    cleans to "8,453, 642"; patent_ref strips commas but only COLLAPSES
    whitespace, so "8453 642" would fall through to kind='unsupported'.
    Normalizing here keeps line-break-split numbers fully fetchable."""
    return re.sub(r",\s+", ",", number)


def _make_citation(
    citation_type: str,
    full_citation: str,
    span: tuple[int, int],
    ref: dict | None,
) -> PatentCitation:
    return PatentCitation(
        citation_type=citation_type,
        full_citation=full_citation,
        span=[span[0], span[1]],
        ref=ref,
        pincite=None,
        nickname=None,
        resolved_to=None,
        flags=[],
    )


def _find_raw_matches(text: str) -> list[tuple[int, int, str, re.Match]]:
    """Sweep every family over the text. Returns (start, end, family, match)."""
    families = [
        ("us_long", US_LONG_RE),
        ("apppub", APPPUB_RE),
        ("apppub", APPPUB_BARE_RE),
        ("ep", EP_RE),
        ("wo", WO_RE),
        ("pct", PCT_RE),
        ("short_num", SHORT_NUM_RE),
        ("short_inventor", SHORT_INVENTOR_RE),
    ]
    raw: list[tuple[int, int, str, re.Match]] = []
    for family, pattern in families:
        for m in pattern.finditer(text):
            if family == "short_inventor" and m.group("name") in _NOT_INVENTOR_NAMES:
                continue
            raw.append((m.start(), m.end(), family, m))
    return raw


def _merge_longest_wins(
    raw: list[tuple[int, int, str, re.Match]],
) -> list[tuple[int, int, str, re.Match]]:
    """Drop any match overlapping a longer (or equal, earlier-listed) one."""
    ordered = sorted(raw, key=lambda r: (-(r[1] - r[0]), r[0]))
    kept: list[tuple[int, int, str, re.Match]] = []
    for cand in ordered:
        if any(cand[0] < k[1] and k[0] < cand[1] for k in kept):
            continue
        kept.append(cand)
    return sorted(kept, key=lambda r: r[0])


def _attach_nickname(text: str, citation: PatentCitation) -> None:
    """If a nickname parenthetical sits within NICKNAME_MAX_GAP of the
    citation's end, record it (mutates citation in place)."""
    end = citation["span"][1]
    # Window extends +60 chars to allow full nickname label parsing (max ~14 chars for
    # "the [CapitalizedName]" or "the '[3digits]"), plus NICKNAME_MAX_GAP tolerance.
    window = text[end:end + NICKNAME_MAX_GAP + 60]
    m = NICKNAME_RE.match(window.lstrip()) if window else None
    # Only accept if the parenthetical starts within the gap.
    stripped_offset = len(window) - len(window.lstrip())
    if m is not None and stripped_offset <= NICKNAME_MAX_GAP:
        label = m.group("label")
        noun = m.group("noun").lower()
        citation["nickname"] = f"the {label} {noun}"


def _record_nickname(text: str, citation: PatentCitation, nickname_spans: list) -> None:
    """Attach nickname to citation and record its span if found.

    Eliminates duplicated bookkeeping between us_long and apppub branches.
    """
    _attach_nickname(text, citation)
    if citation["nickname"] is not None:
        end = citation["span"][1]
        nick_m = NICKNAME_RE.search(text, end, end + NICKNAME_MAX_GAP + 60)
        if nick_m:
            nickname_spans.append((nick_m.start(), nick_m.end()))


def get_patent_citations(text: str) -> list[PatentCitation]:
    """Find and parse all patent citations in cleaned text, document order.

    Pass text through clean_patent_text first; spans returned here are valid
    in the original text because cleaning is 1:1.
    """
    merged = _merge_longest_wins(_find_raw_matches(text))

    citations: list[PatentCitation] = []
    nickname_spans: list[tuple[int, int]] = []

    for start, end, family, m in merged:
        matched = text[start:end]
        if family == "us_long":
            # Expand "Nos." lists: one citation per number, sharing the span.
            numbers = _NUM_ITER_RE.findall(m.group("numbers"))
            for number in numbers:
                ref = dict(parse_patent_ref(_normalize_number(number)))
                cit = _make_citation("patent", matched, (start, end), ref)
                citations.append(cit)
            if citations and citations[-1]["span"] == [start, end]:
                _record_nickname(text, citations[-1], nickname_spans)
        elif family == "apppub":
            ref = dict(parse_patent_ref(m.group("number")))
            cit = _make_citation("patent", matched, (start, end), ref)
            citations.append(cit)
            _record_nickname(text, cit, nickname_spans)
        elif family in ("ep", "wo", "pct"):
            ref = dict(parse_patent_ref(matched))
            citations.append(_make_citation("patent", matched, (start, end), ref))
        elif family in ("short_num", "short_inventor"):
            citations.append(
                _make_citation("patent_short", matched, (start, end), None)
            )

    # Drop short forms that are actually the inside of a nickname
    # parenthetical we already attached to a long form.
    def _inside_nickname(c: PatentCitation) -> bool:
        s, e = c["span"]
        return c["citation_type"] == "patent_short" and any(
            ns <= s and e <= ne for ns, ne in nickname_spans
        )

    return [c for c in citations if not _inside_nickname(c)]


# ---------------------------------------------------------------------------
# Imperative Shell — CLI
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    """Read raw document text from --input or stdin; print a JSON array of
    PatentCitation entries to stdout.

    Returns 0 on success, 2 on input errors (unreadable --input file).
    """
    parser = argparse.ArgumentParser(
        description="Extract patent citations from document text. "
                    "Reads raw text; writes a JSON array of citations to stdout.",
    )
    parser.add_argument("--input", help="Path to input text file. If omitted, read stdin.")
    args = parser.parse_args(argv)

    if args.input:
        try:
            with open(args.input, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            sys.stderr.write(f"ERROR: failed to read input file: {e}\n")
            return 2
    else:
        text = sys.stdin.read()

    cleaned = clean_patent_text(text)
    citations = get_patent_citations(cleaned)

    json.dump(citations, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
