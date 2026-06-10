#!/usr/bin/env python3
# pattern: Imperative Shell
"""
patent_fetch.py — fetch original text-layered PDFs for US patents from
Google Patents, with runtime extractability (usability) check.

Companion to patent_extract.py. Where patent_extract.py reads a local
patent PDF and builds a line-extracted artifact, patent_fetch.py discovers
and downloads the original PDF from Google Patents using the citation_pdf_url
meta tag, then verifies it has a usable text layer.

Scope:
- Utility grants, design patents, reissues, plant patents, and application
  publications ("apppub") from the USPTO/Google Patents. Other kinds (provisional,
  unsupported) are rejected without a network call (defense-in-depth guard).
- Source is exclusively Google Patents `citation_pdf_url` meta tag (not USPTO
  PDFs, which are image-only without a text layer).
- Usability gate reuses patent_extract.page_word_counts + has_text_layer,
  which counts extractable words per page. This phase emits text_words (summed
  page_word_counts) rather than text_chars, as a faithful realization of the
  "is there an extractable text layer?" decision against the existing word-count
  model.

Usage:

    # From a file containing the input JSON array:
    python3 patent_fetch.py --input requests.json

    # From stdin:
    cat requests.json | python3 patent_fetch.py

Input (JSON array on stdin or via --input). One object per patent:

    [
      {"id": "p1", "kind": "grant", "canonical_number": "8453642"},
      {"id": "p2", "kind": "apppub", "canonical_number": "20090151718"}
    ]

  - id:                 opaque caller-supplied identifier; echoed back in output.
  - kind:               "grant" (utility/design/plant/reissue) or "apppub", as
                        emitted by patent_ref.py. Only these two are fetchable; any
                        other kind (e.g. "provisional", "unsupported") is rejected
                        without a network call.
  - canonical_number:   patent number as a string, e.g., "8453642" for US8453642.
                        Design/plant/reissue grants carry kind="grant" with the
                        type code kept in the number (e.g., "D645062", "PP12345",
                        "RE38161").

Output (JSON array on stdout, one object per input entry, same order):

    [
      {
        "id": "p1",
        "status": "ok",                                    # ok | not_located | image_only | rejected
        "kind": "grant",
        "pdf_path": ".../patent_cache/US8453642.pdf",
        "source_url": "https://patentimages.storage.googleapis.com/.../US8453642.pdf",
        "text_words": 2451,
        "reason": null
      }
    ]

Status semantics:
  - "ok":         PDF fetched, text layer verified usable (>= MIN_TOTAL_WORDS).
  - "not_located": Discovery failure (page 404, no citation_pdf_url meta tag,
                   fetch failure, or PDF body doesn't start with %PDF).
                   pdf_path, source_url, text_words are null.
  - "image_only": PDF fetched but text layer unusable (< MIN_TOTAL_WORDS words).
                   pdf_path is set, source_url is set, text_words is the
                   true summed page_word_counts.
  - "rejected":   Kind not in {grant, apppub}. No network call.
                   pdf_path, source_url, text_words are null.

Dependencies: stdlib only (argparse, json, re, sys, time, urllib.request, pathlib),
plus pdfplumber (already declared in requirements-dev.txt). patent_extract.py
provides the usability gate (page_word_counts, has_text_layer, MIN_TOTAL_WORDS).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from patent_extract import has_text_layer, page_word_counts

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TIMEOUT_SECONDS = 20
REQUEST_SPACING_SECONDS = 2.0
MAX_429_RETRIES = 3
PATENT_PAGE_TMPL = "https://patents.google.com/patent/{id}/en"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / "patent_cache"


# ---------------------------------------------------------------------------
# Pure helpers (Functional Core — no I/O, testable offline)
# ---------------------------------------------------------------------------


def google_id(kind: str, canonical_number: str) -> str:
    """Construct the Google Patents ID for a patent.

    Utility grants and app-pubs: "US" + canonical_number (no kind code).
    Design/plant/reissue: "US" + canonical_number (letters kept, part of
    the canonical number).

    Examples:
        google_id("grant", "8453642") → "US8453642"
        google_id("grant", "D645062") → "USD645062"
        google_id("apppub", "20090151718") → "US20090151718"
    """
    return f"US{canonical_number}"


def extract_citation_pdf_url(html: str) -> str | None:
    """Extract the citation_pdf_url from a Google Patents page HTML.

    Regex-match the <meta name="citation_pdf_url" content="..."> tag (or
    content-before-name attribute order). Return the content value or None
    if the tag is absent.

    The regex is tolerant of attribute order:
        <meta name="citation_pdf_url" content="...">
        <meta content="..." name="citation_pdf_url">
    """
    # Match <meta ...> tag containing both name="citation_pdf_url" and
    # content="(...)". Use two separate regexes to handle both attribute orders.
    # First try: name before content
    match = re.search(
        r'<meta\s+name="citation_pdf_url"\s+content="([^"]+)"', html, re.IGNORECASE
    )
    if match:
        return match.group(1)

    # Second try: content before name
    match = re.search(
        r'<meta\s+content="([^"]+)"\s+name="citation_pdf_url"', html, re.IGNORECASE
    )
    if match:
        return match.group(1)

    return None


def decide_status(*, located: bool, usable: bool) -> str:
    """Pure status decision based on discovery and usability.

    Args:
        located: True if the PDF was successfully downloaded.
        usable: True if the PDF has an extractable text layer.

    Returns:
        "ok" if located and usable.
        "image_only" if located but not usable.
        "not_located" if not located.
    """
    if not located:
        return "not_located"
    if not usable:
        return "image_only"
    return "ok"


def cache_path(cache_dir: Path, google_id: str) -> Path:
    """Return the cache file path for a patent PDF."""
    return cache_dir / f"{google_id}.pdf"


_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_META_ATTR_RE = re.compile(r'([\w.:-]+)="([^"]*)"')


def extract_patent_metadata(html: str) -> dict:
    """Parse title/inventors/assignee meta tags from a Google Patents page.

    Attribute order inside each <meta> tag is irrelevant. Returns:
        {"title": str | None, "inventors": [str, ...], "assignee": str | None}
    Inventors keep page order (first-named inventor first).
    """
    title: str | None = None
    inventors: list[str] = []
    assignee: str | None = None

    for tag in _META_TAG_RE.findall(html):
        attrs = dict(_META_ATTR_RE.findall(tag))
        name = attrs.get("name", "")
        content = attrs.get("content", "")
        if not content:
            continue
        if name == "DC.title" and title is None:
            title = content.strip()
        elif name == "DC.contributor":
            scheme = attrs.get("scheme", "")
            if scheme == "inventor":
                inventors.append(content.strip())
            elif scheme == "assignee" and assignee is None:
                assignee = content.strip()

    return {"title": title, "inventors": inventors, "assignee": assignee}


def page_cache_path(cache_dir: Path, google_id: str) -> Path:
    """Return the cache file path for a patent page's HTML."""
    return cache_dir / f"{google_id}.html"


# ---------------------------------------------------------------------------
# I/O functions (Imperative Shell)
# ---------------------------------------------------------------------------


def http_get(url: str) -> tuple[bytes | None, int | None, str | None]:
    """GET request with User-Agent, return (body, http_status, error).

    Returns:
        (body_bytes, http_status, error_string) where error_string is None on
        success (status 200-299), and body_bytes is None on failure.

    On HTTPError: return its code.
    On URLError, TimeoutError, OSError: return error string, status None.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            if resp.status >= 400:
                return None, resp.status, None
            return resp.read(), resp.status, None
    except urllib.error.HTTPError as e:
        return None, e.code, None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, None, f"{type(e).__name__}: {e}"


def fetch_with_backoff(url: str) -> tuple[bytes | None, int | None, str | None]:
    """GET with 429 retry backoff.

    On HTTP 429, sleep for REQUEST_SPACING_SECONDS * (attempt+1) and retry
    up to MAX_429_RETRIES times. Return the last result.
    """
    for attempt in range(MAX_429_RETRIES + 1):
        body, status, error = http_get(url)
        if status != 429:
            return body, status, error
        if attempt < MAX_429_RETRIES:
            sleep_time = REQUEST_SPACING_SECONDS * (attempt + 1)
            time.sleep(sleep_time)
    return body, status, error


def discover_pdf_url(google_id: str) -> tuple[str | None, str | None]:
    """Fetch the Google Patents page and extract the PDF URL.

    Returns:
        (pdf_url, error) where error is a diagnostic string on failure,
        and pdf_url is None on failure.
    """
    url = PATENT_PAGE_TMPL.format(id=google_id)
    body, status, error = fetch_with_backoff(url)

    if status != 200:
        if error:
            return None, error
        return None, f"page {status}" if status else "unknown error"

    if not body:
        return None, "empty page"

    html = body.decode("utf-8", errors="replace")
    pdf_url = extract_citation_pdf_url(html)

    if pdf_url is None:
        return None, "citation_pdf_url not found"

    return pdf_url, None


def download_pdf(pdf_url: str, dest: Path) -> tuple[bool, str | None]:
    """Download PDF from pdf_url, verify %PDF signature, write to dest.

    Returns:
        (success, error) where success is True on success, and error is
        a diagnostic string on failure.
    """
    body, status, error = fetch_with_backoff(pdf_url)

    if status != 200:
        if error:
            return False, error
        return False, f"PDF fetch status {status}"

    if not body or not body.startswith(b"%PDF"):
        return False, "response does not start with %PDF signature"

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.write_bytes(body)
        return True, None
    except OSError as e:
        return False, f"failed to write {dest}: {e}"


def fetch_patent_metadata_batch(
    google_ids: list[str], cache_dir: Path
) -> dict[str, dict]:
    """Fetch (with HTML caching) and parse metadata for each Google Patents id.

    Returns {google_id: metadata_dict} for every id whose page was obtained;
    failed ids are simply absent (callers treat absence as still-unresolved).
    Applies REQUEST_SPACING_SECONDS between live fetches; cache hits are free.
    Only patent numbers go over the wire — never document text.
    """
    results: dict[str, dict] = {}
    fetched_any = False

    for gid in google_ids:
        cached = page_cache_path(cache_dir, gid)
        if cached.exists():
            html = cached.read_text(encoding="utf-8")
            results[gid] = extract_patent_metadata(html)
            continue

        if fetched_any:
            time.sleep(REQUEST_SPACING_SECONDS)
        url = PATENT_PAGE_TMPL.format(id=gid)
        body, status, _error = fetch_with_backoff(url)
        fetched_any = True
        if status != 200 or not body:
            continue

        html = body.decode("utf-8", errors="replace")
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(html, encoding="utf-8")
        results[gid] = extract_patent_metadata(html)

    return results


# ---------------------------------------------------------------------------
# Per-entry orchestration
# ---------------------------------------------------------------------------


def fetch_one(entry: dict, cache_dir: Path) -> dict:
    """Fetch one patent PDF and return the result object.

    Args:
        entry: {"id": "...", "kind": "...", "canonical_number": "..."}
        cache_dir: directory for cached PDFs

    Returns:
        Result dict with status, id, kind, pdf_path, source_url, text_words, reason.
    """
    entry_id = entry.get("id")
    kind = entry.get("kind")
    canonical_number = entry.get("canonical_number")

    # Re-guard: reject non-fetchable kinds (defense-in-depth, AC2.2)
    if kind not in {"grant", "apppub"}:
        return {
            "id": entry_id,
            "status": "rejected",
            "kind": kind,
            "pdf_path": None,
            "source_url": None,
            "text_words": None,
            "reason": f"non-fetchable kind: {kind}",
        }

    gid = google_id(kind, canonical_number)
    dest = cache_path(cache_dir, gid)

    # Cache hit: skip discovery+download, go straight to usability check
    if dest.exists():
        try:
            counts = page_word_counts(dest)
            usable = has_text_layer(counts)
            text_words = sum(counts)
        except Exception as e:
            # Catch-all at pdfplumber boundary: any PDF parse failure degrades
            # gracefully to not_located rather than crashing the shell.
            return {
                "id": entry_id,
                "status": "not_located",
                "kind": kind,
                "pdf_path": None,
                "source_url": None,
                "text_words": None,
                "reason": f"cached PDF error: {e}",
            }

        status = decide_status(located=True, usable=usable)
        return {
            "id": entry_id,
            "status": status,
            "kind": kind,
            "pdf_path": str(dest),
            "source_url": None,  # Cached; source URL not available
            "text_words": text_words,
            "reason": None,
        }

    # Not cached: discover PDF URL
    pdf_url, discover_error = discover_pdf_url(gid)
    if pdf_url is None:
        return {
            "id": entry_id,
            "status": "not_located",
            "kind": kind,
            "pdf_path": None,
            "source_url": None,
            "text_words": None,
            "reason": discover_error,
        }

    # Download the PDF
    success, download_error = download_pdf(pdf_url, dest)
    if not success:
        return {
            "id": entry_id,
            "status": "not_located",
            "kind": kind,
            "pdf_path": None,
            "source_url": None,
            "text_words": None,
            "reason": download_error,
        }

    # Check usability gate on the downloaded PDF
    try:
        counts = page_word_counts(dest)
        usable = has_text_layer(counts)
        text_words = sum(counts)
    except Exception as e:
        # Catch-all at pdfplumber boundary: any PDF parse failure degrades
        # gracefully to not_located rather than crashing the shell.
        return {
            "id": entry_id,
            "status": "not_located",
            "kind": kind,
            "pdf_path": None,
            "source_url": None,
            "text_words": None,
            "reason": f"PDF usability check error: {e}",
        }

    status = decide_status(located=True, usable=usable)
    return {
        "id": entry_id,
        "status": status,
        "kind": kind,
        "pdf_path": str(dest),
        "source_url": pdf_url,
        "text_words": text_words,
        "reason": None,
    }


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------


def process(entries: list[dict], cache_dir: Path) -> list[dict]:
    """Process a batch of patent fetch requests.

    Preserves order. Sleeps REQUEST_SPACING_SECONDS between entries that
    touch the network (not after cache hits or rejects).
    """
    results: list[dict] = []
    last_network_time = None

    for i, entry in enumerate(entries):
        # Space out network requests (but not cache hits or rejects)
        entry_kind = entry.get("kind")
        if entry_kind in {"grant", "apppub"}:
            # This entry will try the network (unless cached); apply spacing
            if last_network_time is not None:
                elapsed = time.time() - last_network_time
                if elapsed < REQUEST_SPACING_SECONDS:
                    time.sleep(REQUEST_SPACING_SECONDS - elapsed)
            last_network_time = time.time()

        result = fetch_one(entry, cache_dir)
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    """Parse arguments, read JSON input, process, write JSON output."""
    parser = argparse.ArgumentParser(
        description="Fetch US patent PDFs from Google Patents with usability check. "
        "Reads a JSON array of patent requests; writes a JSON array of results to stdout.",
    )
    parser.add_argument(
        "--input", help="Path to input JSON file. If omitted, read stdin."
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=f"Directory for cached PDFs (default: {DEFAULT_CACHE_DIR})",
    )
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

    results = process(entries, args.cache_dir)
    json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
