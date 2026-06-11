---
name: citation-toolkit
description: Reference skill for legal citations — defines the citation-type taxonomy, short-form resolution rules, structured component schemas, flag vocabulary, and CourtListener API patterns used by other legal-tools skills (cite-checking, chain-cite, table-of-authorities). Read this before parsing citations, calling CourtListener, or emitting citation-related structured output in any other skill.
---

# Citation Toolkit

## Overview

This is a **reference skill**, not a workflow. It does not run end-to-end on its own. It defines the shared vocabulary and external-API patterns used by every other skill in `legal-tools` that touches legal citations:

- **Citation taxonomy** — the set of citation types recognized and how to spot them in text
- **Short-form resolution** — how `Id.`, `supra`, party-name, and reporter-only forms are resolved against a running citation stack
- **Proposition extraction** — rules for identifying the assertive text a citation supports
- **Parenthetical handling** — which parentheticals create independent citation entries and which do not
- **Structured component schemas** — the JSON shapes each citation type is parsed into
- **Flag vocabulary** — the shared set of flags for ambiguous, uncertain, or unresolvable situations
- **CourtListener API patterns** — auth, endpoints, and response handling for the primary US case-law data source

Consuming skills (e.g., `cite-checking`, `chain-cite`, `table-of-authorities`) include a "Prerequisites" section referencing this skill and use the vocabulary and patterns defined here without restating them.

Two companion reference files live alongside this one and are loaded **only when the run needs them**: **`LII.md`** (statute/regulation resolution via `lii_fetcher.py`) and **`PATENTS.md`** (the patent script suite: extraction, fetch, column:line, verification). Don't read them for runs with no statutes/regulations or no patents.

**CourtListener access: MCP for resolution, REST for opinion text.** When the `claude.ai CourtListener` MCP server is available, use its tools for the small-payload *resolution* steps (citation-lookup, cluster→opinion resolution, sub-opinion selection) — those responses are compact JSON you genuinely need to read and reason about, and the MCP handles auth. But fetch **opinion text** via the REST API with `curl -o` straight to disk, even when the MCP is available: opinion text is consumed only by local tools, and an MCP fetch forces the full text through the conversation (once inbound, once again re-emitted to write it to disk — slow, token-expensive, and lossy for long opinions). The governing principle: **opinion text never transits the conversation — it goes API→disk, and all reading of it is local.** The MCP text-fetch tools are the fallback for environments where shell network access is unavailable. Both paths are documented below.

---

## Extraction: eyecite is the primitive (local only)

Every consuming skill in `legal-tools` starts with the same step — pull every citation out of a document. That step is **not** a free-form LLM scan. It runs [eyecite](https://github.com/freelawproject/eyecite), the Free Law Project's citation parser trained on 55M+ real citations. eyecite output is **authoritative** for the citation types it recognizes; the consuming-skill's LLM gap pass exists only to fill known gaps (listed below), not to second-guess what eyecite already found.

### Confidentiality: extraction runs locally — never over MCP

Legal documents are routinely privileged or work-product protected (draft briefs, internal memos, anything not yet filed publicly). To keep the privilege posture bright-line, **extraction in these skills always runs on-machine** via the local `eyecite_extract.py` script. The CourtListener MCP's `extract_citations` and `analyze_citations` tools both take the **full document text** as input and send it to Free Law Project's servers — they are **not** to be used from any of these skills for any input, ever. The rule is bright-line so there is no judgment call about whether a given input is privileged.

For downstream verification, the MCP is fine — but only the tools that operate on **already-public citation strings or IDs** (`call_endpoint`, `search`, `get_endpoint_item`, `get_endpoint_schema`, `get_choices`, `get_more_results`). Those send citation components like `volume=576&reporter=U.S.&page=155`, not the document. See the "Citation lookup (privilege-safe)" subsection of the CourtListener API section below for the components-only lookup pattern that replaces `analyze_citations`.

### How to run eyecite locally

The script lives in this skill's directory: `eyecite_extract.py`. It reads from a file or stdin and emits a JSON array of toolkit-shaped citation entries on stdout.

```bash
python3 plugins/legal-tools/skills/citation-toolkit/eyecite_extract.py --input brief.txt
# or:
cat brief.txt | python3 plugins/legal-tools/skills/citation-toolkit/eyecite_extract.py
```

Requires `pip install eyecite` (or, on PEP-668 systems like recent Linux distros, a venv: `python3 -m venv .venv && .venv/bin/pip install eyecite && .venv/bin/python plugins/legal-tools/skills/citation-toolkit/eyecite_extract.py --input brief.txt`).

The script does not make any network calls. The document never leaves the machine.

### What eyecite recognizes

eyecite returns structured records for these citation types (each shape maps onto the Structured Component Schemas below):

| eyecite class | Toolkit `citation_type` | Notes |
|---|---|---|
| `FullCaseCitation` | `case` | `groups: {volume, reporter, page}`; `metadata: {plaintiff, defendant, court, year, pin_cite, parenthetical}`. |
| `ShortCaseCitation` | `short_case` (links to a `case`) | `metadata.antecedent_guess` is the party name eyecite linked it to. |
| `IdCitation` | `id` (links to the immediately-prior cite) | Carries `pin_cite` only — antecedent comes from `resolve_citations`. |
| `SupraCitation` | `supra` (links to a prior `case`) | `metadata.antecedent_guess` plus pin cite. |
| `FullLawCitation` | `statute` | `groups: {reporter (e.g. "U.S.C."), title/chapter, section, subdivision}`. **Soft spot:** subsections like `(c)(2)` are not always populated — verify against the source text and flag `ambiguous_section_reference` if missing. |
| `FullJournalCitation` | `secondary` (law review) | `metadata: {author, title}`, `groups: {volume, reporter (journal), page}`. |
| `UnknownCitation` | `unknown` | Matched the citation tokenizer but did not parse into any of the above. Surface for human review. |

### Gap list — what eyecite does NOT catch

After running eyecite, the consuming skill must walk the document for these. Don't try to make eyecite do them — patch around it.

- **Administrative decisions:** PTAB (`IPR2020-00019`), FTC, SEC, FCC orders and opinions.
- **EU / international cases:** ECLI identifiers, EUR-Lex case numbers, ECHR application numbers.
- **Popular-name statutes:** "the Lanham Act", "ERISA", "Section 230" — bare references not in `[title] U.S.C. § [section]` form.
- **Informal constitutional references:** "First Amendment", "Article III", "due process" — eyecite catches formal `U.S. Const. amend. I` but not narrative references.
- **State constitutional provisions:** `[State] Const. art. [X], § [Y]` — sometimes caught, often not.
- **Treatises and books** in non-standard forms; **legislative materials** other than `Cong. Rec.` / committee reports.
- **Statute subsection extensions** (`(c)(2)`, `§§ 315(a), (d), and (e)`) — eyecite parses the section but may drop the subsection breakdown.

### How to combine eyecite + the gap pass

1. **Extract:** Run eyecite once over the substantive text via the local `eyecite_extract.py` script. This produces a sorted, document-order list with short forms resolved.
2. **Map onto the toolkit schemas.** The script already emits toolkit-shaped JSON; no manual mapping needed.
3. **Walk for gaps.** Read the substantive text once, looking *only* for the gap categories. Don't re-extract what eyecite already found. When you find a gap-category citation, parse it manually into the appropriate schema.
4. **Apply flags.** Unresolved short forms from eyecite → `unresolved_short_form`. Missing subsection on a statute → `ambiguous_section_reference`. Informal references resolved by the LLM gap pass → `informal_reference`.
5. **Page/proposition tracking is still the skill's job.** eyecite gives you span offsets (character positions), not page numbers — the consuming skill maintains the offset→page map and the proposition for each citation.

This split moves the deterministic work (parsing, short-form linking) out of the LLM and into eyecite, while reserving LLM judgment for the parts that genuinely need it (proposition extraction, gap-category recognition, support analysis).

---

## Citation Taxonomy

Identify citations of these types. The consuming skill decides what to do with each (e.g., look it up, extract a proposition, include in a TOA).

### Cases

- Full: `Party v. Party, [vol] [reporter] [page] ([court] [year])`
  - Example: `Reed v. Town of Gilbert, 576 U.S. 155, 163 (2015)`
- Westlaw/LEXIS: `[year] WL [number]`
- PTAB / agency decisions: `Party v. Party, IPR[year]-[number] (PTAB [date])`; also FTC, SEC, FCC orders and opinions. Consuming skills that categorize citations (e.g., `table-of-authorities`) may treat these as a distinct category from court opinions.
- EU Court of Justice: ECLI identifiers and EUR-Lex case numbers
- ECHR: `Party v. Country, App. No. XXXXX/XX ([year])`

### Constitutional Provisions

- Formal: `U.S. Const. art. [X], § [Y]` / `U.S. Const. amend. [X]`
- Informal: "First Amendment", "Article III" → resolve to formal citation
- Vague references ("due process", "equal protection") without specification → do NOT include unless the brief specifies the exact clause

### Statutes

- Federal: `[title] U.S.C. § [section]` (with or without year)
- State: various formats by jurisdiction
- Popular-name: "the Lanham Act", "ERISA" → resolve to formal citation; flag with `informal_reference` if uncertain
- Cite the specific subsection as written — do NOT generalize

### Rules and Regulations

- Federal Rules: `Fed. R. Civ. P. [rule]`, `Fed. R. App. P. [rule]`, `Fed. R. Evid. [rule]`
- Grouped rules ("Rules 413–415") → expand to one entry per rule
- C.F.R.: `[title] C.F.R. § [section]`
- Federal Register: `[vol] Fed. Reg. [page] ([year])`

### Legislative Materials

- Congressional Record: `[vol] Cong. Rec. [page] ([year])`
- Committee Reports: `H.R. Rep. No. [congress]-[number]` / `S. Rep. No.`
- Hearing transcripts, markup transcripts, amendments

### Secondary Sources

- Law review: `[Author], [Title], [vol] [journal] [page] ([year])`
- Treatises: `[vol] [Author], [Title] § [section] ([ed.] [year])`
- Restatements: `Restatement ([ed.]) of [Subject] § [section] ([year])`
- Blog posts, reports, web sources: author/org, title, date, URL if present

### Patents

- Utility grant: `U.S. Patent No. 8,453,642` (7–10 digits; kind codes `B1`/`B2` are noise, stripped)
- Design / plant / reissue grant: `D645,062` / `PP12,345` / `RE38,161` (letter prefix kept — it identifies the document)
- Application publication: `U.S. Patent Application Pub. No. 2009/0151718 A1` (11-digit `YYYYNNNNNNN`; cited to paragraph `[0042]`, not column:line)
- Provisional: `60/123,456` → not publicly retrievable; flag, do not fetch
- Parsed by `patent_ref.py` into a `PatentRef` (see Structured Component Schemas). Patents are extracted by `patent_eyecite.py` (documented in `PATENTS.md` alongside this file); the LLM gap pass remains only as a recall backstop for informal references the regex finder cannot see (e.g., "the patent-in-suit").

**Recognizing patent cites in text** (all extracted by `patent_eyecite.py`):
- Long form, first mention: `U.S. Patent No. 8,453,642`, often with a parenthetical nickname `("the '642 patent")`.
- **`'NNN` short form** (the dominant in-text form): `the '642 patent`, `the '298 patent` — an apostrophe + the last 3 digits of a grant number. This is the patent analog of `Id.`/`supra` and resolves against the citation stack to the most recent full patent number ending in those digits (see Short Forms).
- **Inventor-name short form** ("the Kwok patent") — a capitalized surname + "patent", resolved to the most recent patent introduced to that inventor.
- **Pincite is `column:line` or `¶ paragraph`:** grants are cited `col. 5, ll. 12–18`, `5:12–18`, or `5:12`; capture the column:line span as the pincite. Application publications are cited to **paragraph** `[0042]` or `¶ 42`; capture the paragraph number. Claims: `claims 1–3` are parsed and attached to their citing patent.
- **Nos. lists** (plural patents in a single entry): `U.S. Patent Nos. 8,453,642, 8,234,821, and 8,012,944` — each number is a separate citation entry sharing the text span.
- **International forms** (parsed via `patent_ref.py` kinds `ep`/`wo`/`pct_app`, `fetchable: false`): European patents (EP), WIPO/PCT publications (WO), PCT applications (PCT/).

---

## Short Forms

Short forms require a **citation stack** — the running list of recently-cited authorities maintained in document order so short forms can be resolved to their antecedents.

- `Id.` → resolves to the immediately preceding citation (even across page boundaries; track meticulously)
- Party-name short forms: `[Party], [vol] [reporter] at [page]`
- Reporter-only: `[vol] [reporter] at [page]`
- `supra` / `supra note [X]`
- Informal references ("the Paxton court", "Daubert standard") → resolve to case; flag `informal_reference`
- **Patent `'NNN` short form** ("the '642 patent", "the '298 patent") → resolved deterministically by `patent_eyecite.py`'s resolution pass (`resolve_patent_citations`). If two stacked patents share the same last-3 digits, or none match, flag `unresolved_short_form` with a `candidates` list of entry indices in the same JSON array so the consuming skill can prompt the user.
- **Patent inventor-name short form** ("the Kwok patent") → resolved to the most recent patent introduced to that inventor. Inventor-name short forms never introduced in the text additionally carry `needs_metadata` (re-run with `--resolve-metadata` to attempt network resolution via Google Patents, patent numbers only).

When a short form cannot be confidently resolved, flag it as `unresolved_short_form` for user review rather than guessing.

---

## Proposition Extraction

The **proposition** is the assertive clause or sentence(s) that a citation is offered to support.

- Usually the specific assertion in the sentence ending with the citation, not the full paragraph
- For mid-sentence citations, use the clause up to the citation
- For footnote citations, use the footnote's assertive text
- For string cites, the proposition is the same for all citations in the string — capture it once and associate with all
- For `Id.` and short forms, extract the proposition from the location of the short form, NOT from the original full-citation location
- If the scope is genuinely ambiguous, capture the most proximate assertive clause and flag `ambiguous_proposition`

---

## Parenthetical Handling

- `(quoting [Authority])` → the authority gets a citation entry
- `(citing [Authority])`, `(discussing X)`, `(applying X)`, `(overruling X)` → these describe what another case did; the citing brief is NOT independently citing that authority; do NOT create a citation entry (flag as judgment call if encountered)
- `(holding [description])` → parenthetical on primary citation; not a separate authority

---

## Structured Component Schemas

When a consuming skill emits structured data about a citation, use these shapes.

**Cases:**
```
citation_type: case
full_citation: [full string as it appears]
source_name: [Party v. Party]
reporter: [e.g., U.S., F.3d, F. Supp. 2d]
volume: [number]
start_page: [number]
pincite: [list of page numbers, e.g., [163, 170]]
court: [e.g., SCOTUS, 9th Cir., S.D.N.Y.]
year: [number]
subsequent_history: [e.g., "cert. denied, 140 S. Ct. 2761 (2020)"] or null
```

**Statutes:**
```
citation_type: statute
full_citation: [full string]
title: [number, e.g., 47]
code: [e.g., U.S.C.]
section: [e.g., 230]
subsection: [e.g., (c)(2)] or null
year: [number] or null
```

**Federal Regulations:**
```
citation_type: regulation
full_citation: [full string]
title: [number]
code: [C.F.R. or Fed. Reg.]
section: [number]
pincite: [page or section number] or null
year: [number] or null
```

**Federal Rules:**
```
citation_type: rule
full_citation: [full string, e.g., Fed. R. Civ. P. 56(a)]
rule_set: [e.g., Fed. R. Civ. P. | Fed. R. App. P. | Fed. R. Evid. | Fed. R. Bankr. P. | S. Ct. R.]
rule_number: [e.g., 56]
subsection: [e.g., (a)] or null
```

**Secondary Sources:**
```
citation_type: secondary
full_citation: [full string]
author: [last name(s)]
title: [article/book title]
journal_or_publisher: [name]
volume: [number] or null
start_page: [number] or null
pincite: [page] or null
year: [number] or null
url: [if present] or null
```

**Patents** (extracted and resolved by `patent_eyecite.py`):
```
citation_type: patent | patent_short | patent_claim
full_citation: [full string as it appears]
span: [start, end) in the original text
ref: PatentRef | null
  (null for patent_short entries; PatentRef includes kind, canonical_number,
   display, fetchable, reason)
pincite: {
  "kind": "column_line" | "paragraph" | "claims" | null,
  "start_column": int, "start_line": int,   # column_line
  "end_column": int, "end_line": int,       # column_line
  "paragraph": int,                         # paragraph
  "start_claim": int, "end_claim": int      # claims
} | null
nickname: [e.g., "the '642 patent"] | null
resolved_to: {"index": int, "full_citation": str} | null
flags: [unresolved_short_form, ambiguous_pincite, needs_metadata]
candidates: [list of indices] if unresolved_short_form
```

**Kind vocabulary:** `grant` (utility, design, plant, reissue), `apppub` (application publication), `provisional` (not publicly retrievable), `ep` (European), `wo` (WIPO/PCT), `pct_app` (PCT application), `unsupported` (unclassifiable). Fetchable: true for `grant` and `apppub` only.

**Constitutional Provisions:**
```
citation_type: constitutional
full_citation: [formal citation, e.g., U.S. Const. amend. I]
```

**Legislative Materials:**
```
citation_type: legislative
full_citation: [full string]
source_type: [congressional_record | committee_report | hearing | markup | amendment]
congress: [number] or null
number: [report/bill number] or null
year: [number] or null
```

---

## Flag Vocabulary

Consuming skills attach flags to citation entries when something is uncertain. Use these names verbatim so downstream tooling sees consistent vocabulary across skills.

| Flag | Meaning |
|------|---------|
| `unresolved_short_form` | Could not link a short form to a full citation in the running stack |
| `informal_reference` | Resolved from informal text (e.g., "First Amendment", "the Paxton court") |
| `ambiguous_proposition` | Proposition scope uncertain; most proximate assertive clause captured |
| `ambiguous_section_reference` | Bare statute section without subsection |
| `uncertain_category` | Not clear which citation type applies |
| `citing_parenthetical` | Judgment call on a `(citing X)` / `(applying X)` parenthetical |
| `subsequent_negative_history` | Cited authority has been overruled, abrogated, or significantly limited |
| `subsection_anchor_not_found` | Statute or regulation was located on LII but the cited subsection anchor is not tagged in the page (false-negative — the text may be present but unanchored, or the subsection genuinely doesn't exist) |
| `source_not_found` | Statute or regulation section was not located on LII (HTTP 404 or chrome-only empty body) |
| `unverifiable` | Source could not be located after escalation chain exhausted |

Consuming skills may define their own additional flags for workflow-specific situations (e.g., `chain-cite` needs flags for drift annotations across hops). Keep the ones above consistent.

---

## CourtListener API

Primary source for US case law. Two access paths are supported; **prefer the MCP** when it is available.

Do NOT attempt to scrape `courtlistener.com` pages — they are JavaScript-rendered and will return empty content. Use the MCP tools (or, as fallback, the REST API).

### MCP tool cheat-sheet (preferred path)

When the `claude.ai CourtListener` MCP server is loaded, use these tools instead of curl. Auth is handled by the MCP — consuming skills do **not** need to collect a token from the user when going through the MCP.

| Task | MCP tool | Notes |
|------|----------|-------|
| ~~Parse citations from text~~ | ~~`extract_citations`~~ | **DO NOT USE from these skills.** This tool takes the full document text as input and sends it to Free Law Project's servers — privilege/work-product risk. Run the local `eyecite_extract.py` script instead. See "Extraction: eyecite is the primitive (local only)" above. |
| ~~Verify a batch of citations~~ | ~~`analyze_citations`~~ | **DO NOT USE from these skills.** Same privilege issue — accepts and uploads document text. For verifying a parsed citation against CourtListener, use the components-only `call_endpoint("citation-lookup", ...)` pattern below, which sends only the citation's `volume/reporter/page` (already public). |
| ~~Resume verification~~ | ~~`resume_citation_analysis`~~ | **DO NOT USE.** Only relevant as a companion to `analyze_citations`, which is also banned. |
| Look up opinion *metadata* by ID | `mcp__claude_ai_CourtListener__get_endpoint_item` with `endpoint_id="opinions"` | For metadata (e.g., `fields=["id", "type"]` to confirm a sub-opinion). For opinion **text**, use the REST `curl -o` fetch in Step 2b instead — text via this tool is the no-shell-network fallback only, and then **always pass `fields=[...]`** (text fields are huge; allowlists below). |
| ~~Fetch opinion text into the conversation~~ | `read_document` | **Fallback only** (no shell network access). Full read per opinion (omit `chunk_index`), then save to disk. Never use chunked reads to hunt for a pincite. Primary text fetch is the REST `curl -o` in Step 2b — direct to disk, no context transit. |
| ~~Search opinion text~~ | ~~`search_document`~~ | **DO NOT USE from these skills, period** — even though the server's own instructions recommend it. All text searching runs locally against the saved opinion file. See "Fetch once, then work locally" in Step 2b. |
| Look up an opinion cluster (parallel cites, sub-opinions, case metadata) | `get_endpoint_item` with `endpoint_id="clusters"` | When the components-only `citation-lookup` call returns a `cluster_id` and you need its sub-opinions list, court, date, or canonical case name. |
| Free-text or fielded search | `mcp__claude_ai_CourtListener__search` | Use when the user has a case name but no cite, or to disambiguate between clusters. Pass `type="o"` for opinions, `"d"` for dockets, `"p"` for judges, `"oa"` for oral argument. Always pass `fields=[...]`. |
| Discover an endpoint's schema | `mcp__claude_ai_CourtListener__get_endpoint_schema` | When you need a field that's not on the search index — e.g., the full `opinions-cited` graph, party/attorney detail, financial disclosures. |
| Call any non-search endpoint | `mcp__claude_ai_CourtListener__call_endpoint` | For docket entries, recap-documents, opinions-cited, courts, parties, attorneys, etc. Pass `fields=[...]`. |
| Paginate prior results | `mcp__claude_ai_CourtListener__get_more_results` | Continue a `search` or `call_endpoint` query without re-issuing the filters. |
| Enumerate field choices | `mcp__claude_ai_CourtListener__get_choices` | When a schema says "use get_choices" (e.g., the 470 valid `court` values). |

#### Opinion text fields: which to use

The REST fetch saves the full opinion record to disk; these rules govern which field of the **saved local file** each task reads. (They double as the `fields=[...]` allowlist on the rare MCP-fallback fetch — opinion text fields are enormous, so any MCP call that touches them must restrict `fields`.)

**Default to `html_with_citations` as primary across all skills**, with `plain_text` as a backup. `html_with_citations` is CourtListener's consolidated field — it includes the star-pagination markers AND the inline citation anchors AND the consolidated text, in one payload. `plain_text` is sometimes empty (especially for older or Harvard-CAP-only ingests), and when it is populated it does not always carry the same pagination scheme as `html_with_citations`. Use `html_with_citations` first; fall back to `plain_text` only when the HTML field is empty.

- **For proposition/pincite text searching (`cite-checking` Stage 5):** `html_with_citations` after stripping tags; fall back to `plain_text` only if HTML is empty.
- **For star-pagination / pincite page extraction (`chain-cite` Stage 3):** `html_with_citations`; `xml_harvard` is an additional pagination source for ingestion-format edge cases.
- **For citation-graph traversal (`chain-cite` Stage 4):** `html_with_citations`. The anchors `<span class="citation" data-id="..."><a href="/opinion/{id}/...">` are what backward traversal walks.
- **For identity verification only (case name + date + reporter):** no text fetch needed — use the cluster: `get_endpoint_item("clusters", id, fields=["id", "case_name", "date_filed", "citations", "sub_opinions"])`.

#### Choosing the right sub-opinion within a cluster

A cluster's `sub_opinions` array may contain one or several opinion records. When there are several, use the `type` field to pick the right one:

| `type` | What it is | When to pick |
|---|---|---|
| `010combined` | Single combined opinion (majority + concurrences + dissents in one record) | When it's the only entry, or when reporter pagination is absent in the split-out records. Often a slip-format ingest. |
| `020lead` | The majority / lead opinion, split out from concurrences and dissents | **Prefer this when present** — typically the Harvard-CAP ingest with reporter pagination (`*N` markers). |
| `030concurrence`, `040dissent` | Separate concurring or dissenting opinions | Only pick when the brief specifically cites a dissent or concurrence. |

Rule of thumb: if the brief's citation does not flag a dissent or concurrence (no `(dissenting)`, `(concurring)`, `(per curiam)` notation), prefer `020lead` if present, otherwise `010combined`. When you pick a non-lead opinion deliberately, record that choice — Stage 6 support assessment depends on whether the cited passage is in the controlling opinion or a separate writing.

#### Upfront pagination-mode detection

Before doing any pincite extraction, run a one-shot check on the chosen opinion's `html_with_citations` and record a `pagination_mode` for downstream Stages 5/6 to consume. This is fast (single regex pass over the HTML) and prevents a class of late-stage failures where the matched passage lands on the wrong page scheme.

The detection algorithm:

1. From the local eyecite output (or the cluster's `citations` array after `citation-lookup`), note the **reporter** the brief used (e.g., `F.3d`, `U.S.`, `S. Ct.`) and the **starting page** of the cited case.
2. Scan `html_with_citations` for star-pagination markers using this combined pattern (covers known conventions): `\*(\d+)\b | label="(\d+)" | page-label="(\d+)" | \f(\d+)`. The last alternative — form-feed + number — catches slip-opinion pagination from court-direct ingests (e.g., SCOTUS slips, Ninth Circuit en banc PDFs).
3. Compare the marker number range to the cited starting page:
   - **Markers exist AND the cited pincite page falls inside the marker range** (start ≤ pincite ≤ end) → `pagination_mode: "reporter"`. Use page-based pincite extraction.
   - **Markers exist BUT the cited pincite page is far outside the marker range** (typical slip pagination starts at `*1` and runs into the low thousands; reporter pagination for a circuit case might be `*854`–`*870`) → `pagination_mode: "slip_only"`. The opinion text is paginated by a *different* scheme than the brief uses. Page-based extraction will fail; route to phrase/semantic matching. Flag `non_reporter_pagination_detected`.
   - **No markers at all** → `pagination_mode: "none"`. Route to phrase/semantic matching. Flag `pincite_page_unresolvable`.

When `pagination_mode != "reporter"`, surface the mismatch in Stage 6's confidence assessment — it explains the inherent uncertainty in pincite localization.

#### Match ladder for pincite extraction

Stage 5 (in `cite-checking`) and Stage 3 (in `chain-cite`) both need to localize the brief's proposition inside the cited opinion. Use this four-tier ladder, fast to slow, with the tier and outcome recorded for Stage 6:

| Tier | When applicable | How | Tier confidence |
|---|---|---|---|
| **1. Direct phrase match** | Brief contains a directly quoted passage from the source | String-search the quoted text (or a 6–10 word distinctive substring) across the opinion text. If pagination_mode is "reporter", verify the hit lies within ±1 page of the cited pincite. | High |
| **2. Parenthetical semantic match** | Brief uses an explanatory parenthetical: `(holding X)`, `(reasoning X)`, `(noting X)`, `(explaining X)`, etc. | Sonnet-tier semantic match: dispatch the parenthetical's content against the opinion text, preferring the pincite page when pagination_mode is "reporter". The parenthetical is a soft quote — the briefing author has committed to a characterization. | High–Medium |
| **3. Pincite-page semantic match** | pagination_mode is "reporter", but the brief has neither a direct quote nor an explanatory parenthetical (e.g., a bare `See` cite with no parenthetical) | Slice the opinion to the pincite page; Sonnet-tier semantic match between the brief's proposition (in its surrounding context) and the sentences on that page. | Medium |
| **4. Whole-opinion semantic search** | pagination_mode is "slip_only" or "none", OR Tier 3 returned no confident match | Sonnet-tier semantic match across the whole opinion text. If no passage scores above a confidence threshold, flag `pincite_page_unresolvable` and ask the user to point at the intended passage. | Low — surface to user |

Always start at Tier 1 and fall through. A successful Tier 1 hit short-circuits the more expensive tiers. When falling through, record `match_tier_used: <1|2|3|4>` on the citation entry for Stage 6 to consume.

#### Signal-relativized support assessment

The Bluebook signal (`See`, `Cf.`, `But see`, `See generally`, etc.) tells you what the brief *claims* about the cited source. Stage 6 (or any equivalent support-quality stage) must evaluate the support label relative to the signal, not against a strict "this passage states this proposition verbatim" bar:

| Signal | What the brief claims | Stage 6 evaluation bar |
|---|---|---|
| (no signal) | Source directly states the proposition | Standard bar: Strong if verbatim or near-verbatim; lower as the inferential gap widens. |
| `See` | Source supports the proposition, by implication or short inference | Standard bar — but a one-step inference is fully consistent with Strong. |
| `See, e.g.,` | Source is one example of authorities supporting the proposition | Standard bar, applied to *this* source only; don't ding the cite for not being the only authority. |
| `Cf.` | Source supports the proposition by analogy | Lower bar: an analogous holding is Adequate; a strict-on-point holding would also be Strong. The inferential gap is the *intended* mode of citation. |
| `But see`, `Contra` | Source *contradicts* the proposition | Inverted bar: "Strong" means strongly contradicts; "Misleading" means the cite is mislabeled (the source actually supports, or is on a different point). |
| `See generally` | Background or related authority | Loose bar: support is sufficient if the source is genuinely on the topic, even without supporting the specific proposition. Flag `Misleading` only if the cite is materially off-topic. |
| `Compare X, with Y` | Reader should compare the two; neither cite supports a single proposition standalone | Evaluate each side for whether it accurately represents what the cite says; the proposition is the *comparison*, not a single rule. |

When a citation uses a signal not listed here (e.g., `accord`, `see also`), default to the standard bar but note the signal in the explanation. Always record the signal alongside the proposition so Stage 6 has the necessary context.

#### Step 1 (MCP) — Resolve a citation to an opinion (privilege-safe, components only)

Once you've parsed the citation locally via `eyecite_extract.py`, look it up against CourtListener using the citation-lookup endpoint with **citation components only** — never document text:

```
call_endpoint(
  endpoint_id="citation-lookup",
  method="POST",
  body={"volume": "<vol>", "reporter": "<reporter>", "page": "<page>"},
)
```

This sends only the citation's public components (e.g., `volume=576&reporter=U.S.&page=155`), not the brief. The response's `clusters` array gives one or more candidate clusters; pick the right one by matching `case_name`, `date_filed`, and `citations` against what the brief says. Each cluster carries a `Cluster ID`.

For batches, loop over the unique citations from your local eyecite output and call this endpoint once per cite. Rate limit: 60 valid citations/minute — pace accordingly. **Do NOT use `analyze_citations` or pass document text to citation-lookup** even though the endpoint accepts a `text` parameter — those paths upload the full document.

#### Step 2 — Resolve to an opinion ID (MCP) and fetch the text (REST)

**Critical:** the citation-lookup response gives a **`Cluster ID`**, not an opinion ID. The `opinions` endpoint takes an opinion ID; passing a cluster ID will silently return whatever unrelated opinion happens to share that integer (or, for older single-opinion clusters, the correct opinion only by coincidence). You MUST resolve cluster → opinion first.

**Step 2a — Resolve cluster ID to opinion ID(s):**

```
call_endpoint(
  endpoint_id="clusters",
  query={"id": <cluster_id_from_citation_lookup>},
  num_results=1,
)
```

The response's `sub_opinions` array contains one or more opinion URIs of the form `https://www.courtlistener.com/api/rest/v4/opinions/<opinion_id>/`. Pick the right one using the **Choosing the right sub-opinion within a cluster** guidance above (prefer `020lead`, then `010combined`, switching to dissent/concurrence only if the brief specifically cites one). You typically need to fetch each candidate sub-opinion to read its `type` field, since `call_endpoint("clusters", ...)` returns URIs, not the `type` value directly — fetch them one at a time until you find the one matching your selection rule.

**Step 2b — Fetch the opinion text (REST, direct to disk):**

Opinion text is consumed only by local tools (grep, python), so it should never transit the conversation. Fetch it with `curl -o` straight to disk — **even when the MCP is available**:

```bash
curl -s "https://www.courtlistener.com/api/rest/v4/opinions/<opinion_id>/" \
  -o /tmp/opinion-<case-slug>.json
```

No token is needed by default — unauthenticated REST allows ~100 requests/day, ample for a typical brief's opinion fetches. If the run is large or CourtListener returns HTTP 429, ask the user for a free API token (courtlistener.com/sign-in/; authenticated: 5,000/hr) and add `--header "Authorization: Token [USER_TOKEN]"`.

The endpoint takes an **opinion ID** — the cluster→opinion resolution in Step 2a is still mandatory, and the cluster-as-opinion-ID hazard applies here identically. The saved JSON carries `html_with_citations`, `plain_text`, `xml_harvard`, and `type` (confirm `type` matches the sub-opinion you intended).

Why not the MCP for this step: any MCP tool result lands in the conversation, and getting it onto disk means re-emitting the full text through a Write call — token cost twice over, and for long opinions a transcription that risks truncation or silent corruption. A cite-check that verifies verbatim quotes cannot work from a lossy copy. `curl -o` writes the bytes untouched.

**MCP fallback (no shell network access only):** a single full read via `read_document(opinion_id=...)` (omit `chunk_index` — never use chunked reads to page around looking for a pincite), or `get_endpoint_item("opinions", <opinion_id>, fields=["id", "type", "html_with_citations", "plain_text"])`. Save the returned text to a temp file immediately and treat any size-related truncation as a fetch failure, not something to work around.

**Sanity check after fetching:** If the opinion's text does not contain the cited party names, reporter abbreviation, or any star-pagination marker overlapping the cited page range, you have fetched the wrong opinion. Re-resolve via `call_endpoint("clusters", ...)` and check the `sub_opinions` array. This check costs almost nothing and catches both the cluster-as-opinion-ID error and CourtListener's occasional cross-cluster ingest mismatches.

**Fetch once, then work locally — `search_document` is off-limits.** Opinion text goes API→disk once, and everything after that is local. `search_document` is a search tool: do NOT call it in this workflow, period — even though the server's own instructions recommend it for grepping snippets, **that server guidance is overridden here**. Every `search_document` call (and every chunked `read_document` hunt) is a network round-trip against CourtListener's API budget for text you already hold or could hold locally; it is far slower than local grep and spends the user's rate limits. ALL text searching, pincite extraction, and citation-graph traversal runs against the saved local file with local tools (grep, python).

This holds under pressure. Deadline, a fiddly grep, or a user saying "use whatever tool is fastest" are not exceptions — the local file IS the fastest path, and the fix for HTML-markup grep failures is to strip tags locally (one `re.sub`/`html.parser` pass), not to reach for `search_document`. The only thing that overrides this rule is the user naming `search_document` explicitly.

For downstream pincite-page slicing or anchor extraction, the local-file fields work the same as the scripted path:

- `html_with_citations` — **primary** field. Outbound citations as anchor tags AND star-pagination markers AND consolidated text, all in one. Use this for both proposition matching (strip tags first) and citation-graph traversal.
- `plain_text` — secondary fallback when `html_with_citations` is empty.
- `xml_harvard` — additional pagination source (`label="[PAGE]"` attributes); often omitted on newer opinions. Only worth requesting alongside the others when you anticipate ingestion-format-specific edge cases.

### REST API (resolution fallback when the MCP is absent)

The opinion-text fetch is *always* REST (Step 2b above). When the MCP is unavailable entirely, the resolution steps run over REST too. Resolution endpoints are stricter about auth than the opinions GET — collect a free token from the user (courtlistener.com/sign-in/; authenticated: 5,000 req/hour) and send it as a header:

```
Authorization: Token [USER_TOKEN]
```

**Step 1 — Resolve a citation to an opinion**

```bash
curl -s -X POST "https://www.courtlistener.com/api/rest/v4/citation-lookup/" \
  --header "Authorization: Token [USER_TOKEN]" \
  --data "volume=[VOL]&reporter=[REPORTER]&page=[PAGE]"
```

Returns a `clusters` array. Identify the correct cluster by matching `case_name`, `date_filed`, and `citations`. The `sub_opinions` field contains an array of opinion URIs — extract the numeric **opinion ID** from one of these URIs (NOT the cluster's own `id`, which is different) using the sub-opinion selection guidance above. The opinion ID is what Step 2b needs.

**Step 2 — Fetch the opinion text:** identical to Step 2b above (`curl -o /tmp/opinion-[CASE-SLUG].json`); add the token header if you collected one. Work from the local file for all subsequent pincite extraction and citation-graph traversal.

### Identity verification

Once an opinion is fetched (by either path), confirm it's the right one before using it:

- Confirm the reporter volume, reporter abbreviation, starting page, and party names match the input citation.
- If the fetched opinion has a different starting page, it is a different case — do not use it; treat the lookup as failed and fall through to the next source.

After fetching the candidate cluster from `citation-lookup`, perform the case-name cross-check yourself: compare the cluster's `case_name` to the brief's party names. If they diverge while the reporter/volume/page match, the brief likely contains a hallucinated or transposed citation — treat as failure-of-identity for the escalation chain below.

### Escalation chain for US cases

If CourtListener fails (no cluster, wrong cluster after verification, or opinion text unavailable), fall through in this order:

1. **CourtListener** (primary — MCP if available, REST API otherwise)
2. **Justia** (law.justia.com) — fallback if CourtListener lacks the opinion text
3. **Direct court websites** — SCOTUS (supremecourt.gov), circuit courts
4. **Google Scholar** — last resort; scraping is unreliable and may be blocked

After exhausting this chain, consuming skills ask the user directly; if the user cannot help, mark the citation `unverifiable`.

### Non-case US sources

For statutes (U.S.C.) and federal regulations (C.F.R.), the primary source is **Cornell LII**, fetched and parsed via the `lii_fetcher.py` script in this skill's directory. See `LII.md` alongside this file for the full pattern. Other source types (Federal Rules, secondary sources, treatises, legislative materials) are outside both CourtListener's and the LII script's scope; consuming skills use the source-specific lookup lists in their own Stage 4 (SSRN / direct law review sites for articles, Google Books for treatises, Congress.gov for legislative materials, etc.).

### EU / international

EUR-Lex for Court of Justice and EU secondary materials; HUDOC for European Court of Human Rights. Outside CourtListener's scope.

---

## LII source resolution (U.S.C. and C.F.R.)

US statutes and federal regulations are resolved through **Cornell LII** via the `lii_fetcher.py` script in this skill's directory (batch JSON in/out; stdlib-only). Full documentation — anchor scheme, input/output shapes, status semantics, and the deliberate no-fallback rule — lives in **`LII.md`** alongside this file. Read it before invoking `lii_fetcher.py`.

---
## Patent tooling

Patent citations are handled by four local scripts in this skill's directory: `patent_eyecite.py` (extraction + short-form resolution — the patent sibling of `eyecite_extract.py`), `patent_fetch.py` (PDF retrieval by public patent number), `patent_extract.py`/`patent_query.py` (column:line artifact build and lookup), and `patent_verify.py` (quote-location verification). All run locally; document text never leaves the machine. Full documentation — invocation, output shapes, the line-numbering truth model, the query contract, and the verify emit/resolve modes — lives in **`PATENTS.md`** alongside this file. Read it whenever a run contains patent citations. (The patent taxonomy, `'NNN`/inventor-name short forms, and the Patents structured-component schema remain in this file, above.)

---

## Model Tiers for Subtasks

Consuming skills dispatch many small subtasks in the course of a run. To control cost, delegate each subtask to the cheapest model that can reliably do it. Tier names (Haiku / Sonnet / Opus) refer to model families — resolve each to the newest available model in that family at run time rather than pinning a dated model ID. The guidance below is shared across all consumers (`cite-checking`, `chain-cite`, `table-of-authorities`). Skills may override in specific cases but should justify the override.

### Haiku — mechanical / pattern work

Use the current Haiku-tier model for tasks that are deterministic or near-deterministic string/pattern manipulation:

- **Citation parsing into the structured component schemas** above (splitting `547 U.S. at 391` into volume/reporter/page; identifying `Fed. R. Civ. P. 56(a)` as rule_set + rule_number + subsection).
- **Short-form resolution against a running citation stack** when the candidate set is small and the match is unambiguous (exact party-name match, exact reporter-volume-page match, unambiguous `Id.`). Escalate to Sonnet only when the toolkit's `unresolved_short_form` flag is about to be raised.
- **Star-pagination / pincite offset lookup** in `xml_harvard` or `html_with_citations` (locating `label="[PAGE]"` or `star-pagination">*[PAGE]`).
- **Exact-quote proposition localization** in `html_with_citations` after tag stripping (string search for the quoted passage; Match Ladder Tier 1).
- **Applying the flag vocabulary** once the judgment has been made — assigning an already-chosen flag name to an entry.
- **Category assignment** for the TOA's 7-category ordering when the citation_type is already known.

### Sonnet — judgment and synthesis

Use the current Sonnet-tier model for tasks that require semantic reasoning, judgment against legal conventions, or synthesis across multiple inputs:

- **Fuzzy / semantic proposition localization** when the quoted text in the brief is paraphrased, truncated, or uses a short form whose proposition must be re-extracted at the short-form location.
- **Drift annotation** — judging whether a predecessor opinion broadens, narrows, or rephrases a proposition (the work that distinguished Hop 1 from Hop 2 in the chain-cite test).
- **Next-hop selection from a string cite** — applying Bluebook 1.4 weight ordering and judging which predecessor actually carries the proposition.
- **Termination decisions** — `proposition_originates_here`, `source_synthesized_not_quoted`, and similar terminal reasons in `chain-cite`.
- **Support-quality labeling** in `cite-checking` Stage 6 (Strong / Adequate / Weak / Misleading / Unable to assess) and the accompanying précis.
- **Parenthetical judgment calls** — deciding whether `(citing X)` / `(applying X)` warrants a `citing_parenthetical` flag.
- **Ambiguity resolution** — any subtask that will otherwise raise `ambiguous_proposition`, `uncertain_category`, or `ambiguous_section_reference`.

### Opus — reserve for orchestration and critics

Use the current Opus-tier model sparingly:

- **The Stage 7 critic subagent in `cite-checking`** — by design this is an independent second opinion and should not be cost-matched to the primary analyzer.
- **The optional summary critic pass in `chain-cite`** when enabled.
- **The orchestrating skill itself** — the main loop that decides which subtask to dispatch next.

Do NOT use Opus for the per-hop / per-citation inner loops; that's how cost runs away.

### Override guidance

If a Haiku-tier task starts raising flags at high rates (e.g., short-form resolution frequently returning `unresolved_short_form`), the consuming skill should promote those specific calls to Sonnet rather than raising the whole stage's tier. Per-call promotion is cheaper than blanket escalation.

---

## Using This Skill

A consuming skill should include a short Prerequisites section like:

> **Prerequisites:** This skill uses the citation taxonomy, short-form resolution rules, structured component schemas, flag vocabulary, and CourtListener API patterns defined in the `citation-toolkit` skill. Read that skill first; this one refers to its definitions by name rather than restating them.

Then reference concepts by name (e.g., "parse the citation using the Case schema from citation-toolkit", "flag with `ambiguous_proposition`", "use citation-toolkit Step 1 to resolve the citation").
