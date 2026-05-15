---
name: cite-checking
description: Use when verifying citations in a legal brief or document — scans for every citation, looks up each source online, extracts the pincite text, and produces a standalone report assessing how well each citation supports the proposition it is cited for, with a critic subagent review of each assessment
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
3. **Where should the output report be saved?** (suggest: same directory as the document, named `<original-filename>-cite-check.md`)
4. **CourtListener access.** If the `claude.ai CourtListener` MCP server is available, no token is needed — Stage 4 uses the MCP directly. Otherwise, ask for a CourtListener API token (free at courtlistener.com/sign-in/) and note it for the scripted-fallback path in Stage 4.

## Supported Formats

- **PDF:** Use the Read tool. Use the document's own page numbering (footers/headers), NOT raw PDF page numbers.
- **Plain text / Markdown:** Look for explicit page markers (e.g., `## PAGE 1`). Ask the user to clarify if not obvious.
- **DOCX / Word with tracked changes:** Extract text using this python3 script, which also inlines footnotes with `[FNx: ...]` markers:

  ```bash
  python3 -c "
  import zipfile, xml.etree.ElementTree as ET
  def extract(path):
      with zipfile.ZipFile(path) as z:
          doc_tree = ET.parse(z.open('word/document.xml'))
          fn_text = {}
          if 'word/footnotes.xml' in z.namelist():
              for fn in ET.parse(z.open('word/footnotes.xml')).getroot().iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}footnote'):
                  fid = fn.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id')
                  fn_text[fid] = ''.join(t.text for t in fn.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t') if t.text)
      ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
      paras = []
      for p in doc_tree.getroot().iter(f'{{{ns}}}p'):
          line = ''.join(t.text for t in p.iter(f'{{{ns}}}t') if t.text)
          refs = [f'[FN{r.get(\"{{{ns}}}id\")}: {fn_text.get(r.get(\"{{{ns}}}id\"),\"\")}]' for r in p.iter(f'{{{ns}}}footnoteReference')]
          if line.strip() or refs: paras.append(line + ' '.join(refs))
      return '\n\n'.join(paras)
  print(extract('FILEPATH'))
  "
  ```

  Replace `FILEPATH` with the document path. Page boundaries in DOCX are approximate — warn the user. For tracked changes, the script extracts accepted-changes text; deleted text is ignored and inserted text is present.

---

## Stage 1 — Document Parsing

Read the document. Identify the substantive pages to process:

1. **Find body sections.** Look for headings: INTRODUCTION, ARGUMENT, STATEMENT OF THE CASE, STATEMENT OF FACTS, CONCLUSION. These are the pages to scan.
2. **Skip front matter.** Exclude cover pages, certificates of interest, tables of contents, any existing Table of Authorities, roman-numeral paginated pages.
3. **Skip back matter.** Exclude certificates of compliance, certificates of service, signature pages after CONCLUSION.
4. **Include footnotes** on substantive pages — they often contain important citations.
5. **Exclude non-authority references.** References to other briefs ("Blue Br.", "Appellant's Br."), appendix cites ("Appx123"), and record cites ("R. at 45") are not legal authorities — skip them.

---

## Stage 2 — Citation Extraction

Extraction is a two-pass process: **eyecite first, then a focused human pass for the gap categories.** Do not LLM-scan the document for citations — that is what eyecite is for, and re-doing its work wastes tokens and introduces errors.

**Pass 1 — eyecite (authoritative for recognized types).** Follow the **"Extraction: eyecite is the primitive (local only)"** section of `citation-toolkit`. Run the local `eyecite_extract.py` script in `citation-toolkit/` — extraction stays on-machine because briefs are routinely privileged. **Do NOT use the MCP's `extract_citations` or `analyze_citations` for this** (they upload the document text). The script's output is a JSON array of citations in document order with `Id.`/`supra`/short cites already linked to their antecedents — that *is* your citation stack for Stage 3, no manual re-derivation needed.

**Pass 2 — gap pass.** Walk the substantive text once looking *only* for the gap categories listed in `citation-toolkit` (administrative decisions, EU/international cases, popular-name statutes, informal constitutional references, state constitutional provisions, statute subsection breakdowns). Add these to the array produced by Pass 1. Do not re-extract anything eyecite already found.

**Pass 3 — proposition extraction.** For every citation (eyecite-extracted *and* gap-pass), capture the assertive clause it supports. eyecite returns the citation strings and their span offsets, not the propositional context — that is on you. Follow the **Proposition Extraction** rules in `citation-toolkit` (specific-assertion vs paragraph scope, mid-sentence and footnote handling, string-cite sharing, short-form propositions, `ambiguous_proposition` flag). Use the spans from Pass 1 to locate each citation in the source text precisely.

Apply the **Parenthetical Handling** rules from `citation-toolkit` when deciding whether a parenthetical like `(quoting X)` or `(citing Y)` creates an independent citation entry.

Maintain a **citation stack** only for gap-category cites and for any eyecite short forms flagged `unresolved_short_form` — eyecite already maintains the stack for everything else.

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

**Upfront pagination check.** Immediately after fetching each opinion, run `citation-toolkit`'s pagination-mode detection (single regex pass over `html_with_citations`) and record `pagination_mode` as one of `"reporter"`, `"slip_only"`, or `"none"`. This determines which match-ladder tier Stage 5 starts at and is consumed by Stage 6's confidence assessment.

**Batching tip:** Local eyecite already gave you the deduped list of unique case citations from the brief. Loop over that list and issue one components-only `call_endpoint("citation-lookup", ...)` per unique cite at the start of Stage 4 — rate-limited to 60 valid citations/minute, so pace accordingly. Then fetch only the opinion texts whose pincite content you actually need for Stage 5. (Do NOT use `analyze_citations` for batching — it uploads document text.)

**Cases (EU / international):**
1. EUR-Lex (eur-lex.europa.eu) — Court of Justice of the EU; search by ECLI or case name
2. HUDOC (hudoc.echr.coe.int) — European Court of Human Rights; search by application number or party names

**Federal statutes:**
1. Cornell LII (law.cornell.edu/uscode) — navigate to title and section directly
2. law.gov / Office of the Law Revision Counsel (uscode.house.gov)

**Federal regulations:**
1. eCFR (ecfr.gov) — navigate to title and section directly
2. GovInfo (govinfo.gov)
3. Federal Register (federalregister.gov) — for citations to specific Federal Register pages

**Federal rules:**
1. Cornell LII (law.cornell.edu) — covers FRCP, FRAP, FRE, and other federal rules
2. Direct court websites — Supreme Court Rules at supremecourt.gov

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

### Cases

Apply the **match ladder for pincite extraction** defined in `citation-toolkit` (four tiers: direct phrase match → parenthetical semantic match → pincite-page semantic match → whole-opinion semantic search). Start at Tier 1 and fall through until you get a confident match. Record `match_tier_used: <1|2|3|4>` on the citation entry — Stage 6 reads this to set confidence.

The starting tier depends on what the brief actually contains, not on the pincite alone:

- Brief contains a direct quote from the source → start at Tier 1.
- Brief uses an explanatory parenthetical (`(holding X)`, `(reasoning X)`, `(noting X)`, etc.) → if Tier 1 doesn't apply, start at Tier 2.
- Brief is a bare cite (with or without `See` / `Cf.` / `see also` etc.) → start at Tier 3 if `pagination_mode == "reporter"`; otherwise Tier 4.

When pagination_mode is `"slip_only"` or `"none"` (from the upfront check in Stage 4), Tier 3 is skipped — there is no reliable pincite page to slice. Go to Tier 4 (whole-opinion semantic search) and flag the entry with the appropriate pagination flag (`non_reporter_pagination_detected` or `pincite_page_unresolvable`).

Extract enough context to understand the proposition being stated (typically 100–300 words surrounding the matched passage).

### Other source types

- **Statutes and regulations:** Retrieve the text of the cited section/subsection in full.
- **Federal rules:** Retrieve the text of the cited rule and subsection in full.
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

After all citations have been processed through Stages 4–7, produce the cite-check report.

Save the report to the path agreed with the user before starting (default: `<original-filename>-cite-check.md` in the same directory as the source document).

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
