# Patent Tooling (extraction, fetch, column:line, verification)

Reference companion to `citation-toolkit/SKILL.md`. Read this file when a run contains patent citations. The patent taxonomy, short forms, and the Patents structured-component schema live in SKILL.md; this file documents the scripts: `patent_eyecite.py`, `patent_extract.py`, `patent_query.py`, `patent_verify.py`.


## Extraction: `patent_eyecite.py`

Extracts every patent citation from brief or document text — the patent sibling of `eyecite_extract.py`. Like eyecite, the tool extracts, parses, and resolves short forms in a single local pass. Document text never leaves the machine.

### How to run patent_eyecite locally

The script lives in this skill's directory: `patent_eyecite.py`. It reads from a file or stdin and emits a JSON array of toolkit-shaped patent citation entries on stdout.

```bash
python3 plugins/legal-tools/skills/citation-toolkit/patent_eyecite.py --input brief.txt
# or:
cat brief.txt | python3 plugins/legal-tools/skills/citation-toolkit/patent_eyecite.py
```

The script does not make any network calls. Default run is fully offline and stdlib-only (imports only `patent_ref.py`).

### Sample output

One entry per citation, document order:

```json
[
  {
    "citation_type": "patent",
    "full_citation": "U.S. Patent No. 8,453,642",
    "span": [120, 146],
    "ref": {
      "kind": "grant",
      "canonical_number": "8453642",
      "display": "U.S. Patent No. 8,453,642",
      "fetchable": true,
      "reason": null
    },
    "pincite": {
      "kind": "column_line",
      "start_column": 5,
      "start_line": 12,
      "end_column": 5,
      "end_line": 18
    },
    "nickname": "the '642 patent",
    "resolved_to": null,
    "flags": []
  }
]
```

### Three-layer API

The script's three public functions mirror eyecite's design:

- **`clean_patent_text(text)`** → `str` — normalizes text for matching (curly quotes, dashes, newlines become their ASCII equivalents). Strictly 1:1 character replacement; spans computed on the cleaned text are valid in the original.
- **`get_patent_citations(text)`** → `list` — finds all patent citations in cleaned text, parses them, and attaches pincites.
- **`resolve_patent_citations(cites)`** → `list` — single forward pass filling `resolved_to` on short forms and standalone claims using a running stack. Unresolvable entries are flagged, never dropped.

### Pincite gating contract

Pincites attach only within approximately 80 characters after a citation, crossing only whitespace, commas, and the word "at". A bare `N:M` outside this window is never emitted. In-window compact matches carrying an adjacent `§` are flagged `ambiguous_pincite` (the `§` signals the `N:M` may be a statute section, not a column:line reference).

### Flag vocabulary

- **`unresolved_short_form`** — Could not link a short form (`'NNN` or inventor-name) to a full citation in the running stack. Includes a `candidates` list of entry indices where collisions occur, so the consuming skill can prompt the user.
- **`ambiguous_pincite`** — Compact `N:M` match carries a `§` signal; the proximity gating accepted it but the brief's context is ambiguous.
- **`needs_metadata`** — Inventor-name short form (`"the Kwok patent"`) was never introduced in preceding text. Re-run with `--resolve-metadata` to attempt network resolution.

### Network opt-in: `--resolve-metadata`

```bash
python3 plugins/legal-tools/skills/citation-toolkit/patent_eyecite.py \
  --input brief.txt \
  --resolve-metadata \
  --cache-dir ./patent_cache
```

Sends **patent numbers only** (never document text) to Google Patents to fetch inventor lists for any short form flagged `needs_metadata`. Uses `patent_fetch.py`'s caching to avoid redundant requests. The `--cache-dir` option specifies where to store cached HTML; defaults to `patent_fetch.py`'s `patent_cache/` directory.

---

## Patent column:line extraction

US patent documents cite column and line numbers — e.g., `4:32-38` means column 4, lines 32–38 — to pinpoint passages in their specification. This skill provides tools to extract, query, and verify these citations locally without leaving the machine.

### Build phase: `patent_extract.py`

The extraction script reads a patent PDF with an embedded text layer and produces a structured JSON artifact mapping every printed line to its `(column, line)` coordinates. The script is local-only — the PDF never leaves your machine.

```bash
python3 plugins/legal-tools/skills/citation-toolkit/patent_extract.py build --input US9154231.pdf --out us9.json
```

Output: a `PatentDoc` JSON artifact with `lines` (each tagged with `column`, `line`, `text`, `kind`, and `page_index`) and diagnostic `page_fits` (including per-page confidence signals like `max_marker_residual` and `signal` status). For high-confidence pages, `max_marker_residual` is `0` (perfect line alignment); pages flagged as non-body content have a residual of `−1`.

**Dependency:** `pip install pdfplumber`. On PEP-668 systems (recent Linux distros), use a venv:
```bash
python3 -m venv .venv && .venv/bin/pip install pdfplumber
.venv/bin/python plugins/legal-tools/skills/citation-toolkit/patent_extract.py build --input US9154231.pdf --out us9.json
```

### Query phase: `patent_query.py`

Once you have an artifact, resolve column:line citations instantly using the query script — no PDF re-parsing, no network calls, pure local lookup. The query script supports single-line citations, same-column spans, and cross-column spans (reading across gutter boundaries).

```bash
# Single line
python3 plugins/legal-tools/skills/citation-toolkit/patent_query.py --artifact us9.json --cite 5:1

# Same-column span (column 4, lines 32 through 38)
python3 plugins/legal-tools/skills/citation-toolkit/patent_query.py --artifact us9.json --cite 4:32-38

# Cross-column span (column 4 line 65 through column 5 line 3)
python3 plugins/legal-tools/skills/citation-toolkit/patent_query.py --artifact us9.json --cite 4:65-5:3

# Span with true blank line (rendered as blank in output)
python3 plugins/legal-tools/skills/citation-toolkit/patent_query.py --artifact us9.json --cite 3:49-51
```

Output: the joined printed text for the requested span on stdout, with lines separated by newline. Cross-column citations read in document order: start column from start_line to its max_line, each intermediate column 1 to its max_line, then end column from 1 to end_line.

**Line numbering truth model:** US patents number every physical line slot by a gutter grid — the printed margin numbers (multiples of 5) are authoritative anchors, and the grid pitch is the truth source. The text leading drifts from the grid over the course of a page (~0.33pt per line), so line numbers are assigned per-grid-slot, not per-text-row. Each slot in the extracted artifact carries a `kind` field classifying it:

- `text` — a printed line with content (text is non-empty).
- `blank` — a real printed empty line (e.g., the vertical gap around a centered heading); text is empty.
- `spurious` — a grid slot the drifting text skipped (no actual line printed there); text is empty. Spurious slots appear when the text leading clusters and the gutter grid drifts below the actual printed lines.
- `unknown` — a slot on a marker-less page (claims tail with no gutter numerals) where the kind cannot be reliably classified; text is empty (a printed line is emitted as `text`, never `unknown`). Emitted only by the marker-less extraction path.

The artifact upholds the invariant `text != "" iff kind == "text"`: only `text` slots carry content; `blank`, `spurious`, and `unknown` slots all have empty text.

**Query contract:** When you request a span `start_col:start_line`–`end_col:end_line`:

- `text` slots are rendered at full content.
- True `blank` slots (interior to the span, not at span edges) are rendered as empty lines, preserving the printed vertical structure.
- `spurious` slots are skipped silently — bracketing `text` is contiguous and reads continuously.
- **Ambiguity signal:** A span shorter than 5 lines (the `AMBIGUITY_MAX_SPAN` threshold), or a single cite (`cite_width=1`), that **touches** a `spurious` or `unknown` slot raises an `AmbiguousCiteError` (exit code 3). This signals that the grid is unreliable at that scale; the error still returns the likely-intended text (the consecutive physical lines from the start; for a single cite, both neighbors). The human can disambiguate by inspecting the PDF.
- Spans of 5+ lines render normally without raising an ambiguity signal — at large scales, humans anchor visually, not by counting, so the signal is not useful.

Exit codes: 0 (ok) / 1 (cite error: malformed, out of range, column absent) / 2 (missing artifact) / 3 (ambiguous cite: returned text but grid is unreliable).

**Marker-less best-effort:** Claims tails (single-column pages at document end) often have no gutter numerals. The extraction allocates columns and emits printed lines as `kind=text`, filling the gaps between them with `kind=unknown` slots (empty text) where classification is uncertain. Numbering is borrowed-pitch best-effort (assuming the text leading continues at the observed average pitch). Text cites on marker-less pages can resolve, but an `unknown` slot signals lower confidence.

**CLEAN/NOISY diagnostic:** Each column in the artifact is flagged `signal: "CLEAN"` or `signal: "NOISY"` in the `page_fits` metadata. This is a per-column quality flag that warns (to stderr during build) of possible OCR fragmentation (undue word clustering at one y-center). The flag is **diagnostic-only** — it does NOT change the emitted line kinds, numbering, or query behavior. (The original premise that NOISY columns warrant fallback blank-rendering did not reproduce on the production extraction path, which clusters words into one y-center per actual printed row. See the project memory `project_patent_noisy_gate_demoted`.)

The query script is stdlib-only — no dependencies beyond Python 3.

### Verify phase: `patent_verify.py`

Querying returns the text *at* a cite. Verifying answers a different question: does a brief's quoted passage actually appear at (or near) the cite it claims? `patent_verify.py` supports an LLM-driven quote-location ladder — the script does the deterministic normalization and coordinate math; the model does the matching (it never sees the brief's quote, only blob text the script emits).

It is a batch-JSON primitive like `patent_ref.py`/`patent_fetch.py`: a JSON array of request objects on `--input` (or stdin) → a JSON array of results on stdout, echoing each entry's `id` in order. Each entry carries a `mode` and its own `artifact_path` (loaded per entry; a missing or unreadable artifact yields a `status:"error"` result object, not a hard exit — only malformed top-level JSON input exits 2).

```bash
# emit: normalize the cited region into a clean blob the LLM can match against
echo '[{"id":"e1","mode":"emit","artifact_path":"us9.json","cite":"5:1-10"}]' \
  | python3 plugins/legal-tools/skills/citation-toolkit/patent_verify.py

# resolve: locate a verbatim slice (copied from the emitted blob) back to a coordinate
echo '[{"id":"r1","mode":"resolve","artifact_path":"us9.json","substring":"a widget that","within":"5:1-14","retried":false}]' \
  | python3 plugins/legal-tools/skills/citation-toolkit/patent_verify.py
```

- **`emit`** returns `window_blob` (the cited region ±10% expanded) and `body_blob` (the whole specification), both newline-free, plus `cited_coord`, `window_coord_range`, and an `ambiguity` flag (set when the cited region touches a `spurious`/`unknown` slot — the grid drift signal from the query layer, here triggering a wider window rather than an error).
- **`resolve`** takes a substring the LLM matched and returns `found_at` (a `c:l` or `sc:sl-ec:el` coordinate string) with `match_scope` (`"window"` or `"body"` — the tier the hit came from). It searches the window first, then the full body in a single call. Multiple hits return `ambiguous_match` (with a `retry` instruction, or — when `retried:true` — all hit coordinates), never a silent first-hit. The re-normalize guard is whitespace-only and case-exact: a whitespace slip still resolves, but a case difference does not (patents capitalize defined terms deliberately).

The LLM-facing ladder that drives these two modes is documented in `cite-checking`'s Stage 5. `patent_verify.py` is stdlib-only and imports cite parsing / ambiguity detection from `patent_query.py` rather than reimplementing them.

### Architecture

The build-once/query-many split is intentional. The geometric complexity (gutter detection, line-model fitting, per-page marker-residual confidence) lives in `patent_extract.py`. The query and verify layers (`patent_query.py`, `patent_verify.py`) see only the finalized artifact — they are pure functions over JSON, suitable for downstream consumption by cite-check without exposing linemodel internals. `patent_query.py` resolves a cite to its text; `patent_verify.py` builds the normalized blobs and coordinate index that let an LLM confirm a brief's quote sits at the cite. Both reuse `patent_query`'s cite parsing and ambiguity detection rather than duplicating it.

### Privacy and scope

- **Local-only:** The PDF and extracted text never leave the machine. Both scripts run entirely offline.
- **Confidence signals:** Each page's diagnostic includes `is_body` (boolean — is this a numbered column:line page whose text is extracted and which consumes column numbers), `flagged` (boolean — does the page warrant a human look) and `flag_reason` (string), plus the per-page `max_marker_residual` confidence metric. `is_body` and `flagged` are usually opposites, but a body page can be both (e.g. a gutter cross-check disagreement is extracted *and* surfaced for review). Use these to assess extraction confidence before relying on a document's citations.
- **Page classification (voting rule):** A page is body text if it has a clean gutter line-model fit, OR both column-number headers, OR at least two of {≥2 gutter markers, ≥1 column header, ≥100 words}. This admits single-column **claims tails** — including very short ones with zero multiple-of-5 gutter line-numbers, where the gutter is recovered from the column-header midpoint. Marker-less columns emit `unknown` slots rather than guessing blanks.
- **Citation recognition:** Patent-cite recognition is implemented by `patent_eyecite.py` (including the proximity-gated `4:32-38` pincite rules); cite-checking consumes its output.

