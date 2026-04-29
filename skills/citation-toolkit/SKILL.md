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

When a consuming skill needs the user's CourtListener token, the consuming skill collects it (typically in its own "Before Starting" questionnaire) and passes it through to the API calls described below.

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

---

## Short Forms

Short forms require a **citation stack** — the running list of recently-cited authorities maintained in document order so short forms can be resolved to their antecedents.

- `Id.` → resolves to the immediately preceding citation (even across page boundaries; track meticulously)
- Party-name short forms: `[Party], [vol] [reporter] at [page]`
- Reporter-only: `[vol] [reporter] at [page]`
- `supra` / `supra note [X]`
- Informal references ("the Paxton court", "Daubert standard") → resolve to case; flag `informal_reference`

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
| `unverifiable` | Source could not be located after escalation chain exhausted |

Consuming skills may define their own additional flags for workflow-specific situations (e.g., `chain-cite` needs flags for drift annotations across hops). Keep the ones above consistent.

---

## CourtListener API

Primary source for US case law. Free public tokens are available at courtlistener.com/sign-in/ (authenticated: 5,000 req/hour; unauthenticated: ~100/day). Consuming skills collect the token from the user before calling these endpoints.

Do NOT attempt to scrape `courtlistener.com` pages — they are JavaScript-rendered and will return empty content. Use the REST API.

### Auth

All requests use a bearer-token header:

```
Authorization: Token [USER_TOKEN]
```

### Step 1 — Resolve a citation to an opinion

```bash
curl -s -X POST "https://www.courtlistener.com/api/rest/v4/citation-lookup/" \
  --header "Authorization: Token [USER_TOKEN]" \
  --data "volume=[VOL]&reporter=[REPORTER]&page=[PAGE]"
```

Returns a `clusters` array. Identify the correct cluster by matching `case_name`, `date_filed`, and `citations`. Note the opinion ID from `sub_opinions`.

### Step 2 — Fetch the opinion text

```bash
curl -s "https://www.courtlistener.com/api/rest/v4/opinions/[OPINION_ID]/" \
  --header "Authorization: Token [USER_TOKEN]" \
  -o /tmp/opinion-[CASE-SLUG].json
```

Work from the local file for all subsequent pincite extraction and citation-graph traversal.

- Use `plain_text` for searching and semantic matching of propositions.
- Use `xml_harvard` for star-pagination markers (format: `label="[PAGE]"`) when you need to locate a specific pincite page within the opinion.
- Use `html_with_citations` when you need the opinion's **outbound citations** marked up in context — every citation is wrapped in an anchor tag, which makes it possible to correlate a cited authority with the passage that cites it. This is the field `chain-cite` relies on for backward traversal.

### Identity verification

Once an opinion is fetched, confirm it's the right one before using it:

- Confirm the reporter volume, reporter abbreviation, starting page, and party names match the input citation.
- If the fetched opinion has a different starting page, it is a different case — do not use it; treat the lookup as failed and fall through to the next source.

### Escalation chain for US cases

If CourtListener fails (no cluster, wrong cluster after verification, or opinion text unavailable), fall through in this order:

1. **CourtListener** (primary — as above)
2. **Justia** (law.justia.com) — fallback if CourtListener lacks the opinion text
3. **Direct court websites** — SCOTUS (supremecourt.gov), circuit courts
4. **Google Scholar** — last resort; scraping is unreliable and may be blocked

After exhausting this chain, consuming skills ask the user directly; if the user cannot help, mark the citation `unverifiable`.

### Non-case US sources

For statutes, regulations, rules, and secondary sources, use the consuming skill's source-specific lookup list (Cornell LII for statutes and rules, eCFR for regulations, SSRN / direct law review sites for articles, Google Books for treatises, Congress.gov for legislative materials). These are outside CourtListener's scope.

### EU / international

EUR-Lex for Court of Justice and EU secondary materials; HUDOC for European Court of Human Rights. Outside CourtListener's scope.

---

## Model Tiers for Subtasks

Consuming skills dispatch many small subtasks in the course of a run. To control cost, delegate each subtask to the cheapest model that can reliably do it. The guidance below is shared across all consumers (`cite-checking`, `chain-cite`, `table-of-authorities`). Skills may override in specific cases but should justify the override.

### Haiku — mechanical / pattern work

Use Haiku (`claude-haiku-4-5-20251001`) for tasks that are deterministic or near-deterministic string/pattern manipulation:

- **Citation parsing into the structured component schemas** above (splitting `547 U.S. at 391` into volume/reporter/page; identifying `Fed. R. Civ. P. 56(a)` as rule_set + rule_number + subsection).
- **Short-form resolution against a running citation stack** when the candidate set is small and the match is unambiguous (exact party-name match, exact reporter-volume-page match, unambiguous `Id.`). Escalate to Sonnet only when the toolkit's `unresolved_short_form` flag is about to be raised.
- **Star-pagination / pincite offset lookup** in `xml_harvard` or `html_with_citations` (locating `label="[PAGE]"` or `star-pagination">*[PAGE]`).
- **Exact-quote proposition localization** in `plain_text` (string search for the quoted passage).
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
