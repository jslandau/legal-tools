# legal-tools

A Claude Code plugin with three skills for legal document work: extracting a Table of Authorities, verifying citations, and tracing a citation's lineage.

US case-law lookups go through the [claude.ai CourtListener MCP server](https://www.courtlistener.com/help/api/) when it's available (no token required, batched citation verification via eyecite + citation-lookup in one call), with a scripted REST-API fallback for environments without the MCP.

## Skills

### `table-of-authorities`

Scans a brief and produces a formatted Table of Authorities. Reads every page of the substantive content, identifies all legal citations (cases, statutes, constitutional provisions, legislative materials, secondary sources), resolves short forms (`Id.`, `supra`, reporter-only cites) back to their full citations, and outputs both JSON and formatted TOA text with page references.

**Use when:** You need to build or audit the TOA for an appellate brief.

---

### `cite-checking`

Checks every citation in a document against the actual source. For each citation it:
- Looks up the source online (CourtListener, eCFR, Cornell LII, SSRN, etc.)
- Extracts the text at the pincite
- Writes a neutral précis of what the source actually says
- Assigns a support quality label: **Strong / Adequate / Weak / Misleading / Unable to assess**
- Dispatches a separate Opus-tier critic subagent to independently review the analysis

Output is a standalone Markdown report saved next to the original document.

**Use when:** You want to verify that citations hold up — that the source actually says what the brief says it says.

---

### `chain-cite` ⚠️ experimental

Traces a single legal proposition backward through its citation graph to find the original source. Takes one proposition and one seed citation, walks hop by hop through CourtListener's opinion citations, annotates the relationship at each hop (quoting / paraphrasing / holding) and any semantic drift (broadens / narrows / rephrases), and terminates when the chain hits a natural end: a non-case source, a case CourtListener doesn't cover, an opinion that states the rule without citing a predecessor, or a cycle.

Output is a JSON chain and a Markdown report (summary first, full lineage second).

**Use when:** You want to know where a proposition *actually* comes from — not just what case a brief cites, but what that case cited, and what that case cited, all the way back.

> **Status:** This skill is under active development and may produce incomplete or incorrect chains. Results should be verified manually.

---

### `citation-toolkit` (internal)

Shared vocabulary used by all three skills above: citation taxonomy, short-form resolution rules, structured component schemas, flag vocabulary, CourtListener API patterns, and model-tier guidance for subagents. Not intended to be invoked directly.

## Installation

First, add the marketplace.
```
/plugin marketplace add jslandau/legal-tools
```
Then install the plugin, either via the /plugin TUI or via the following command.
```
/plugin install legal-tools@legal-tools
```

## Requirements

US case-law lookups require access to CourtListener. Two paths, in order of preference:

- **CourtListener MCP server (preferred)** — when the `claude.ai CourtListener` MCP server is installed and connected, no token is needed. The skills use `analyze_citations`, `get_endpoint_item`, and related MCP tools directly. Auth and rate limiting are handled by the MCP. This path also batches eyecite extraction with citation-lookup in one call, which is materially faster on documents with many citations.
- **CourtListener REST API (fallback)** — when the MCP is not available, a free CourtListener API token is required for `cite-checking` and `chain-cite`. Get one at [courtlistener.com/sign-in](https://www.courtlistener.com/sign-in/). The skills will ask for the token at the start of a run when they detect the MCP is absent.

`table-of-authorities` does not require either path — it uses local citation extraction (eyecite via the MCP's `extract_citations` tool when available, the skill's own parser otherwise) and does not need to verify citations against CourtListener.

## Supported document formats

PDF, plain text / Markdown, DOCX (including Word with tracked changes).
