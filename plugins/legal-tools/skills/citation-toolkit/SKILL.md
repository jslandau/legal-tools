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

**CourtListener access: MCP-first.** When the `claude.ai CourtListener` MCP server is available, prefer its tools (auth and rate limiting are handled by the MCP — consuming skills do not need to collect a token from the user). Fall back to the scripted REST API (with a user-supplied bearer token) only when the MCP is unavailable. Both paths are documented below.

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
- Parsed by `patent_ref.py` into a `PatentRef` (see Structured Component Schemas). Patents are extracted by `patent_eyecite.py` (script section below); the LLM gap pass remains only as a recall backstop for informal references the regex finder cannot see (e.g., "the patent-in-suit").

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
| Look up a specific opinion by ID | `mcp__claude_ai_CourtListener__get_endpoint_item` with `endpoint_id="opinions"` | Replaces Step 2 (opinion fetch). **Always pass `fields=[...]`** — opinion text fields are huge. Useful field allowlists below. |
| Look up an opinion cluster (parallel cites, sub-opinions, case metadata) | `get_endpoint_item` with `endpoint_id="clusters"` | When the components-only `citation-lookup` call returns a `cluster_id` and you need its sub-opinions list, court, date, or canonical case name. |
| Free-text or fielded search | `mcp__claude_ai_CourtListener__search` | Use when the user has a case name but no cite, or to disambiguate between clusters. Pass `type="o"` for opinions, `"d"` for dockets, `"p"` for judges, `"oa"` for oral argument. Always pass `fields=[...]`. |
| Discover an endpoint's schema | `mcp__claude_ai_CourtListener__get_endpoint_schema` | When you need a field that's not on the search index — e.g., the full `opinions-cited` graph, party/attorney detail, financial disclosures. |
| Call any non-search endpoint | `mcp__claude_ai_CourtListener__call_endpoint` | For docket entries, recap-documents, opinions-cited, courts, parties, attorneys, etc. Pass `fields=[...]`. |
| Paginate prior results | `mcp__claude_ai_CourtListener__get_more_results` | Continue a `search` or `call_endpoint` query without re-issuing the filters. |
| Enumerate field choices | `mcp__claude_ai_CourtListener__get_choices` | When a schema says "use get_choices" (e.g., the 470 valid `court` values). |

#### Field allowlists for opinion fetches

Opinion text fields are enormous. **Always restrict `fields`**.

**Default to `html_with_citations` as primary across all skills**, with `plain_text` as a backup. `html_with_citations` is CourtListener's consolidated field — it includes the star-pagination markers AND the inline citation anchors AND the consolidated text, in one payload. `plain_text` is sometimes empty (especially for older or Harvard-CAP-only ingests), and when it is populated it does not always carry the same pagination scheme as `html_with_citations`. Request `html_with_citations` first; fall back to `plain_text` only when the HTML field is empty.

- **For proposition/pincite text searching (`cite-checking` Stage 5):** `["id", "html_with_citations", "plain_text"]`. Use `html_with_citations` after stripping tags; fall back to `plain_text` only if HTML is empty.
- **For star-pagination / pincite page extraction (`chain-cite` Stage 3):** `["id", "html_with_citations"]`. Optionally also request `"xml_harvard"` if you anticipate ingestion-format-specific edge cases.
- **For citation-graph traversal (`chain-cite` Stage 4):** `["id", "html_with_citations"]`. The anchors `<span class="citation" data-id="..."><a href="/opinion/{id}/...">` are what backward traversal walks.
- **For identity verification only (case name + date + reporter):** fetch the cluster instead — `get_endpoint_item("clusters", id, fields=["id", "case_name", "date_filed", "citations", "sub_opinions"])`.

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

#### Step 2 (MCP) — Fetch the opinion text

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

**Step 2b — Fetch the opinion text:**

Preferred: a single **full read** via `read_document` — it is cached server-side for 24 hours across all users (repeated fetches don't re-hit the API) and returns the opinion's `html_with_citations`:

```
read_document(opinion_id=<opinion_id_from_sub_opinions>)   # omit chunk_index → full document
```

It takes an **opinion ID** — the cluster→opinion resolution in Step 2a is still mandatory, and the cluster-as-opinion-ID hazard applies here identically. Because `read_document` returns only text, confirm the sub-opinion's `type` via the Step 2a metadata (or a fields-only `get_endpoint_item` with `fields=["id", "type"]`) before or after the read. **Save the returned text to a local temp file immediately** (e.g., `/tmp/opinion-<case-slug>.html`); the rest of the workflow operates on that file. Do NOT use chunked reads (`chunk_index`) to page around looking for a pincite — that is searching via the MCP; take the full document once.

Fallback (e.g., `read_document` errors, or you also want `xml_harvard`): fetch the raw fields:

```
get_endpoint_item(
  endpoint_id="opinions",
  item_id=<opinion_id_from_sub_opinions>,
  fields=["id", "type", "html_with_citations", "plain_text"],
)
```

Always include `"type"` in `fields` so you can confirm the sub-opinion is the one you intended.

**Sanity check after fetching:** If the opinion's text does not contain the cited party names, reporter abbreviation, or any star-pagination marker overlapping the cited page range, you have fetched the wrong opinion. Re-resolve via `call_endpoint("clusters", ...)` and check the `sub_opinions` array. This check costs almost nothing and catches both the cluster-as-opinion-ID error and CourtListener's occasional cross-cluster ingest mismatches.

**Fetch once, then work locally — `search_document` is off-limits.** The MCP is for *getting* documents, never for *searching* them. `read_document` is a fetch tool: use it once per opinion (full read, no `chunk_index`), save the text to disk, done. `search_document` is a search tool: do NOT call it in this workflow, period — even though the server's own instructions recommend it for grepping snippets, **that server guidance is overridden here**. Every `search_document` call (and every chunked `read_document` hunt) is a network round-trip against CourtListener's API budget for text you already hold or could hold locally; it is far slower than local grep and spends the user's rate limits. ALL text searching, pincite extraction, and citation-graph traversal runs against the saved local file with local tools (grep, python).

This holds under pressure. Deadline, a fiddly grep, or a user saying "use whatever tool is fastest" are not exceptions — the local file IS the fastest path, and the fix for HTML-markup grep failures is to strip tags locally (one `re.sub`/`html.parser` pass), not to reach for `search_document`. The only thing that overrides this rule is the user naming `search_document` explicitly.

For downstream pincite-page slicing or anchor extraction, the local-file fields work the same as the scripted path:

- `html_with_citations` — **primary** field. Outbound citations as anchor tags AND star-pagination markers AND consolidated text, all in one. Use this for both proposition matching (strip tags first) and citation-graph traversal.
- `plain_text` — secondary fallback when `html_with_citations` is empty.
- `xml_harvard` — additional pagination source (`label="[PAGE]"` attributes); often omitted on newer opinions. Only worth requesting alongside the others when you anticipate ingestion-format-specific edge cases.

### REST API (scripted fallback)

When the MCP is not available, use the REST API directly. Free public tokens are available at courtlistener.com/sign-in/ (authenticated: 5,000 req/hour; unauthenticated: ~100/day). The consuming skill collects the token from the user before calling these endpoints.

All requests use a bearer-token header:

```
Authorization: Token [USER_TOKEN]
```

**Step 1 — Resolve a citation to an opinion**

```bash
curl -s -X POST "https://www.courtlistener.com/api/rest/v4/citation-lookup/" \
  --header "Authorization: Token [USER_TOKEN]" \
  --data "volume=[VOL]&reporter=[REPORTER]&page=[PAGE]"
```

Returns a `clusters` array. Identify the correct cluster by matching `case_name`, `date_filed`, and `citations`. The `sub_opinions` field contains an array of opinion URIs — extract the numeric **opinion ID** from one of these URIs (NOT the cluster's own `id`, which is different) using the sub-opinion selection guidance above. The opinion ID is what Step 2 needs.

**Step 2 — Fetch the opinion text**

```bash
curl -s "https://www.courtlistener.com/api/rest/v4/opinions/[OPINION_ID]/" \
  --header "Authorization: Token [USER_TOKEN]" \
  -o /tmp/opinion-[CASE-SLUG].json
```

Work from the local file for all subsequent pincite extraction and citation-graph traversal. Field semantics (`plain_text`, `xml_harvard`, `html_with_citations`) are identical to the MCP path documented above.

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

For statutes (U.S.C.) and federal regulations (C.F.R.), the primary source is **Cornell LII**, fetched and parsed via the `lii_fetcher.py` script in this skill's directory. See the "LII source resolution" section below for the full pattern. Other source types (Federal Rules, secondary sources, treatises, legislative materials) are outside both CourtListener's and the LII script's scope; consuming skills use the source-specific lookup lists in their own Stage 4 (SSRN / direct law review sites for articles, Google Books for treatises, Congress.gov for legislative materials, etc.).

### EU / international

EUR-Lex for Court of Justice and EU secondary materials; HUDOC for European Court of Human Rights. Outside CourtListener's scope.

---

## LII source resolution (U.S.C. and C.F.R.)

US statutes and federal regulations are resolved through **Cornell LII** via the `lii_fetcher.py` script in this skill's directory. Like `eyecite_extract.py`, it is invoked as a subprocess, reads JSON on stdin (or `--input`), and writes JSON on stdout — one batch per run, not one call per citation.

### What it handles

- **Statutes**: `[title] U.S.C. § [section]` → `https://www.law.cornell.edu/uscode/text/{title}/{section}`
- **Regulations**: `[title] C.F.R. § [section]` → `https://www.law.cornell.edu/cfr/text/{title}/{section}` (where `section` includes the part, e.g., `201.6`)

Federal Rules (FRCP/FRAP/FRE) are **not** covered by this script yet. Use the existing case-side escalation pattern for those until they're wired through.

### Subsection anchors

LII tags subsections with one of two markup conventions, both keyed by the same anchor scheme:

- **U.S.C.**: `<a name="X"></a>` inside a `<div class="subsection|paragraph indentN">` container.
- **C.F.R.**: `<span class="enumxml" id="X">(X)</span>` inside a `<p class="psection-N">` container.

`X` is the subsection name with parens stripped and levels joined by underscores, preserving case: `(c)(2)` → `c_2`; `(b)(2)(C)(i)` → `b_2_C_i`. The script computes this from the Bluebook-style `subsection` field on the input entry. Single-level inputs that already look like anchors (e.g., `c_2`) are passed through unchanged.

### No fallback

If LII returns 404, or returns 200 with an empty section body (LII serves chrome-only pages for reserved or missing CFR sections), the script marks the entry `not_found`. There is no Wayback / archive fallback wired up: LII has been stable for decades, so a failure is more likely to indicate a bad citation or a network problem than a transient outage. The consuming skill escalates to the user and, failing that, marks `unverifiable`.

LII's CFR coverage in particular is patchy — some sections are reserved, some have content but no anchor for every subsection. A `subsection_anchor_not_found` result is **deliberately a false negative**: the script does not attempt to slice the section text heuristically when the anchor is absent, because that would silently substitute the wrong passage. The consuming skill should ask the user to confirm or mark `unverifiable`.

### Input shape

```json
[
  {"id": "c1", "type": "statute",    "title": "17", "section": "512",   "subsection": "(c)(2)"},
  {"id": "c2", "type": "regulation", "title": "29", "section": "1910.95","subsection": "(b)(1)"}
]
```

- `id`: opaque caller identifier; echoed back in the output.
- `type`: `"statute"` or `"regulation"`.
- `title`: title number (string or int).
- `section`: section identifier. For C.F.R., include the part (e.g., `"201.6"`, not `"6"`).
- `subsection`: Bluebook-style (`"(c)(2)"`), pre-computed anchor (`"c_2"`), or null/missing.

### Output shape

Same order as input. Per-entry fields:

```json
{
  "id": "c1",
  "status": "ok",                     // ok | anchor_not_found | not_found | network_error
  "url": "https://www.law.cornell.edu/uscode/text/17/512",
  "anchor": "c_2",
  "anchor_matched": true,
  "section_text": "...full § 512 text with tags stripped...",
  "subsection_text": "...just (c)(2)...",
  "retrieved_at": "YYYY-MM-DDTHH:MM:SSZ",
  "flags": []
}
```

Status semantics:
- `ok`: section fetched, and if a subsection was requested, its anchor was located and its text extracted.
- `anchor_not_found`: section fetched but the requested subsection anchor isn't in the page. `section_text` is populated; `subsection_text` is null. Flag `subsection_anchor_not_found`.
- `not_found`: LII returned 404 *or* served a chrome-only empty body. Flag `source_not_found`.
- `network_error`: timeout, 5xx, DNS, etc. `error` field carries a short description. The consuming skill decides whether to retry.

### Invocation

```bash
python3 plugins/legal-tools/skills/citation-toolkit/lii_fetcher.py --input requests.json
```

Or via stdin. The script is stdlib-only — no `pip install` required.

---

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

---

## Model Tiers for Subtasks

Consuming skills dispatch many small subtasks in the course of a run. To control cost, delegate each subtask to the cheapest model that can reliably do it. The guidance below is shared across all consumers (`cite-checking`, `chain-cite`, `table-of-authorities`). Skills may override in specific cases but should justify the override.

### Haiku — mechanical / pattern work

Use Haiku (`claude-haiku-4-5-20251001`) for tasks that are deterministic or near-deterministic string/pattern manipulation:

- **Citation parsing into the structured component schemas** above (splitting `547 U.S. at 391` into volume/reporter/page; identifying `Fed. R. Civ. P. 56(a)` as rule_set + rule_number + subsection).
- **Short-form resolution against a running citation stack** when the candidate set is small and the match is unambiguous (exact party-name match, exact reporter-volume-page match, unambiguous `Id.`). Escalate to Sonnet only when the toolkit's `unresolved_short_form` flag is about to be raised.
- **Star-pagination / pincite offset lookup** in `xml_harvard` or `html_with_citations` (locating `label="[PAGE]"` or `star-pagination">*[PAGE]`).
- **Exact-quote proposition localization** in `html_with_citations` after tag stripping (string search for the quoted passage; Match Ladder Tier 1).
- **Applying the flag vocabulary** once the judgment has been made — assigning an already-chosen flag name to an entry.
- **Category assignment** for the TOA's 7-category ordering when the citation_type is already known.

### Sonnet — judgment and synthesis

Use Sonnet (`claude-sonnet-4-6`) for tasks that require semantic reasoning, judgment against legal conventions, or synthesis across multiple inputs:

- **Fuzzy / semantic proposition localization** when the quoted text in the brief is paraphrased, truncated, or uses a short form whose proposition must be re-extracted at the short-form location.
- **Drift annotation** — judging whether a predecessor opinion broadens, narrows, or rephrases a proposition (the work that distinguished Hop 1 from Hop 2 in the chain-cite test).
- **Next-hop selection from a string cite** — applying Bluebook 1.4 weight ordering and judging which predecessor actually carries the proposition.
- **Termination decisions** — `proposition_originates_here`, `source_synthesized_not_quoted`, and similar terminal reasons in `chain-cite`.
- **Support-quality labeling** in `cite-checking` Stage 6 (Strong / Adequate / Weak / Misleading / Unable to assess) and the accompanying précis.
- **Parenthetical judgment calls** — deciding whether `(citing X)` / `(applying X)` warrants a `citing_parenthetical` flag.
- **Ambiguity resolution** — any subtask that will otherwise raise `ambiguous_proposition`, `uncertain_category`, or `ambiguous_section_reference`.

### Opus — reserve for orchestration and critics

Use Opus (`claude-opus-4-7`) sparingly:

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
