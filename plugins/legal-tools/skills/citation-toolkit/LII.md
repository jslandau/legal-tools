# LII Source Resolution (U.S.C. and C.F.R.)

Reference companion to `citation-toolkit/SKILL.md`. Read this file when a run contains statute (U.S.C.) or regulation (C.F.R.) citations that need source resolution.


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
