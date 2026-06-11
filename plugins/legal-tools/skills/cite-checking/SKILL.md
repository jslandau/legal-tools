---
name: cite-checking
description: Use when verifying citations in a legal brief or document — extracts every citation locally via eyecite (document text never leaves the machine, important for privileged work product), looks up each source online via CourtListener and other public sources, extracts the pincite text, and produces a standalone report assessing how well each citation supports the proposition it is cited for, with a critic subagent review of each assessment
---

# Cite-Checking

## Prerequisites

This skill uses the citation taxonomy, short-form resolution rules, proposition-extraction rules, parenthetical handling, structured component schemas, flag vocabulary, and CourtListener API patterns defined in the `citation-toolkit` skill. Read `citation-toolkit` first; the stages below refer to its definitions by name rather than restating them.

When dispatching subtask subagents, follow the **Model Tiers for Subtasks** section of `citation-toolkit`: Stage 2 extraction and Stage 3 parsing are Haiku-tier; Stage 5 pincite extraction and Stage 6 support analysis are Sonnet-tier; the Stage 7 critic is Opus-tier by design.

## Overview

This skill takes a legal document and produces a standalone cite-check report. For every citation in the document the report shows:
- Whether the cited source was located
- A précis of what the source actually says at the pincite
- A qualitative assessment of how well the source supports the proposition it is cited for
- A critic subagent's independent assessment of that analysis

The source document is never modified.

## Before Starting

Ask the user:
1. **What is the document?** (file path or paste content)
2. **What format is it in?** PDF, plain text/Markdown, DOCX, or Word with tracked changes
3. **Where should the output be saved?** Three sibling files are produced: a human-readable Markdown report (`<original-filename>-cite-check.md`), a structured data file (`<original-filename>-cite-check.json`), and a self-contained interactive HTML report (`<original-filename>-cite-check.html`) that the user opens in a browser. Default location: same directory as the source document.
4. **CourtListener access.** If the `claude.ai CourtListener` MCP server is available, no token is needed — Stage 4 uses the MCP directly. Otherwise, ask for a CourtListener API token (free at courtlistener.com/sign-in/) and note it for the scripted-fallback path in Stage 4.

## Supported Formats

- **PDF:** Use the Read tool. Use the document's own page numbering (footers/headers), NOT raw PDF page numbers.
- **Plain text / Markdown:** Look for explicit page markers (e.g., `## PAGE 1`). Ask the user to clarify if not obvious.
- **DOCX / Word with tracked changes:** Extract text using the `docx_extract.py` script in this skill's directory. It emits paragraph text with footnotes inlined as `[FNx: ...]` markers, accepts accepted/inserted text, and drops deleted text:

  ```bash
  python3 plugins/legal-tools/skills/cite-checking/docx_extract.py path/to/brief.docx
  # or write to a file:
  python3 plugins/legal-tools/skills/cite-checking/docx_extract.py path/to/brief.docx --output extracted.txt
  ```

  Stdlib-only — no `pip install` required. Page boundaries in DOCX are approximate — warn the user.

---

## Stage 1 — Document Parsing

Read the document. Identify the substantive pages to process:

1. **Find body sections.** Look for headings: INTRODUCTION, ARGUMENT, STATEMENT OF THE CASE, STATEMENT OF FACTS, CONCLUSION. These are the pages to scan.
2. **Skip front matter.** Exclude cover pages, certificates of interest, tables of contents, any existing Table of Authorities, roman-numeral paginated pages.
3. **Skip back matter.** Exclude certificates of compliance, certificates of service, signature pages after CONCLUSION.
4. **Include footnotes** on substantive pages — they often contain important citations.
5. **Exclude non-authority references.** References to other briefs ("Blue Br.", "Appellant's Br."), appendix cites ("Appx123"), and record cites ("R. at 45") are not legal authorities — skip them.

**Retain document structure for JSON emission.** While walking the document, keep enough structure to populate the `document` block of the JSON output (Stage 8): substantive page numbers and their text, section headings and the page ranges they cover, and the footnote-id → footnote-text map (already produced by the DOCX script). For each citation captured in Stage 2, record its location as `{page, section, footnote_id?, snippet}` where `snippet` is the surrounding sentence (≈40–80 words centered on the citation) for use as in-context preview.

**Page numbering rule for `location.page`.** Use the brief's own page numbering — the number a reader sees in the document's footer/header. Not a 0-indexed offset, not an extraction-ordinal index, not a count of paragraphs. For PDFs, prefer the document's *printed* pagination over the raw PDF page index (cover pages, certificates of interest, TOCs, and tables of authority shift the offset, typically by several pages). For DOCX where the extraction script does not track pages directly, infer page boundaries from in-text page markers when present (e.g., `## PAGE 6`), and **always verify by spot-checking at least one emitted `location.page` value against the source brief before emitting any of them** — an off-by-one in page numbering propagates through every citation and silently breaks every downstream tool that uses page references. When unable to verify, ask the user to confirm one or two pages and calibrate the rest, rather than guessing.

---

## Stage 2 — Citation Extraction

Extraction is a two-pass process: **eyecite first, then a focused LLM gap pass for the gap categories.** Do not LLM-scan the document for *all* citations — that is what eyecite is for, and re-doing its work wastes tokens and introduces errors. The gap pass is a targeted read for only the categories eyecite cannot emit (below), not a free-form re-scan.

**Pass 1 — eyecite (authoritative for recognized types).** Follow the **"Extraction: eyecite is the primitive (local only)"** section of `citation-toolkit`. Run the local `eyecite_extract.py` script in `citation-toolkit/` — extraction stays on-machine because briefs are routinely privileged. **Do NOT use the MCP's `extract_citations` or `analyze_citations` for this** (they upload the document text). The script's output is a JSON array of citations in document order with `Id.`/`supra`/short cites already linked to their antecedents — that *is* your citation stack for Stage 3, no manual re-derivation needed.

**Pass 1b — patent extraction.** Run `patent_eyecite.py` once over the substantive text to extract every patent citation at document level (parallel to Pass 1 eyecite but for patents only):

```bash
python3 plugins/legal-tools/skills/citation-toolkit/patent_eyecite.py --input <text-file>
```

This produces a JSON array of patent entries (in document order) with:
- **Spans** (start/end offsets in the original text)
- **Parsed `ref`** (a `PatentRef` from `patent_ref.py` — kind, canonical_number, fetchable, reason)
- **Pincites** (structured: `column_line` with start/end column/line for grants, `paragraph` for app-pubs, `claims` for claim ranges)
- **Nicknames** (from parenthetical introductions, e.g., "the '642 patent")
- **Short-form resolution** (already resolved against the running stack within the script; short forms pointing to full citations carry `resolved_to`)

All of this is already extracted and parsed — no manual patent-string parsing required in this skill. Like eyecite, the script handles both full citations and short forms in a single pass.

**Pass 2 — gap pass (recall backstop only).** Walk the substantive text *once* looking only for the non-patent gap categories listed in `citation-toolkit` (administrative decisions, EU/international cases, popular-name statutes, informal constitutional references, state constitutional provisions, statute subsection breakdowns). Add these to the arrays produced by Pass 1 (eyecite) and Pass 1b (patent_eyecite). Do not re-extract anything eyecite or patent_eyecite already found.

For informal patent references that the script cannot see (e.g., "the patent-in-suit", "Smith's invention" without an earlier full-form introduction), note them separately — these are recall-backstop finds, not the primary extraction. The script is authoritative for recognizable forms (long form, `'NNN` short form, inventor-name short form, pincites); the gap pass fills in edge cases only.

**Pass 3 — proposition extraction.** For every citation (eyecite-extracted, patent_eyecite-extracted, *and* gap-pass), capture the assertive clause it supports. eyecite and patent_eyecite return citation strings and span offsets, not propositional context — that is on you. Follow the **Proposition Extraction** rules in `citation-toolkit` (specific-assertion vs paragraph scope, mid-sentence and footnote handling, string-cite sharing, short-form propositions, `ambiguous_proposition` flag). Use the spans from Pass 1 and Pass 1b to locate each citation in the source text precisely.

Apply the **Parenthetical Handling** rules from `citation-toolkit` when deciding whether a parenthetical like `(quoting X)` or `(citing Y)` creates an independent citation entry.

Maintain a **citation stack** only for gap-category cites and for any eyecite/patent_eyecite short forms flagged `unresolved_short_form` — both scripts already maintain the stack internally for everything else.

---

## Stage 3 — Citation Resolution

For **eyecite-extracted citations** (Pass 1 of Stage 2), structured-component parsing is already done — the JSON entries land in toolkit-schema shape. The only work here is the gap-category cites from Pass 2 and any field cleanup eyecite couldn't do.

- **Gap-category cites:** parse into the **Structured Component Schemas** in `citation-toolkit` (Cases, Statutes, Federal Regulations, Federal Rules, Secondary Sources, Constitutional Provisions, Legislative Materials) by hand. This is Haiku-tier mechanical work.
- **Statute subsection cleanup:** eyecite's `subsection` field is unreliable for forms like `47 U.S.C. § 230(c)(2)`. After Pass 1, re-read the source text for any statute entry where `subsection` is null and a subsection appears in the brief. Either fill it in or flag `ambiguous_section_reference`.
- **Unresolved short forms:** eyecite already flagged these. Try one more pass against the running stack; if still unresolved, leave the `unresolved_short_form` flag in place for user review.

Attach any remaining flags from the **Flag Vocabulary** in `citation-toolkit` (`informal_reference`, `ambiguous_proposition`, `uncertain_category`, `citing_parenthetical`; `subsequent_negative_history` comes later in Stage 6).

---

## Stage 4 — Source Lookup

For each resolved citation, attempt to locate the full source text using the priority-ordered lookup list for its type.

**Escalation chain:** Try all sources in order → if all fail, ask the user (provide the citation and the sources already tried; the user may know a direct URL or have access to a subscription service) → if the user cannot help, mark as `unverifiable`.

### Lookup Lists by Citation Type

**Cases (US):** Use the **CourtListener API** section of `citation-toolkit`. Stage 1 there (citation resolution) is the **components-only `call_endpoint("citation-lookup", ...)`** call — privilege-safe, sends only the citation's `volume/reporter/page`, not the brief. Loop over the unique citations from your Pass-1 eyecite output and call once per cite. Each successful lookup returns a `Cluster ID`; resolve cluster → opinion ID via `call_endpoint("clusters", {"id": <cluster_id>})`, walk `sub_opinions`, prefer `020lead`, then fetch text with `get_endpoint_item("opinions", <opinion_id>, fields=[...])`. **Do not pass the cluster ID directly to `get_endpoint_item("opinions", ...)`** — it will silently return the wrong opinion. **Do not call `analyze_citations`** — it uploads document text. See `citation-toolkit`'s "Step 1/2 (MCP)" section for the full pattern and post-fetch sanity check. If the MCP is unavailable entirely, the equivalent curl-based REST calls (same components-only shape) are documented in the same section. The full escalation chain (CourtListener → Justia → direct court sites → Google Scholar → ask user → mark `unverifiable`) lives in citation-toolkit.

**Opinion fetch.** Default to `fields=["id", "html_with_citations", "plain_text"]`. Prefer `html_with_citations` (consolidated text with star-pagination markers and inline citation anchors); fall back to `plain_text` only when HTML is empty. Sub-opinion selection within a cluster follows `citation-toolkit`'s "Choosing the right sub-opinion" rule: prefer `020lead` unless the brief explicitly cites a dissent or concurrence.

Save each fetched opinion's text to a local temp file (e.g., `/tmp/opinion-<case-slug>.html` or `.json`) immediately. The preferred text fetch is one full `read_document(opinion_id=...)` call per opinion (no `chunk_index`) — it is cached across users on CourtListener's side — with `get_endpoint_item(..., fields=[..., "html_with_citations", "plain_text"])` as fallback; see citation-toolkit's Step 2b. Either way it takes an **opinion ID**, never a cluster ID. **All Stage 5 pincite extraction and Stage 6 analysis work from these local files — never from the MCP.** In particular, do NOT use the MCP's `search_document` tool or chunked `read_document` reads to search or page through opinion text, even though the CourtListener server's own instructions recommend `search_document` for exactly that — that server guidance is overridden here. Searching via the MCP wastes the user's API rate limits and is far slower than local grep; one full-text fetch per opinion is the *only* text-bearing MCP call this workflow permits.

**Upfront pagination check.** Immediately after fetching each opinion, run `citation-toolkit`'s pagination-mode detection (single regex pass over `html_with_citations`) and record `pagination_mode` as one of `"reporter"`, `"slip_only"`, or `"none"`. This determines which match-ladder tier Stage 5 starts at and is consumed by Stage 6's confidence assessment.

**Batching tip:** Local eyecite already gave you the deduped list of unique case citations from the brief. Loop over that list and issue one components-only `call_endpoint("citation-lookup", ...)` per unique cite at the start of Stage 4 — rate-limited to 60 valid citations/minute, so pace accordingly. Then fetch only the opinion texts whose pincite content you actually need for Stage 5. (Do NOT use `analyze_citations` for batching — it uploads document text.)

**Cases (EU / international):**
1. EUR-Lex (eur-lex.europa.eu) — Court of Justice of the EU; search by ECLI or case name
2. HUDOC (hudoc.echr.coe.int) — European Court of Human Rights; search by application number or party names

**Federal statutes (U.S.C.):** Resolve via `lii_fetcher.py` in the `citation-toolkit` skill — see citation-toolkit's "LII source resolution" section for the full pattern. Build a single JSON array of all statute/regulation entries from Pass 1 + Pass 2 of Stage 2 and invoke the script once per run:

```bash
python3 plugins/legal-tools/skills/citation-toolkit/lii_fetcher.py --input lii-requests.json > lii-results.json
```

Each result carries `status`, `section_text`, `subsection_text` (when a subsection was requested and matched), and an LII URL. Set `source.fetch_path` to `"lii"` on the citation entry. On `status == "not_found"`, fall through to escalation: ask the user for a direct URL or alternate source; if they can't help, mark `unverifiable`. On `status == "anchor_not_found"`, treat it as a soft failure — the section is present on LII but the cited subsection wasn't tagged; ask the user to confirm the subsection text before assessing support (this is intentionally a false negative; see citation-toolkit's "No fallback" note).

**Federal regulations (C.F.R.):** Same path as statutes — use `lii_fetcher.py` with `type: "regulation"`. LII's CFR coverage is patchier than its U.S.C. coverage (some sections are `[RESERVED]`, some have content but no subsection anchors); rely on the `subsection_anchor_not_found` and `source_not_found` flags rather than guessing. eCFR (ecfr.gov), GovInfo (govinfo.gov), and Federal Register (federalregister.gov) remain available as user-supplied fallbacks when LII comes back empty.

**Federal rules:**
1. Cornell LII (law.cornell.edu) — covers FRCP, FRAP, FRE, and other federal rules. Not yet wired into `lii_fetcher.py`; navigate to title and section directly until the rules type is folded in.
2. Direct court websites — Supreme Court Rules at supremecourt.gov

**Patents (U.S. Patent Nos. and application publications):** Script-extracted patents (from Stage 2, Pass 1b) arrive pre-parsed and short-form-resolved via `patent_eyecite.py`. Each entry carries a `ref` (a `PatentRef` with kind, canonical_number, fetchable status) and structured pincites (`column_line`, `paragraph`, or `claims`). Handle flags first, then fetch PDFs:

*Flag handling — must run before fetch:*
- **`unresolved_short_form`** — The script could not resolve a short form (`'NNN` or inventor-name) to a full citation. The entry includes a `candidates` list of indices into the same JSON array. Prompt the user once (batched) to select which full patent the short form refers to, then update `resolved_to`.
- **`needs_metadata`** — An inventor-name short form was never introduced in preceding text. Offer to re-run the extraction with `--resolve-metadata` (network: patent numbers only, sent to Google Patents). If the user agrees, rebuild the extraction and re-check flags.
- **`ambiguous_pincite`** — A compact `N:M` pincite carries a `§` signal (possible statute section, not column:line). Confirm with the user that the pincite is intended to be column:line before routing to verify.

*Fetch via `patent_fetch.py` (gap-pass patents and any flagged script-extracted patents awaiting user action):* Build one JSON array of every patent that needs fetching and pass to the fetcher in one batch:

```bash
python3 plugins/legal-tools/skills/citation-toolkit/patent_fetch.py --input patent-fetch.json > patent-fetch-out.json
```

Each result carries `status` (`ok` | `not_located` | `image_only` | `rejected`), `pdf_path`, `source_url`, `text_words`. Collect the per-item outcomes, then ask the user **once** for local-copy paths covering all `not_located` and `image_only` failures in a single pass. Set `source.fetch_path` to `"patent"` on the citation entry. Failures are **non-fatal** — the batch continues for the rest.

*Status handling:*
- `ok` — text-layered PDF saved; route it (below).
- `not_located` — Google page 404 / no `citation_pdf_url` / fetch failed. Flag `US X,XXX,XXX not located`; ask the user for a local copy; if none, mark `unverifiable`.
- `image_only` — fetched a valid PDF but it has no text layer. Flag `US X,XXX,XXX has no text layer — extraction unavailable`; ask for a local copy; the tool never OCRs on its own.
- `rejected` — a non-fetchable kind (provisional/international unsupported). Skip and surface the `reason`.

*Routing the `ok` results:*
- `kind="grant"` → the patent **column:line extract/query pipeline** — `patent_extract.py` then `patent_query.py` (see `citation-toolkit`'s **Patent column:line extraction**). Patents are cited to `column:line`.
- `kind="apppub"` → **paragraph-numbered handling**, processed outside the column:line pipeline (application publications are cited to paragraph `[0042]`, not column:line). Flag the apppub for paragraph-based pincite handling.
- `kind="ep"`, `kind="wo"`, `kind="pct_app"` (international) — arrive `fetchable: false` from the script. Record and skip; non-US lookup is not yet supported.

*Privilege note.* Fetching a public patent PDF sends only the **public patent number** outbound (to Google) — the opposite direction from the document-text confidentiality rule that governs extraction. No privileged document text leaves the machine.

**Constitutional provisions:**
Text is resolved directly from the provision citation — no external lookup required for text. The text of U.S. constitutional provisions is settled; use the standard text.

**Law review articles:**
1. SSRN (ssrn.com) — search by title and author; many articles are freely posted
2. Direct law review website — derive from journal name (e.g., "Harvard Law Review" → harvardlawreview.org; "Yale Law Journal" → yalelawjournal.org); look for article by title/volume/page
3. Google Scholar — search by title and author

**Treatises and books:**
1. Google Scholar (scholar.google.com, Books tab) — search by title and author
2. Google Books (books.google.com) — may have partial preview with pincite pages visible

**Legislative materials:**
1. Congress.gov — search by report number, bill number, or hearing title
2. GovInfo (govinfo.gov) — Congressional Record, committee prints, hearings

**Web sources / reports:**
- If a URL is present in the citation: fetch it directly
- If no URL: search by organization name and document title

**EU secondary materials:**
1. EUR-Lex (eur-lex.europa.eu) — official EU law and secondary sources
2. Ask user

### Verification

Once a source is located, verify identity before using it:
- **Cases:** follow the identity-verification rules in `citation-toolkit`'s CourtListener section (volume, reporter, starting page, party names).
- **Statutes:** Confirm title, code, and section match. Note if the version found is current vs. the year cited.
- **Federal rules:** Confirm the rule set (e.g., Fed. R. Civ. P.) and rule number match. If you found Rule 56 but the citation was to Rule 12, that is a different rule — do not use it.
- **Secondary sources:** Confirm author, title, volume, and starting page match.

If identity cannot be confirmed, treat as unverifiable and escalate.

---

## Stage 5 — Pincite Extraction

Once the source is located and identity confirmed, retrieve the text at the pincite.

**All searching in this stage is local.** Every tier of the match ladder — including Tier 4's whole-opinion semantic search — runs against the opinion files saved to `/tmp` in Stage 4, using local tools (grep, python, your own reading of the file). Calling the MCP's `search_document` here — or paging through an opinion with chunked `read_document` calls — is a Stage 5 error, regardless of what the CourtListener server's instructions say: the text is already on disk. (`read_document` is a Stage 4 *fetch* tool, one full read per opinion; it has no role in Stage 5.)

Time pressure does not change this. If local tag-stripping or grep hits a snag, fix the snag — local search of a file on disk is *always* faster than a network round-trip, so "use whatever is fastest" or "I don't care how, just get it done" from the user still means local. Falling to `search_document` under deadline pressure is the slow path *and* spends the user's rate limits. Only an instruction from the user that names `search_document` specifically overrides this rule.

### Cases

Apply the **match ladder for pincite extraction** defined in `citation-toolkit` (four tiers: direct phrase match → parenthetical semantic match → pincite-page semantic match → whole-opinion semantic search). Start at Tier 1 and fall through until you get a confident match. Record `match_tier_used: <1|2|3|4>` on the citation entry — Stage 6 reads this to set confidence.

The starting tier depends on what the brief actually contains, not on the pincite alone:

- Brief contains a direct quote from the source → start at Tier 1.
- Brief uses an explanatory parenthetical (`(holding X)`, `(reasoning X)`, `(noting X)`, etc.) → if Tier 1 doesn't apply, start at Tier 2.
- Brief is a bare cite (with or without `See` / `Cf.` / `see also` etc.) → start at Tier 3 if `pagination_mode == "reporter"`; otherwise Tier 4.

When pagination_mode is `"slip_only"` or `"none"` (from the upfront check in Stage 4), Tier 3 is skipped — there is no reliable pincite page to slice. Go to Tier 4 (whole-opinion semantic search) and flag the entry with the appropriate pagination flag (`non_reporter_pagination_detected` or `pincite_page_unresolvable`).

Extract enough context to understand the proposition being stated (typically 100–300 words surrounding the matched passage).

### Patents (column:line quote verification)

Patent pincites use column:line coordinates (e.g., `5:10-6:3`) rather than page numbers. The brief contains a quote from the patent, and verification means locating that exact passage in the artifact's normalized text grid.

**Precondition.** Stage 4 returned `status: ok`, `kind: grant`, and the artifact has been built via `patent_extract.py build`. Script-extracted patent entries (Pass 1b) carry a structured `pincite` with `kind: "column_line"` and numeric `start_column`, `start_line`, `end_column`, `end_line` fields, mapping directly to the cite string format `start_column:start_line-end_column:end_line` consumed by `patent_verify.py`.

**The ladder** (LLM-executed; deterministic emit/resolve via `patent_verify.py` batch entries):

1. **Emit candidates.** Call `patent_verify.py` with a `mode:"emit"` entry to normalize the citation and gather the search window:

```bash
python3 plugins/legal-tools/skills/citation-toolkit/patent_verify.py --input -
```

Input JSON array entry:
```json
{
  "id": "cite-0001",
  "mode": "emit",
  "artifact_path": "/path/to/US9154231.json",
  "cite": "5:10-6:3"
}
```

Output object (within the results array):
```json
{
  "id": "cite-0001",
  "cite": "5:10-6:3",
  "cited_coord": [5, 10, 6, 3],
  "window_coord_range": [5, 9, 6, 4],
  "window_blob": "normalized text from window (newline-free)",
  "body_blob": "normalized text of full body (newline-free)",
  "ambiguity": false,
  "ambiguity_reason": null
}
```

The `window_blob` is a ±10% margin around the cited span (minimum ±1 line at each line endpoint, clamped to document bounds); columns are never widened. The `body_blob` is the full-text body (all text-kind lines normalized). The `ambiguity` flag is set when the grid has insufficient anchor lines to locate the cite (see grid drift below).

2. **Tier 1 — window match.** The LLM matches the brief's quote against `window_blob`. Tolerate whitespace/case/punctuation drift and obvious OCR quirks; do **not** accept a paraphrase or a dropped substantive word (a near-miss falls through — no soft-pass). On a hit, hand the matched **verbatim slice** (as it appears in `window_blob`) to a `mode:"resolve"` entry:

```json
{
  "id": "cite-0001",
  "mode": "resolve",
  "artifact_path": "/path/to/US9154231.json",
  "substring": "verbatim slice as matched in window_blob",
  "within": "5:9-6:4",
  "retried": false
}
```

The resolve() call automatically searches the window first; if no match is found there, it searches the full body in a single call. Output on a unique window hit:
```json
{
  "id": "cite-0001",
  "found_at": "5:12",
  "match_scope": "window"
}
```

Record `match_tier_used: 1` on the `pincite` entry. If the returned `match_scope` is `"window"`, the quote was located in the ±10% search window around the cited coordinates (Tier 1).

3. **Tier 2 — body match.** When resolve() searches the body as a fallback (window contained zero hits), it returns:
```json
{
  "id": "cite-0001",
  "found_at": "7:23",
  "match_scope": "body"
}
```

This indicates a unique match in the body outside the window — the quote exists but the cite is materially off (quote is elsewhere in the patent). Record `match_tier_used: 2`.

4. **Resolver ambiguity.** If resolve returns `ambiguous_match` with a `retry` instruction (multiple matches found and not yet retried), re-call with a longer/more distinctive slice and `retried: true`. If still ambiguous (`ambiguous_match: true` with `retried: true`), all candidate coordinates are returned in `found_at` (a list of coordinate strings). Disambiguate using the brief's surrounding context (other pincites, patent abstract, claim text) to select the intended location. Note: ambiguity is a separate orthogonal axis from Tier 1/2 (window vs body) — a retry is for handling duplicate matches in the chosen scope, not for escalating to body.

5. **Grid drift.** If emit returned `ambiguity: true`, the citation grid has spurious/unknown lines near the cited region. Annotate the entry: "grid/line-count drift near cited region — expanded window included." The expanded window widened the search automatically; if a match was found, it is still valid (though the actual location may differ from the cite).

6. **No hit anywhere.** When resolve returns `found_at: null`, the quote was not located in either the window or the body — surface to the user: possible misquote, wrong column:line, or wrong patent. Record `quote_match: false`.

**Recording on the `pincite` entry** (reuse the existing schema; add patent extras):

```json
{
  "text": "passage extracted from the source (window or body)",
  "match_tier_used": 1,
  "brief_quote": "the brief's quoted language",
  "actual_text": "the resolved patent text (verbatim slice from window_blob or body_blob)",
  "quote_match": true,
  "match_phrase": "the substring of actual_text that constitutes the verbatim match",
  "cited_coord": [5, 10, 6, 3],
  "found_at": "5:12",
  "ambiguity": false
}
```

**Outcome mapping for Stage 6:**

- Quote located at the cited coordinate (compare the resolved coordinate from `found_at` semantically against the cited span in `cited_coord`; note that `found_at` is a string like `"5:12"` while `cited_coord` is a list like `[5,10,6,3]`) → **verified** (quote located where the brief says).
- Quote located but at a different coordinate → **verified but cite-defective** (quote found; the offset is the finding. Stage 6 notes "pincite coordinate error").
- `found_at: null` (resolved as `quote_match: false`) → **red flag** (no quote located). Stage 6 marks `support: Unable` with issue `wrong-pincite`.

Stage 6's existing `support` labelling consumes `quote_match` exactly as it does for cases — `true` signals a strong match, `false` signals a mismatch or no-hit, and `match_tier_used` informs the confidence tier.

**Batch error handling.** The patent_verify.py batch command processes each entry independently. If an entry encounters an error (missing artifact, malformed/unreadable artifact file, invalid cite), it returns `{id, status:"error", error:...}` with an error message. The batch continues processing remaining entries; only malformed top-level JSON input causes the entire process to exit with code 2. Per-entry errors do not abort the batch.

**Cross-reference.** This ladder is the patent counterpart to the case-law **match ladder for pincite extraction** (citation-toolkit/SKILL.md), adapted for column:line coordinates. Unlike case-law (where pagination modes vary), patents have an exact coordinate system once the artifact is built — the challenge is that the human-entered cite often contains offsets (grid drift, line-count shifts).

### Other source types

- **Statutes and regulations (U.S.C., C.F.R.):** The pincite is already extracted in Stage 4 by `lii_fetcher.py`. Use `subsection_text` when present; fall back to `section_text` when no subsection was cited or when `anchor_matched` is false. **There is no match ladder for statutes and regulations** — the subsection anchor is the locator, or it isn't. Skip `match_tier_used` on these entries (emit `null` in the JSON). When `status == "anchor_not_found"`, prefer asking the user to point at the cited subsection over silently scanning the full-section text for a paraphrase.
- **Federal rules:** Retrieve the text of the cited rule and subsection in full (not yet automated; navigate to LII manually).
- **Secondary sources:** Navigate to the pincite page. Extract the relevant passage.
- **Constitutional provisions:** Use the standard text of the cited provision.
- **Legislative materials:** Retrieve the relevant passage from the Congressional Record, report, or hearing transcript.

### Multiple pincites and failure handling

**Multiple pincites** (e.g., `576 U.S. 155, 163, 170`): retrieve all pincite locations and treat them as a combined passage for analysis.

**If pincite text cannot be retrieved** (Tier 4 returns no confident match, or source is located but the specific page is behind a paywall): note what was found, mark pincite extraction as failed, and set support quality to `unable_to_assess`.

---

## Stage 6 — Support Analysis

Using the proposition (from Stage 2) and the pincite text (from Stage 5), produce:

### Précis

Write a 2–5 sentence neutral summary of what the source actually says at the pincite. Write it without reference to the brief's argument — describe what the source says on its own terms. A reader unfamiliar with the brief should be able to understand what the cited passage says from the précis alone.

### Support Quality Label

Assign one of these labels:

| Label | Meaning |
|-------|---------|
| **Strong** | Source directly and clearly states the proposition, or uses language that unambiguously supports it. A reasonable reader would immediately recognize the cite as apt. |
| **Adequate** | Source addresses the proposition but requires reasonable inference to connect. The cite is defensible; opposing counsel could challenge it but not easily dismiss it. |
| **Weak** | Source is on the general topic but does not clearly support the specific proposition as stated. A reader could fairly question whether this cite does the work being asked of it. |
| **Misleading** | Source, read in full context, cuts against the proposition or supports a materially different point. The cite may be technically accurate but creates a false impression. |
| **Unable to assess** | Source was not located, pincite text could not be retrieved, or the cited passage is inaccessible. |

Write a 2–4 sentence explanation of why you assigned this label, quoting relevant language from the pincite text where possible.

### Statutes and Regulations — Narrowed Rubric

For citations to statutes (U.S.C.) and federal regulations (C.F.R.), the Strong/Adequate/Weak/Misleading spectrum collapses. Statute language is fixed; either the brief characterizes it faithfully or it doesn't. Use only three labels for these entries:

| Outcome | Label |
|---|---|
| Brief's characterization matches the cited subsection text | **Strong** |
| Brief misstates the subsection text — wrong text, dropped qualifier, shifted meaning, or the cited subsection doesn't say what the brief claims | **Misleading** |
| Section not found on LII (`source_not_found`); or subsection anchor not found and the user couldn't confirm the cited text (`subsection_anchor_not_found` after escalation) | **Unable** |

Do not use Adequate or Weak for statutes — there is no inferential gap to interpolate over.

**Quotation marks vs. paraphrase** is the key distinction within Strong/Misleading:

- **If the brief presents the statute language in quotation marks**, it must match the source verbatim, subject to the standard Bluebook alterations: `[brackets]` for capitalization/pluralization/clarity tweaks that don't change meaning, `…` or `* * *` for elisions, `[emphasis added]` / `[emphasis in original]` notations. Apply the same `pincite.brief_quote` / `pincite.actual_text` / `pincite.quote_match` / `pincite.match_phrase` machinery the case-side uses (see the Field Conventions in Stage 8). A quote that diverges materially → **Misleading**, with `issues: ["misquote"]`. A quote that diverges only in unbracketed trivial alterations → **Misleading** with `issues: ["citation-form"]` (the brief should have bracketed the change).
- **If the brief paraphrases without quotation marks**, the rule is "operative text captured." A paraphrase that conveys the statute's actual command — including all material qualifiers like "knowingly," "willfully," "materially," "in writing" — is **Strong**. A paraphrase that drops a qualifier in a way that changes meaning, or that imports a requirement the statute doesn't contain, is **Misleading**.

The Stage 7 critic still runs for statutes and regulations — it's well suited to catching paraphrases that look faithful but elide a qualifier.

### Signal-Relativized Assessment

Apply the **signal-relativized support assessment** table from `citation-toolkit` when picking the label. A `Cf.` cite that supports the proposition by analogy is Strong, not Adequate — the inferential gap is the intended mode of citation. A `But see` cite whose source straightforwardly contradicts the proposition is Strong, not Misleading. Always record the citation's signal alongside the proposition, and reference the signal in the explanation when it materially affects the label.

### Confidence Adjustment from Match Tier

The match tier recorded by Stage 5 informs how confidently the label can be assigned:

- **Tier 1 (direct phrase match):** full confidence — quote and pincite agree.
- **Tier 2 (parenthetical semantic match):** high confidence — the briefing author committed to a specific characterization; assess against that characterization.
- **Tier 3 (pincite-page semantic match):** medium confidence — the matched passage may be one of several candidates on the cited page. If the second-best candidate is meaningfully different from the chosen one, note in the explanation.
- **Tier 4 (whole-opinion semantic search):** lower confidence — the pincite page was not reliably localized. State this explicitly in the explanation (e.g., "Pincite page could not be localized due to slip-opinion pagination; the matched passage was located by whole-opinion semantic search."). Consider downgrading from Strong to Adequate when the only reason for Strong would be a Tier-4 match.

### Indirect and Oblique Cites

When a case is cited for a proposition it does not directly address — for example, a case cited for a statutory interpretation it never discusses, or a grant-side case cited for a denial-side proposition — the support label should reflect the inferential gap:

- **Adequate** if the inference is short and the case provides genuine (if indirect) support
- **Weak** if the case is on the general topic but the specific proposition requires a step the case does not take
- In either case: note in the explanation whether better direct authority is likely to exist, and suggest it by name if known (e.g., from the model's knowledge of the area)

Common pattern to watch for: a brief cites a procedurally distinct case (different party posture, different statutory subsection, different procedural stage) for a general proposition that the cited case only supports obliquely. Flag the procedural distinction explicitly.

### Subsequent Negative History

After assigning the support label, check whether the cited case or statute has been overruled, abrogated, or significantly limited by subsequent authority. Use your own knowledge for this check — do not conduct a separate web search. If the cited authority has been negatively treated:

- Note it in the explanation (e.g., "Note: *Chevron* was overruled by *Loper Bright Enterprises v. Raimondo*, 603 U.S. 369 (2024).")
- Assess whether the negative treatment affects the specific proposition being cited for — sometimes an overruled case still correctly states the proposition at the pincite (e.g., Chevron step one survives Loper Bright)
- Flag the entry with `subsequent_negative_history` in the report

Do not flag cases that have merely been distinguished or criticized — only overrulings, abrogations, or holdings that directly limit the cited proposition.

---

## Stage 7 — Critic Subagent

After completing Stage 6 for a citation, dispatch a subagent to independently critique your analysis. Do this for each citation before moving to the next.

**Dispatch the subagent with this prompt (fill in the bracketed fields):**

```text
You are a legal cite-checking critic. Your job is to independently assess whether a citation in a legal brief adequately supports the proposition it is offered for.

**Proposition (from the brief):**
[proposition text]

**Citation:**
[full citation]

**Pincite text (retrieved from source):**
[pincite passage]

**Primary analysis:**
Précis: [précis text]
Support label: [label]
Explanation: [explanation]

**Your task:**
1. Read the proposition and pincite text independently.
2. Form your own view of how well the citation supports the proposition.
3. Assess whether the primary analysis's label and explanation are correct.
4. Note any nuance, context, or legal reasoning the primary analysis may have missed.

**Output:**
- Agreement: [Agrees / Disagrees / Partially agrees]
- Your reasoning: [2–4 sentences]
- Nuance or additional observations: [if any]
```

**If pincite text was unavailable (Stage 5 failed):** Do not dispatch the critic subagent. Set the Critic field in the report to `N/A — pincite unavailable` and continue to the next citation.

**If the subagent errors or returns unusable output:** flag the entry as `⚠ CRITIC UNAVAILABLE — primary analysis only` and continue.

**If the critic disagrees:** flag the entry as `⚠ CRITIC DISAGREES` and include both analyses in full in the report.

**If the critic partially agrees:** also flag the entry as `⚠ CRITIC DISAGREES` and include both analyses — partial disagreement is still disagreement worth surfacing.

**If the critic names a specific case or source as better authority:** you must verify that suggestion before including it in the report. Run the named case through Stage 4's case-lookup path — the components-only `call_endpoint("citation-lookup", ...)` (or, as fallback, the equivalent curl POST) — and fetch the opinion. Confirm that the opinion actually addresses the proposition at issue. If it does, extract the relevant passage (using the same pincite-extraction approach as Stage 5) and include both the citation and the quoted passage in the report so the user can evaluate the suggestion concretely. If the case cannot be found, or if reading the opinion shows it does not address the proposition, omit the suggestion from the report entirely and note: `⚠ Critic suggested [citation] as better authority — could not be verified; omitted.` Do not include any unverified case citation suggested by the critic.

---

## Stage 8 — Report Generation

After all citations have been processed through Stages 4–7, produce **three sibling output files**:

1. **Markdown report** — human-readable narrative report at `<original-filename>-cite-check.md`.
2. **JSON data file** — structured data at `<original-filename>-cite-check.json`. The JSON is the source of truth and is consumed by downstream tools; the Markdown and HTML are rendered from it.
3. **Self-contained interactive HTML report** — at `<original-filename>-cite-check.html`. Produced by taking the explorer template at `./explorer-template.html` (in this skill's directory) and inlining the JSON from step 2 into its `<script type="application/json" id="cite-check-data">` block. The result is a single-file, dependency-free HTML report the user opens in a browser to explore the cite-check interactively (severity filters, sort/grouping, brief-vs-pincite diffs, page-number minimap, Print/PDF).

All three files must be written for every run. If the user specified an output path that has none of these extensions, write all three (`<path>.md`, `<path>.json`, `<path>.html`).

**HTML emission.** Run the `assemble_html.py` script in this skill's directory. It reads `explorer-template.html` (alongside the script), inlines the JSON file into the template's `<script type="application/json" id="cite-check-data">` block, and writes the result:

```bash
python3 plugins/legal-tools/skills/cite-checking/assemble_html.py \
  --json brief-cite-check.json \
  --out  brief-cite-check.html
```

Do not modify the explorer template itself when emitting a report — only swap the JSON block (which is exactly what the script does). If you need to change the explorer's structure or styles, edit `explorer-template.html` directly (it is the canonical source) rather than patching post-hoc.

### Report Structure

#### Header

```
# Cite-Check Report

**Document:** [filename]
**Date:** [date]
**Total citations found:** [N]

| Support Label    | Count |
|-----------------|-------|
| Strong          | N     |
| Adequate        | N     |
| Weak            | N     |
| Misleading      | N     |
| Unable to assess| N     |
| Unverifiable    | N     |
```

#### Summary Flags

List all citations labeled Misleading, Weak, or Unverifiable in a prioritized triage section. For each, one line: citation + label + one-sentence reason.

```
## ⚠ Issues Requiring Attention

1. **[Citation]** — Misleading — [one-sentence reason]
2. **[Citation]** — Weak — [one-sentence reason]
3. **[Citation]** — Unverifiable — [lookup attempts made]
```

#### Per-Citation Entries (in document order)

For each citation:

```markdown
---

**Citation:** [full citation]
**Proposition:** "[text from brief that this citation supports]"
**Source found:** [Yes — Google Scholar | No — Unverifiable]
**Pincite text:**
> [quoted passage]

**Précis:** [2–5 sentence neutral summary]

**Support:** [Label] — [explanation]

**Critic:** [Agrees/Disagrees/Partially agrees] — [reasoning and nuance]

> **Note on terminology:** "Unverifiable" is a **Source found** status (the source could not be located). "Unable to assess" is the corresponding **Support** label. When a source is unverifiable, set Support to `Unable to assess` — do not write "Unverifiable" in the Support field.
```

If critic disagrees: add `⚠ CRITIC DISAGREES` immediately after the **Citation** line.
If critic unavailable: add `⚠ CRITIC UNAVAILABLE — primary analysis only` immediately after the **Citation** line.

#### Appendix: Unverifiable Citations

```markdown
## Appendix: Unverifiable Citations

### [Full citation]
- Tried: [source 1], [source 2], [source 3]
- Asked user: [yes/no — what they said]
- Status: Unverifiable
```

### JSON Output Schema

The JSON file mirrors the analytical content of the Markdown but is keyed for programmatic access. It has two top-level blocks: `document` (structure of the source) and `citations` (array, one entry per citation).

```jsonc
{
  "schema_version": "1.0",
  "generated_at": "YYYY-MM-DDTHH:MM:SSZ",

  "document": {
    "filename": "string — basename of the source file",
    "title": "string — brief title (e.g., 'Appellant's Opening Brief')",
    "case_no": "string — docket number and court, if identifiable",
    "format": "docx | pdf | md | txt",
    "pages": [
      { "number": 1, "text": "full page text, with [FNx: ...] footnote markers inlined" }
    ],
    "sections": [
      { "heading": "INTRODUCTION", "page_start": 1, "page_end": 3 },
      { "heading": "ARGUMENT", "page_start": 4, "page_end": 18 }
    ],
    "footnotes": {
      "12": "full text of footnote 12"
    },
    "notes": "free text — extraction caveats (e.g., 'DOCX page boundaries are approximate')"
  },

  "citations": [
    {
      "id": "c1",                              // stable per-run identifier
      "doc_index": 1,                          // 1-based order of appearance in the document
      "citation": {
        "full_text": "Ford Motor Co. v. United States, 405 U.S. 562, 573 (1972).",
        "short_label": "Ford Motor",           // short form for grouping/UI
        "case_key": "Ford Motor",              // stable key for grouping repeated cites of the same opinion
        "type": "case | statute | regulation | rule | constitution | secondary | legislative | other",
        "authority_level": "scotus | circuit | district | state-high | state-app | agency | secondary | other",
        "components": { /* per citation-toolkit Structured Component Schemas */ },
        "signal": "none | see | see-also | cf | but-see | but-cf | accord | contra | compare | string-cite-member",
        "flags": ["unresolved_short_form", "informal_reference", "ambiguous_proposition", "..."]
      },
      "location": {
        "page": 12,
        "section": "ARGUMENT",
        "footnote_id": null,                   // string id if cite appears in a footnote
        "snippet": "≈40–80 words of surrounding context, with the cite included verbatim"
      },
      "proposition": {
        "text": "the brief's assertive clause the citation is offered to support",
        "ambiguous": false,                    // set true when extraction was uncertain
        "proposition_group": "remedy-discretion" // optional — shared key when multiple cites support the same proposition (e.g., string cites)
      },
      "source": {
        "found": true,
        "fetch_path": "courtlistener-mcp | courtlistener-rest | lii | google-scholar | justia | direct-court | patent | user-provided | none",
        "courtlistener": {
          "cluster_id": "108494",
          "opinion_id": "9424801",
          "pagination_mode": "reporter | slip_only | none"
        },
        "lii": {                               // present when fetch_path=lii (statute/regulation)
          "url": "https://www.law.cornell.edu/uscode/text/17/512",
          "anchor": "c_2",
          "anchor_matched": true,
          "status": "ok | anchor_not_found | not_found | network_error"
        },
        "external_url": "https://...",         // when fetched outside CourtListener
        "unverifiable_reason": null            // populated when found=false
      },
      "pincite": {
        "text": "the actual passage retrieved from the source at the pincite",
        "match_tier_used": 1,                  // 1–4 per Stage 5 ladder
        "brief_quote": "the language the brief presents in quotation marks (populated whenever the brief quotes the source, whether or not the quote matches)",
        "actual_text": "the source's actual language at the same locus — the counterpart to brief_quote",
        "quote_match": true,                   // true when brief_quote matches actual_text verbatim; false when it diverges
        "match_phrase": "the substring of actual_text that constitutes the verbatim match (populated only when quote_match is true; used by renderers to highlight the matching span)"
      },
      "precis": "2–5 sentence neutral summary of what the source says at the pincite",
      "support": {
        "label": "Strong | Adequate | Weak | Misleading | Unable",
        "note": "optional short qualifier shown alongside the label (e.g., 'with caveats', 'upgraded from Weak after cross-check')",
        "explanation": "2–4 sentence rationale, quoting pincite language where useful",
        "issues": ["misquote", "mischaracterization", "wrong-pincite",
                   "denominator-error", "posture-error", "holding-inversion",
                   "misspelling", "citation-form", "strategic-omission",
                   "framing-inversion", "doctrinal-fit", "weight-concern"]
      },
      "critic": {
        "status": "agrees | partial | disagrees | not-dispatched | unavailable",
        "reasoning": "critic's own 2–4 sentence assessment (omitted when not-dispatched)",
        "nuance": "additional observations (optional)"
      },
      "subsequent_negative_history": {         // omit when none
        "treatment": "overruled | abrogated | limited",
        "by_case": "Loper Bright Enterprises v. Raimondo, 603 U.S. 369 (2024)",
        "affects_proposition": true
      },
      "action": "optional — concrete suggested fix for the brief preparer"
    }
  ]
}
```

#### Field Conventions

- **`support.label`** uses canonical short forms: `Strong`, `Adequate`, `Weak`, `Misleading`, `Unable` (NOT `"Unable to assess"`). The Markdown report's longer phrasing is rendered from this token.
- **`support.issues`** is an open-vocabulary array; the values above are the recognized set. Add a new value only when none of the existing values fits, and document the addition in the run's `document.notes`.
- **`pincite.brief_quote` and `pincite.actual_text`** populate together whenever the brief presents quoted language attributed to the source — *regardless* of whether the quote matches or diverges. Set `pincite.quote_match` to `true` when the brief's quoted language appears verbatim (or near-verbatim) in the source; in that case also populate `pincite.match_phrase` with the substring of `actual_text` that constitutes the match (downstream renderers use it to highlight the matching span). Set `quote_match` to `false` and omit `match_phrase` when the quote diverges materially. Omit all four fields when the brief paraphrases without quotation marks. Renderers display three modes: **match** (both sides match, ✓✓, highlighted span), **divergent** (✕ brief vs ✓ source), and **neutral** (proposition vs pincite, no quote). The Markdown report's diff symbology should follow the same rule.

- **`actual_text` must be a narrow excerpt, not the full pincite.** Aim for one or two sentences containing `match_phrase` (in match mode) or the brief's quoted language (in divergent mode). The broader surrounding passage lives in `pincite.text`. Renderers show `actual_text` by default and surface `pincite.text` only on expansion, so users see the directly relevant language first and the surrounding context one click away. Emitting the full pincite into `actual_text` defeats this — it hides the matched language inside a wall of unrelated text. The two fields are *not* interchangeable: `actual_text` is the targeted excerpt; `pincite.text` is the broader passage extracted in Stage 5.

- **`actual_text` must be literal source text, not a description of it.** It is a verbatim (or near-verbatim, with bracketed alterations Bluebook-style) excerpt of what the source actually says — copy-pasteable into a brief. Strings like `"(verbatim except where bracketed)"`, `"see pincite"`, or any other meta-description that summarizes the relationship between the brief and source instead of quoting the source are NOT valid values. If the brief uses a string-of-quotes form and you cannot pick a single excerpt that contains all of them, prefer the excerpt that contains the most representative match_phrase and leave the broader assembly in `pincite.text`. The same rule applies to `brief_quote` — it must be a literal excerpt of what the brief says, not a description.
- **`citation.case_key`** identifies the underlying opinion, not the pincite. Multiple entries pinning to different pages of the same opinion (e.g., `@ 70`, `@ 105`, `@ 107`) share a single `case_key` so consumers can group them.
- **`proposition.proposition_group`** is a free-text slug shared across citations supporting the same assertion (string cites). Use the same slug across all members of the group; omit when a citation stands alone.
- **`location.snippet`** is for human display; do not over-truncate (do not cut the citation itself). For citations in footnotes, the snippet should be drawn from the footnote text and `location.footnote_id` set; `location.page` is the body page on which the footnote-reference appears.
- **Critic-disagreement marker.** The `⚠ CRITIC DISAGREES` / `⚠ CRITIC UNAVAILABLE` markers in the Markdown report are derived from `critic.status` (`disagrees`/`partial` → disagreement marker; `unavailable` → unavailable marker). Do not duplicate them as separate fields.
- **Statute and regulation entries.** `pincite.text` is populated from `lii_fetcher`'s `subsection_text` when the anchor matched, or from `section_text` when no subsection was cited. `pincite.match_tier_used` is `null` for statutes/regulations — there is no match ladder; the LII anchor is the locator. `source.courtlistener` is omitted; `source.lii` carries the fetch metadata. The brief_quote/actual_text/quote_match/match_phrase quartet behaves identically to the case side (see the Statutes and Regulations rubric in Stage 6 for the quotation-mark vs paraphrase rule).

#### Determinism

The MD report and the JSON file are generated from the same in-memory analysis. They must agree: every citation in the MD report appears in the JSON `citations` array (and vice versa), every label in the MD matches `support.label` for the corresponding entry, and the per-citation order in the MD report matches ascending `doc_index` in the JSON.
