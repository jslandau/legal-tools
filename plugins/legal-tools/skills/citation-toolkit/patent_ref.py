#!/usr/bin/env python3
"""
patent_ref.py — parse and classify patent numbers into fetchable/non-fetchable kinds.

Companion to cite-checking, chain-cite, and table-of-authorities workflows.
Parses a messy citation string (e.g., "US 8,453,642 B2", "60/123,456", "2009/0151718 A1")
into a structured PatentRef categorizing the patent kind and extracting canonical numbers
for later lookup or display.

Designed as a pure Functional Core — no I/O, no network, fully testable offline.
Follows the same batch entry-point pattern as lii_fetcher.py and eyecite_extract.py:
`process(list[dict]) -> list[dict]` + `main(argv)` with `--input`/stdin JSON I/O.

Usage:

    # From a file containing the input JSON array:
    python3 patent_ref.py --input requests.json

    # From stdin:
    cat requests.json | python3 patent_ref.py

Input (JSON array on stdin or via --input). One object per citation string:

    [
      {"id": "p1", "raw": "US 8,453,642 B2"},
      {"id": "p2", "raw": "60/123,456"},
      {"id": "p3", "raw": "2009/0151718 A1"},
      {"id": "p4", "raw": "banana"}
    ]

  - id:  opaque caller-supplied identifier; echoed back in the output.
  - raw: raw patent citation string to parse and classify.

Output (JSON array on stdout, one object per input entry, same order):

    [
      {
        "id": "p1",
        "kind": "grant",
        "canonical_number": "8453642",
        "display": "U.S. Patent No. 8,453,642",
        "fetchable": true,
        "reason": null
      },
      {
        "id": "p2",
        "kind": "provisional",
        "canonical_number": "123456",
        "display": "U.S. Provisional Application No. 60/123456",
        "fetchable": false,
        "reason": "provisional applications are not publicly retrievable"
      },
      {
        "id": "p3",
        "kind": "apppub",
        "canonical_number": "20090151718",
        "display": "U.S. Patent Application Pub. No. 2009/0151718",
        "fetchable": true,
        "reason": null
      },
      {
        "id": "p4",
        "kind": "unsupported",
        "canonical_number": "",
        "display": "banana",
        "fetchable": false,
        "reason": "unrecognized patent number format"
      }
    ]

PatentRef semantics:
  - kind:              "grant" (utility/design/plant/reissue),
                       "apppub" (application publication),
                       "provisional" (provisional application),
                       "unsupported" (unrecognized format)
  - canonical_number:  grant-utility: digits only ("8453642")
                       design/plant/reissue: letter-prefixed ("D645062", "PP12345", "RE38161")
                       apppub: 11-digit concatenated ("20090151718")
                       unsupported: best-effort isolated digits (may be "" if none)
  - display:           human-readable display form with commas and label
  - fetchable:         true for grant|apppub; false for provisional|unsupported
  - reason:            why non-fetchable/unclassifiable; None when fetchable

Dependencies: stdlib only. No `pip install` required.

# pattern: Functional Core
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import TypedDict


class PatentRef(TypedDict):
    """Structured representation of a parsed patent reference."""
    kind: str  # "grant" | "apppub" | "provisional" | "unsupported"
    canonical_number: str  # digits only or letter-prefixed per kind
    display: str  # human-readable form
    fetchable: bool  # true for grant|apppub; false for provisional|unsupported
    reason: str | None  # why non-fetchable/unclassifiable


# ---------------------------------------------------------------------------
# Helper functions — pure, testable utilities
# ---------------------------------------------------------------------------

def _strip_noise(raw: str) -> str:
    """Normalize and strip leading noise tokens from a raw patent string.

    - Uppercase the working copy
    - Strip surrounding whitespace
    - Remove leading noise tokens: U.S., US, UNITED STATES, PATENT, APPLICATION,
      PUBLICATION, PUB., NO., NO, #, PAT.
    - Remove commas
    - Collapse internal whitespace

    Returns the cleaned string.
    """
    s = raw.strip().upper()

    # Noise tokens to strip from the beginning (in order of specificity)
    noise_tokens = [
        "U.S. PATENT NO.",
        "U.S. PATENT APPLICATION PUBLICATION NO.",
        "U.S. PATENT APPLICATION PUB. NO.",
        "U.S. PATENT APPLICATION PUBLICATION",
        "U.S. PATENT APPLICATION PUB.",
        "U.S. PATENT APPLICATION",
        "U.S. PATENT",
        "U.S. NO.",
        "UNITED STATES PATENT NO.",
        "UNITED STATES PATENT",
        "U.S.",
        "US",
        "UNITED STATES",
        "PATENT APPLICATION PUBLICATION",
        "PATENT APPLICATION PUB.",
        "PATENT APPLICATION",
        "PATENT NO.",
        "PATENT",
        "APPLICATION PUBLICATION",
        "APPLICATION PUB.",
        "APPLICATION",
        "PUBLICATION",
        "PUB.",
        "NO.",
        "NO",
        "PAT.",
        "#",
    ]

    # Strip noise tokens from the beginning, case-insensitive
    for token in noise_tokens:
        if s.startswith(token):
            s = s[len(token):].strip()
            break

    # Remove commas
    s = s.replace(",", "")

    # Collapse internal whitespace
    s = re.sub(r"\s+", " ", s).strip()

    return s


def _strip_kind_code(token: str) -> str:
    """Remove a trailing kind code from a token.

    Kind codes: B1, B2, B9, A1, A2, A9, C1, E1.

    For example, "8453642B2" -> "8453642", "8453642" -> "8453642".
    """
    # Match a trailing kind code (space-separated or not)
    match = re.match(r"^(.*?)\s*([AB][129]|B1|C1|E1)$", token)
    if match:
        return match.group(1).strip()
    return token


def _group_digits(digits: str) -> str:
    """Comma-group a digit run from the right in 3s.

    For example, "8453642" -> "8,453,642", "645062" -> "645,062".
    """
    if not digits or not digits.isdigit():
        return digits

    # Reverse, insert commas every 3 chars, then reverse back
    reversed_digits = digits[::-1]
    grouped = ",".join(reversed_digits[i:i+3] for i in range(0, len(reversed_digits), 3))
    return grouped[::-1]


def _isolated_digits(raw: str) -> str:
    """Extract all digit characters from a string, concatenated.

    For example, "app no. 13/995,123 garbled" -> "13995123", "banana" -> "".
    """
    return "".join(c for c in raw if c.isdigit())


# ---------------------------------------------------------------------------
# Patent parsing and classification
# ---------------------------------------------------------------------------

def parse_patent_ref(raw: str) -> PatentRef:
    """Parse and classify a patent reference string.

    Classification algorithm (apply in order; first match wins):

    1. Normalize: uppercase, strip whitespace, remove noise tokens and commas.
    2. Provisional: if form is 60/NNNNNN, 61/NNNNNN, or 62/NNNNNN.
    3. App-pub: if form is YYYY/NNNNNNN (with optional A1/A2/A9 kind code) or
       11-digit concatenated YYYYNNNNNNN (with plausible year prefix 19xx/20xx).
    4. Design grant: if leading D followed by digits.
    5. Plant grant: if leading PP followed by digits.
    6. Reissue grant: if leading RE followed by digits.
    7. Utility grant: if 7–10 digits (after stripping kind code).
    8. Unsupported: anything else.
    """
    # Normalize
    normalized = _strip_noise(raw)
    has_slash = "/" in raw

    # Try provisional: 60/NNNNNN, 61/NNNNNN, 62/NNNNNN
    if re.match(r"^(60|61|62)/\d{6}$", normalized):
        # Extract the 6 digits after the slash
        match = re.match(r"^(60|61|62)/(\d{6})$", normalized)
        digits = match.group(2) if match else ""
        return PatentRef(
            kind="provisional",
            canonical_number=digits,
            display=f"U.S. Provisional Application No. {match.group(1) if match else ''}/{digits}",
            fetchable=False,
            reason="provisional applications are not publicly retrievable",
        )

    # Try app-pub: slash form YYYY/NNNNNNN with optional kind code
    match = re.match(r"^(19|20)\d{2}/\d{7}(?:\s+([A-Z]\d))?$", normalized)
    if match:
        year_part = normalized.split("/")[0]
        digit_part = normalized.split("/")[1].split()[0]
        canonical = year_part + digit_part  # 11-digit form
        display_canonical = f"{year_part}/{digit_part}"
        return PatentRef(
            kind="apppub",
            canonical_number=canonical,
            display=f"U.S. Patent Application Pub. No. {display_canonical}",
            fetchable=True,
            reason=None,
        )

    # Try app-pub: concatenated 11-digit form YYYYNNNNNNN
    match = re.match(r"^(19|20)(\d{2})(\d{7})$", normalized)
    if match:
        canonical = normalized
        display_year_part = match.group(1) + match.group(2)
        display_digit_part = match.group(3)
        return PatentRef(
            kind="apppub",
            canonical_number=canonical,
            display=f"U.S. Patent Application Pub. No. {display_year_part}/{display_digit_part}",
            fetchable=True,
            reason=None,
        )

    # Try design grant: leading D followed by digits
    match = re.match(r"^D(\d+)$", normalized)
    if match:
        digits = match.group(1)
        return PatentRef(
            kind="grant",
            canonical_number=f"D{digits}",
            display=f"U.S. Patent No. D{_group_digits(digits)}",
            fetchable=True,
            reason=None,
        )

    # Try plant grant: leading PP followed by digits
    match = re.match(r"^PP(\d+)$", normalized)
    if match:
        digits = match.group(1)
        return PatentRef(
            kind="grant",
            canonical_number=f"PP{digits}",
            display=f"U.S. Plant Patent No. PP{_group_digits(digits)}",
            fetchable=True,
            reason=None,
        )

    # Try reissue grant: leading RE followed by digits
    match = re.match(r"^RE(\d+)$", normalized)
    if match:
        digits = match.group(1)
        return PatentRef(
            kind="grant",
            canonical_number=f"RE{digits}",
            display=f"U.S. Reissue Patent No. RE{_group_digits(digits)}",
            fetchable=True,
            reason=None,
        )

    # Try utility grant: 7–10 digits (after stripping kind code)
    # Strip trailing kind code first
    token = _strip_kind_code(normalized)
    match = re.match(r"^(\d{7,10})$", token)
    if match:
        digits = match.group(1)
        return PatentRef(
            kind="grant",
            canonical_number=digits,
            display=f"U.S. Patent No. {_group_digits(digits)}",
            fetchable=True,
            reason=None,
        )

    # Unsupported: anything else
    best_effort_digits = _isolated_digits(raw)
    return PatentRef(
        kind="unsupported",
        canonical_number=best_effort_digits,
        display=raw.strip(),
        fetchable=False,
        reason="unrecognized patent number format",
    )


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def process(entries: list[dict]) -> list[dict]:
    """Process a batch of patent references.

    For each entry in the input list with keys {"id", "raw"}, call parse_patent_ref(raw)
    and emit {"id": <echoed>, **patent_ref}, preserving order.

    Args:
        entries: List of dicts with keys "id" and "raw".

    Returns:
        List of dicts with keys "id", "kind", "canonical_number", "display", "fetchable", "reason".
    """
    results: list[dict] = []
    for entry in entries:
        entry_id = entry.get("id")
        raw = entry.get("raw", "")
        patent_ref = parse_patent_ref(raw)
        result = {"id": entry_id, **patent_ref}
        results.append(result)
    return results


def main(argv: list[str]) -> int:
    """Main entry point for CLI usage.

    Reads a JSON array of patent reference objects from --input file or stdin.
    Writes results to stdout as a JSON array with indentation.

    Args:
        argv: Command-line arguments.

    Returns:
        0 on success, 2 on JSON error or invalid input structure.
    """
    parser = argparse.ArgumentParser(
        description="Parse and classify patent numbers. "
                    "Reads a JSON array of patent references; writes a JSON "
                    "array of classified results to stdout.",
    )
    parser.add_argument("--input", help="Path to input JSON file. If omitted, read stdin.")
    args = parser.parse_args(argv)

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            payload = f.read()
    else:
        payload = sys.stdin.read()

    try:
        entries = json.loads(payload)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"ERROR: input is not valid JSON: {e}\n")
        return 2
    if not isinstance(entries, list):
        sys.stderr.write("ERROR: input JSON must be an array of request objects.\n")
        return 2

    results = process(entries)
    json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
