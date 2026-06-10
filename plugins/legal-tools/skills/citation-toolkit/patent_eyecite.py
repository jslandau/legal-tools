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
from typing import NotRequired, TypedDict

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
    candidates: NotRequired[list[int]]  # indices of ambiguous resolutions (unresolved only)


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

# "U.S. Patent No. 8,453,642 to Kwok" — first-named-inventor introduction.
# Registered as an inventor nickname with zero network. NOTE: no ^ anchor —
# this is used with .match(text, pos), and ^ would still bind to string
# start, never matching at pos > 0. .match() itself anchors at pos.
INVENTOR_INTRO_RE = re.compile(r"\s+to\s+(?P<name>[A-Z][a-zA-Z]+)\b")

# Corporate markers that follow an assignee name (must NOT register as inventor).
_CORPORATE_MARKERS = frozenset({
    "Inc", "Inc.", "Corp", "Corp.", "Corporation", "LLC", "L.L.C.", "Co", "Co.",
    "Ltd", "Ltd.", "Limited", "AG", "plc", "NV", "GmbH", "Sàrl", "Oy",
})

# Single-number iterator used to expand "Nos." lists.
_NUM_ITER_RE = re.compile(rf"{_NUM}")


# ---------------------------------------------------------------------------
# Pincite grammar + proximity gating (Functional Core)
# ---------------------------------------------------------------------------

# A pincite is accepted only inside the proximity window after a citation:
# at most PINCITE_WINDOW_CHARS chars, and the text between citation end and
# pincite start may cross only whitespace, commas, and the word "at".
PINCITE_WINDOW_CHARS = 80
_CONNECTOR_RE = re.compile(r"^[\s,]*(?:at\s+)?[\s,]*$")
# Compact N:M only: the connector may additionally carry a '§' — that match
# is still accepted but flagged ambiguous_pincite (the '§' suggests the N:M
# may be a statute/rule section, not a column:line). Without this relaxed
# variant the ambiguity branch would be unreachable: a '§' prefix would
# always fail _CONNECTOR_RE and the match would be silently dropped.
_COMPACT_CONNECTOR_RE = re.compile(r"^[\s,]*(?:at\s+)?[\s,]*(?:§\s*)?$")

COL_LINE_EXPLICIT_RE = re.compile(
    r"col(?:umn)?s?\.?\s*(?P<c1>\d{1,2}),?\s*"
    r"(?:l(?:ine)?s?\.?|ll\.?)\s*(?P<l1>\d{1,3})"
    r"(?:\s*-\s*(?P<l2>\d{1,3}))?"
    r"(?:\s*(?:to|through)\s*col(?:umn)?\.?\s*(?P<c2>\d{1,2}),?\s*"
    r"(?:l(?:ine)?s?\.?|ll\.?)\s*(?P<l3>\d{1,3}))?",
    re.IGNORECASE,
)

# Compact N:M, optional range, optional cross-column "4:65-5:3".
COL_LINE_COMPACT_RE = re.compile(
    r"(?P<c1>\d{1,2}):(?P<l1>\d{1,3})"
    r"(?:\s*-\s*(?:(?P<c2>\d{1,2}):)?(?P<l2>\d{1,3}))?"
)

PARAGRAPH_RE = re.compile(
    r"(?:¶{1,2}|paras?\.?|paragraphs?)\s*\[?0*(?P<p>\d{1,4})\]?"
    r"|\[(?P<pb>\d{4})\]",
    re.IGNORECASE,
)

CLAIMS_RE = re.compile(
    r"\b[Cc]laims?\s+(?P<a>\d{1,3})(?:\s*-\s*(?P<b>\d{1,3}))?"
)

# Signals that an in-window compact match may not be a column:line cite.
_AMBIGUITY_SIGNAL_RE = re.compile(r"§")
_TIME_SIGNAL_RE = re.compile(r"^\s*[ap]\.?m\.?", re.IGNORECASE)


def _column_line_pincite(c1: int, l1: int, c2: int | None, l2: int | None) -> dict:
    end_col = c2 if c2 is not None else c1
    end_line = l2 if l2 is not None else l1
    return {
        "kind": "column_line",
        "start_column": c1, "start_line": l1,
        "end_column": end_col, "end_line": end_line,
    }


def _match_pincite_in_window(window: str) -> tuple[dict, int, int, list[str]] | None:
    """Try the pincite grammars against a proximity window.

    Returns (pincite, match_start, match_end, flags) for the first accepted
    match, or None. Offsets are relative to the window.

    Grammar evaluation order is: explicit > paragraph > claims > compact.
    Returns on the first connector-valid match in priority order; later/longer
    matches in the same window are not considered.
    """
    # 1. Explicit col/line (most specific, includes cross-column "to col.").
    for m in COL_LINE_EXPLICIT_RE.finditer(window):
        if not _CONNECTOR_RE.match(window[:m.start()]):
            continue
        c2 = int(m.group("c2")) if m.group("c2") else None
        l2 = int(m.group("l3")) if m.group("l3") else (
            int(m.group("l2")) if m.group("l2") else None)
        pin = _column_line_pincite(int(m.group("c1")), int(m.group("l1")), c2, l2)
        return pin, m.start(), m.end(), []

    # 2. Paragraph (apppub form).
    for m in PARAGRAPH_RE.finditer(window):
        if not _CONNECTOR_RE.match(window[:m.start()]):
            continue
        digits = m.group("p") or m.group("pb")
        return {"kind": "paragraph", "paragraph": int(digits)}, m.start(), m.end(), []

    # 3. Claims following the citation ("the '642 patent, claims 1-3").
    for m in CLAIMS_RE.finditer(window):
        if not _CONNECTOR_RE.match(window[:m.start()]):
            continue
        a = int(m.group("a"))
        b = int(m.group("b")) if m.group("b") else a
        return {"kind": "claims", "start_claim": a, "end_claim": b}, m.start(), m.end(), []

    # 4. Compact N:M — most false-positive-prone, tried last and guarded.
    for m in COL_LINE_COMPACT_RE.finditer(window):
        connector = window[:m.start()]
        if not _COMPACT_CONNECTOR_RE.match(connector):
            continue
        if _TIME_SIGNAL_RE.match(window[m.end():]):
            continue  # "9:30 a.m." — a time, not a pincite
        # Edge case: a rejected timestamp in the connector (e.g. "at 9:30 a.m. and 5:12")
        # leaves timestamp prose in the connector, causing later valid compact matches in
        # the same window to also fail the connector check. No-pincite is the deliberate
        # safe failure mode for this scenario.
        flags: list[str] = []
        if _AMBIGUITY_SIGNAL_RE.search(connector):
            flags.append("ambiguous_pincite")
        c2 = int(m.group("c2")) if m.group("c2") else None
        l2 = int(m.group("l2")) if m.group("l2") else None
        pin = _column_line_pincite(int(m.group("c1")), int(m.group("l1")), c2, l2)
        return pin, m.start(), m.end(), flags

    return None


# "claim 1 of the '642 patent" — claims that precede their citation.
_CLAIM_OF_GAP_CHARS = 8  # covers " of " plus stray spaces/commas


def _attach_pincites(text: str, citations: list[PatentCitation]) -> list[tuple[int, int]]:
    """Attach in-window pincites to citations (mutates in place).

    Returns the absolute spans of claim matches that were consumed by
    attachment, so the standalone-claims pass can skip them.
    """
    consumed_claims: list[tuple[int, int]] = []

    # Forward attachment: "claim 1 of <citation>".
    for cit in citations:
        start = cit["span"][0]
        lead = text[max(0, start - 40):start]
        m = None
        for cand in CLAIMS_RE.finditer(lead):
            m = cand  # keep the last (closest) one
        if m is not None:
            between = lead[m.end():]
            if re.fullmatch(r"\s+of\s+", between) and len(between) <= _CLAIM_OF_GAP_CHARS:
                a = int(m.group("a"))
                b = int(m.group("b")) if m.group("b") else a
                cit["pincite"] = {"kind": "claims", "start_claim": a, "end_claim": b}
                abs_start = max(0, start - 40) + m.start()
                consumed_claims.append((abs_start, abs_start + (m.end() - m.start())))
                continue

    # Backward attachment: pincite in the window after the citation.
    for cit in citations:
        if cit["pincite"] is not None:
            continue
        end = cit["span"][1]
        window = text[end:end + PINCITE_WINDOW_CHARS]
        hit = _match_pincite_in_window(window)
        if hit is None:
            continue
        pin, m_start, m_end, flags = hit
        cit["pincite"] = pin
        cit["flags"].extend(f for f in flags if f not in cit["flags"])
        if pin["kind"] == "claims":
            consumed_claims.append((end + m_start, end + m_end))

    return consumed_claims


def _standalone_claims(
    text: str,
    citations: list[PatentCitation],
    consumed_claims: list[tuple[int, int]],
) -> list[PatentCitation]:
    """Emit patent_claim entries for claim refs not attached to any citation."""
    out: list[PatentCitation] = []
    for m in CLAIMS_RE.finditer(text):
        span = (m.start(), m.end())
        if any(cs <= span[0] and span[1] <= ce for cs, ce in consumed_claims):
            continue
        # Inside an existing citation span (e.g., matched text) — skip.
        if any(c["span"][0] <= span[0] < c["span"][1] for c in citations):
            continue
        a = int(m.group("a"))
        b = int(m.group("b")) if m.group("b") else a
        cit = _make_citation("patent_claim", text[span[0]:span[1]], span, None)
        cit["pincite"] = {"kind": "claims", "start_claim": a, "end_claim": b}
        out.append(cit)
    return out


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


def _attach_inventor_intro(text: str, citation: PatentCitation) -> None:
    """If the long form is followed by 'to <Surname>', record it as an
    inventor nickname (unless a parenthetical nickname already attached).
    Only registers single-token names NOT followed by corporate markers."""
    if citation["nickname"] is not None:
        return
    end = citation["span"][1]
    m = INVENTOR_INTRO_RE.match(text, end)
    if m is not None and m.group("name") not in _NOT_INVENTOR_NAMES:
        # Check if name is followed by a corporate marker (e.g., "Sony Corporation"
        # or "Apple, Inc."). A comma immediately after the name is a corporate-name
        # signal. Also scan for multi-word company names (e.g., "Sony Electronics Inc.").
        name = m.group("name")
        # m.end() gives absolute position after the matched name
        peek_text = text[m.end():m.end() + 50]
        # Tolerate optional comma + whitespace, then scan up to 2 capitalized tokens
        # for corporate markers.
        marker_match = re.match(r"^,?\s*([A-Za-z.]+)(?:\s+([A-Za-z.]+))?", peek_text)
        if marker_match:
            # Check first token and (if present) second token for corporate markers
            token1 = marker_match.group(1)
            token2 = marker_match.group(2)
            if token1 in _CORPORATE_MARKERS or (token2 and token2 in _CORPORATE_MARKERS):
                return  # Don't register; it's a corporate assignee
        citation["nickname"] = f"the {name} patent"


def _record_nickname(text: str, citation: PatentCitation, nickname_spans: list) -> None:
    """Attach nickname to citation and record its span if found.

    Eliminates duplicated bookkeeping between us_long and apppub branches.
    """
    _attach_nickname(text, citation)
    _attach_inventor_intro(text, citation)
    if citation["nickname"] is not None:
        end = citation["span"][1]
        nick_m = NICKNAME_RE.search(text, end, end + NICKNAME_MAX_GAP + 60)
        if nick_m:
            nickname_spans.append((nick_m.start(), nick_m.end()))


# ---------------------------------------------------------------------------
# Layer 3: short-form resolution (Functional Core)
# ---------------------------------------------------------------------------

_NICK_DIGITS_RE = re.compile(r"'(\d{3})")
_NICK_NAME_RE = re.compile(r"\bthe\s+(?P<name>[A-Z][a-zA-Z]+)\s+patent", re.IGNORECASE)
_SHORT_DIGITS_RE = re.compile(r"'(\d{3})")
_SHORT_NAME_RE = re.compile(r"\b[Tt]he\s+(?P<name>[A-Z][a-zA-Z]+)\s+patent\b")


def _stack_entry(index: int, citation: PatentCitation) -> dict:
    """Build a stack record for a full citation."""
    canonical = (citation["ref"] or {}).get("canonical_number", "")
    digits = re.sub(r"\D", "", canonical)
    entry = {
        "index": index,
        "full_citation": citation["full_citation"],
        "canonical": canonical,
        "last3": digits[-3:] if len(digits) >= 3 else digits,
        "nick_digits": set(),
        "names": set(),
    }
    nickname = citation["nickname"]
    if nickname:
        dm = _NICK_DIGITS_RE.search(nickname)
        if dm:
            entry["nick_digits"].add(dm.group(1))
        else:
            nm = _NICK_NAME_RE.search(nickname)
            if nm:
                entry["names"].add(nm.group("name").lower())
    return entry


def _distinct_candidates(matches: list[dict]) -> list[dict]:
    """Collapse stack hits to one (the most recent) per canonical number."""
    by_canonical: dict[str, dict] = {}
    for e in matches:
        by_canonical[e["canonical"]] = e  # later entries overwrite → most recent
    return sorted(by_canonical.values(), key=lambda e: e["index"])


def _mark_unresolved(citation: PatentCitation, candidates: list[dict]) -> None:
    citation["flags"].append("unresolved_short_form")
    citation["candidates"] = [e["index"] for e in candidates]


def resolve_patent_citations(citations: list[PatentCitation]) -> list[PatentCitation]:
    """Single forward pass filling resolved_to on short forms and standalone
    claims. Unresolvable entries are flagged, never dropped.

    Returns the same list (entries mutated in place), matching eyecite's
    resolve-pass shape.
    """
    stack: list[dict] = []

    for i, cit in enumerate(citations):
        if cit["citation_type"] == "patent":
            if cit["ref"] and cit["ref"].get("canonical_number"):
                stack.append(_stack_entry(i, cit))
            continue

        if cit["citation_type"] == "patent_claim":
            if stack:
                latest = stack[-1]
                cit["resolved_to"] = {
                    "index": latest["index"],
                    "full_citation": latest["full_citation"],
                }
            else:
                _mark_unresolved(cit, [])
            continue

        # patent_short — digits form or inventor-name form.
        dm = _SHORT_DIGITS_RE.search(cit["full_citation"])
        if dm:
            nnn = dm.group(1)
            matches = [
                e for e in stack if e["last3"] == nnn or nnn in e["nick_digits"]
            ]
            distinct = _distinct_candidates(matches)
            if len(distinct) == 1:
                latest = matches[-1]
                cit["resolved_to"] = {
                    "index": latest["index"],
                    "full_citation": latest["full_citation"],
                }
            else:
                _mark_unresolved(cit, distinct)
            continue

        nm = _SHORT_NAME_RE.search(cit["full_citation"])
        if nm:
            name = nm.group("name").lower()
            matches = [e for e in stack if name in e["names"]]
            distinct = _distinct_candidates(matches)
            if len(distinct) == 1:
                latest = matches[-1]
                cit["resolved_to"] = {
                    "index": latest["index"],
                    "full_citation": latest["full_citation"],
                }
            elif len(distinct) > 1:
                _mark_unresolved(cit, distinct)
            else:
                # Name never introduced in text: metadata lookup could fix it.
                _mark_unresolved(cit, [])
                cit["flags"].append("needs_metadata")
            continue

        # Unrecognizable short form (defense in depth — shouldn't happen).
        _mark_unresolved(cit, [])

    return citations


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

    citations = [c for c in citations if not _inside_nickname(c)]

    consumed_claims = _attach_pincites(text, citations)
    citations.extend(_standalone_claims(text, citations, consumed_claims))
    citations.sort(key=lambda c: c["span"][0])
    return citations


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
    citations = resolve_patent_citations(get_patent_citations(cleaned))

    json.dump(citations, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
