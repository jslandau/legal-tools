"""Tests for patent_eyecite.py — patent citation extraction."""
from __future__ import annotations


class TestCleanPatentText:
    """clean_patent_text: 1:1 character normalization preserving offsets."""

    def test_curly_apostrophes_become_straight(self):
        """Right/left single curly quotes and backtick normalize to '."""
        from patent_eyecite import clean_patent_text

        assert clean_patent_text("the '642 patent") == "the '642 patent"
        assert clean_patent_text("the '642 patent") == "the '642 patent"
        assert clean_patent_text("the `642 patent") == "the '642 patent"

    def test_curly_double_quotes_become_straight(self):
        """Curly double quotes normalize to plain double quote."""
        from patent_eyecite import clean_patent_text

        # Using raw string to handle curly quotes properly
        input_str = '("the \'642 patent")'
        expected = '("the \'642 patent")'
        assert clean_patent_text(input_str) == expected

    def test_dashes_become_hyphen(self):
        """En dash and em dash normalize to ASCII hyphen."""
        from patent_eyecite import clean_patent_text

        assert clean_patent_text("5:12–18") == "5:12-18"
        assert clean_patent_text("5:12—18") == "5:12-18"

    def test_newlines_and_nbsp_become_spaces(self):
        """Newline, CR, tab, NBSP each become a single space (1:1)."""
        from patent_eyecite import clean_patent_text

        assert clean_patent_text("8,453,\n642") == "8,453, 642"
        assert clean_patent_text("No. 8,453,642") == "No. 8,453,642"

    def test_length_always_preserved(self):
        """The 1:1 guarantee: output length equals input length."""
        from patent_eyecite import clean_patent_text

        s = "U.S. Patent\r\nNo. 8,453,\n642 — col.\t4, ll. 12–15 (the 642 patent)"
        assert len(clean_patent_text(s)) == len(s)


def _cites(text: str) -> list[dict]:
    from patent_eyecite import clean_patent_text, get_patent_citations
    return get_patent_citations(clean_patent_text(text))


class TestUsLongForms:
    """US long-form span finding and parsing."""

    def test_canonical_long_form(self):
        """'U.S. Patent No. 8,453,642' is found, parsed, span-exact."""
        text = "See U.S. Patent No. 8,453,642 at col. 4."
        cites = _cites(text)

        assert len(cites) == 1
        c = cites[0]
        assert c["citation_type"] == "patent"
        assert c["ref"]["kind"] == "grant"
        assert c["ref"]["canonical_number"] == "8453642"
        start, end = c["span"]
        assert text[start:end] == "U.S. Patent No. 8,453,642"

    def test_pat_no_abbreviation_with_kind_code(self):
        """'US Pat. No. 8,453,642 B2' parses; kind code inside the span."""
        cites = _cites("US Pat. No. 8,453,642 B2 discloses a mask.")

        assert len(cites) == 1
        assert cites[0]["ref"]["canonical_number"] == "8453642"

    def test_united_states_spelled_out(self):
        """'United States Patent 8,453,642' (no 'No.') is found."""
        cites = _cites("In United States Patent 8,453,642, the inventor...")

        assert len(cites) == 1
        assert cites[0]["ref"]["canonical_number"] == "8453642"

    def test_uncommaed_number(self):
        """'U.S. Patent No. 8453642' (no commas) is found."""
        cites = _cites("U.S. Patent No. 8453642.")

        assert len(cites) == 1
        assert cites[0]["ref"]["canonical_number"] == "8453642"

    def test_number_split_across_line_break(self):
        """A number broken by a soft line break still extracts after clean —
        and parses as a real fetchable grant, not best-effort 'unsupported'."""
        cites = _cites("U.S. Patent No. 8,453,\n642 teaches a vent.")

        assert len(cites) == 1
        assert cites[0]["ref"]["kind"] == "grant"
        assert cites[0]["ref"]["fetchable"] is True
        assert cites[0]["ref"]["canonical_number"] == "8453642"

    def test_design_patent(self):
        """Design patents (D-prefix) parse as grants."""
        cites = _cites("U.S. Patent No. D645,062 covers the ornamental design.")

        assert len(cites) == 1
        assert cites[0]["ref"]["canonical_number"] == "D645062"

    def test_reissue_patent(self):
        """Reissue patents (RE-prefix) parse as grants."""
        cites = _cites("U.S. Patent No. RE38,161 was asserted.")

        assert len(cites) == 1
        assert cites[0]["ref"]["canonical_number"] == "RE38161"

    def test_nos_list_expands_to_multiple_citations(self):
        """'Nos. X and Y' yields one citation per number, sharing the anchor span."""
        text = "U.S. Patent Nos. 8,453,642 and 9,154,231 are asserted."
        cites = _cites(text)

        assert len(cites) == 2
        assert cites[0]["ref"]["canonical_number"] == "8453642"
        assert cites[1]["ref"]["canonical_number"] == "9154231"
        # Both share the full matched anchor span.
        assert cites[0]["span"] == cites[1]["span"]

    def test_nos_comma_list(self):
        """'Nos. X, Y, and Z' yields three citations."""
        cites = _cites("U.S. Patent Nos. 8,453,642, 9,154,231, and 8,131,198.")

        nums = [c["ref"]["canonical_number"] for c in cites]
        assert nums == ["8453642", "9154231", "8131198"]


class TestAppPubForms:
    """Application-publication span finding."""

    def test_apppub_slash_form(self):
        """'U.S. Patent Application Pub. No. 2009/0151718 A1' is found as apppub."""
        cites = _cites("U.S. Patent Application Pub. No. 2009/0151718 A1 describes a seal.")

        assert len(cites) == 1
        assert cites[0]["ref"]["kind"] == "apppub"
        assert cites[0]["ref"]["canonical_number"] == "20090151718"

    def test_apppub_publication_spelled_out(self):
        """'Publication No. 2009/0151718' label variant is found."""
        cites = _cites("See Patent Application Publication No. 2009/0151718.")

        assert len(cites) == 1
        assert cites[0]["ref"]["kind"] == "apppub"

    def test_apppub_us_prefixed_compact(self):
        """'US 2009/0151718 A1' (US-prefixed, no label words) is found."""
        cites = _cites("Prior art includes US 2009/0151718 A1.")

        assert len(cites) == 1
        assert cites[0]["ref"]["kind"] == "apppub"
        assert cites[0]["ref"]["canonical_number"] == "20090151718"


class TestInternationalForms:
    """EP / WO / PCT span finding (parsing added in Phase 1)."""

    def test_ep_compact(self):
        cites = _cites("EP1234567 B1 discloses a similar vent.")

        assert len(cites) == 1
        assert cites[0]["ref"]["kind"] == "ep"
        assert cites[0]["ref"]["fetchable"] is False

    def test_ep_spaced(self):
        cites = _cites("European application EP 1 234 567 A2 was cited.")

        assert len(cites) == 1
        assert cites[0]["ref"]["canonical_number"] == "EP1234567"

    def test_wo_slash(self):
        cites = _cites("WO 2009/151718 published in December 2009.")

        assert len(cites) == 1
        assert cites[0]["ref"]["kind"] == "wo"

    def test_pct_application(self):
        cites = _cites("filed as PCT/US2009/046667 on June 9, 2009.")

        assert len(cites) == 1
        assert cites[0]["ref"]["kind"] == "pct_app"


class TestShortForms:
    """Short-form span finding (resolution comes in Phase 4)."""

    def test_three_digit_short_form(self):
        """\"the '642 patent\" is found as patent_short with ref=None."""
        text = "As explained above, the '642 patent requires a vent."
        cites = _cites(text)

        assert len(cites) == 1
        c = cites[0]
        assert c["citation_type"] == "patent_short"
        assert c["ref"] is None
        start, end = c["span"]
        assert text[start:end] == "the '642 patent"

    def test_curly_apostrophe_short_form(self):
        """Curly-apostrophe '642 is found (clean layer normalizes it)."""
        text = "the '642 patent requires a vent"
        from patent_eyecite import clean_patent_text, get_patent_citations
        cites = get_patent_citations(clean_patent_text(text))

        assert len(cites) == 1
        assert cites[0]["citation_type"] == "patent_short"

    def test_short_form_publication_noun(self):
        """\"the '718 publication\" is also a short form."""
        cites = _cites("the '718 publication discloses the same seal")

        assert len(cites) == 1
        assert cites[0]["citation_type"] == "patent_short"

    def test_inventor_name_short_form(self):
        """'the Kwok patent' is found as an inventor-name short form."""
        cites = _cites("As shown in the Kwok patent, the cushion seals.")

        assert len(cites) == 1
        assert cites[0]["citation_type"] == "patent_short"

    def test_common_adjectives_not_inventor_names(self):
        """'the Asserted patent' / 'the Subject patent' are NOT citations."""
        assert _cites("the Asserted patent fails under § 101") == []
        assert _cites("the Subject patent expired in 2019") == []


class TestNicknameParentheticals:
    """Nickname parentheticals attach to the preceding long form."""

    def test_nickname_attaches_and_is_not_separate_citation(self):
        """(\"the '642 patent\") becomes an attribute, not a second entry."""
        text = 'U.S. Patent No. 8,453,642 ("the \'642 patent") is asserted.'
        cites = _cites(text)

        assert len(cites) == 1
        assert cites[0]["citation_type"] == "patent"
        assert cites[0]["nickname"] == "the '642 patent"

    def test_inventor_nickname(self):
        """(the Kwok patent) without quotes attaches as a nickname."""
        cites = _cites("U.S. Patent No. 8,453,642 (the Kwok patent) is asserted.")

        assert len(cites) == 1
        assert cites[0]["nickname"] == "the Kwok patent"

    def test_distant_parenthetical_does_not_attach(self):
        """A parenthetical far from any long form is a plain short form."""
        text = "U.S. Patent No. 8,453,642 claims a mask. Much later in the document (\"the '642 patent\") appears."
        cites = _cites(text)

        assert cites[0]["nickname"] is None


class TestMergeAndOrder:
    """Longest-match-wins merge; document order; no false positives."""

    def test_long_form_wins_over_embedded_short_pattern(self):
        """An apppub label is not also matched as a bare US long form."""
        cites = _cites("U.S. Patent Application Pub. No. 2009/0151718 A1.")

        assert len(cites) == 1
        assert cites[0]["ref"]["kind"] == "apppub"

    def test_entries_in_document_order(self):
        text = "the '642 patent ... U.S. Patent No. 9,154,231 ... WO 2009/151718"
        cites = _cites(text)

        spans = [c["span"][0] for c in cites]
        assert spans == sorted(spans)
        assert [c["citation_type"] for c in cites] == [
            "patent_short", "patent", "patent",
        ]

    def test_plain_prose_has_no_citations(self):
        """Ordinary prose with numbers and ratios yields nothing."""
        assert _cites("The ratio was 4:1 in 2009, per section 8.") == []


class TestCli:
    """main(argv): --input/stdin in, JSON array out (eyecite_extract shape)."""

    def test_main_reads_stdin_emits_json(self, capsys, monkeypatch):
        """Default invocation reads raw text on stdin, prints a JSON array."""
        import io
        import json
        from patent_eyecite import main

        monkeypatch.setattr(
            "sys.stdin", io.StringIO("See U.S. Patent No. 8,453,642.")
        )
        result = main([])

        assert result == 0
        out = json.loads(capsys.readouterr().out)
        assert isinstance(out, list)
        assert out[0]["citation_type"] == "patent"
        assert out[0]["ref"]["canonical_number"] == "8453642"

    def test_main_reads_input_file(self, capsys, tmp_path):
        """--input reads text from a file path."""
        import json
        from patent_eyecite import main

        f = tmp_path / "brief.txt"
        f.write_text("the '642 patent controls.", encoding="utf-8")

        result = main(["--input", str(f)])

        assert result == 0
        out = json.loads(capsys.readouterr().out)
        assert out[0]["citation_type"] == "patent_short"

    def test_main_missing_input_file_exits_2(self, capsys):
        """A nonexistent --input path is a usage error: exit 2, message on stderr."""
        from patent_eyecite import main

        result = main(["--input", "/nonexistent/path.txt"])

        assert result == 2
        assert "ERROR" in capsys.readouterr().err

    def test_spans_index_original_text(self, capsys, monkeypatch):
        """Emitted spans slice the ORIGINAL (uncleaned) text correctly."""
        import io
        import json
        from patent_eyecite import main

        original = "the '642 patent controls."
        monkeypatch.setattr("sys.stdin", io.StringIO(original))
        main([])

        out = json.loads(capsys.readouterr().out)
        start, end = out[0]["span"]
        assert original[start:end] == "the '642 patent"


class TestExplicitColumnLinePincites:
    """Explicit col./ll. pincites attach inside the proximity window."""

    def test_col_ll_range(self):
        """'col. 4, ll. 12-15' attaches as a column_line pincite."""
        cites = _cites("U.S. Patent No. 8,453,642, col. 4, ll. 12-15.")

        p = cites[0]["pincite"]
        assert p == {
            "kind": "column_line",
            "start_column": 4, "start_line": 12,
            "end_column": 4, "end_line": 15,
        }

    def test_col_single_line(self):
        """'col. 4, l. 12' attaches with start == end."""
        cites = _cites("the '642 patent at col. 4, l. 12")

        p = cites[0]["pincite"]
        assert p["start_line"] == 12 and p["end_line"] == 12

    def test_spelled_out_column_lines(self):
        """'column 4, lines 12-15' (spelled out) attaches."""
        cites = _cites("U.S. Patent No. 8,453,642 at column 4, lines 12-15.")

        assert cites[0]["pincite"]["start_column"] == 4

    def test_cross_column_explicit(self):
        """'col. 4, l. 65 to col. 5, l. 3' attaches as a cross-column span."""
        cites = _cites("the '642 patent, col. 4, l. 65 to col. 5, l. 3")

        p = cites[0]["pincite"]
        assert p == {
            "kind": "column_line",
            "start_column": 4, "start_line": 65,
            "end_column": 5, "end_line": 3,
        }


class TestCompactPincites:
    """Compact N:M pincites: in-window only, never bare in prose."""

    def test_compact_in_window(self):
        """'the '642 patent at 5:12-18' attaches."""
        cites = _cites("the '642 patent at 5:12-18 discloses the seal")

        p = cites[0]["pincite"]
        assert p == {
            "kind": "column_line",
            "start_column": 5, "start_line": 12,
            "end_column": 5, "end_line": 18,
        }

    def test_compact_cross_column(self):
        """'4:65-5:3' cross-column compact form attaches."""
        cites = _cites("U.S. Patent No. 8,453,642 at 4:65-5:3.")

        p = cites[0]["pincite"]
        assert p == {
            "kind": "column_line",
            "start_column": 4, "start_line": 65,
            "end_column": 5, "end_line": 3,
        }

    def test_compact_single_point(self):
        """'5:12' single point attaches with start == end."""
        cites = _cites("the '642 patent, 5:12")

        p = cites[0]["pincite"]
        assert (p["start_column"], p["start_line"]) == (5, 12)
        assert (p["end_column"], p["end_line"]) == (5, 12)

    def test_bare_ratio_outside_window_not_emitted(self):
        """A bare N:M with no citation nearby is never a citation or pincite."""
        assert _cites("The vote split 5:4 and the odds were 12:1.") == []

    def test_out_of_window_compact_does_not_attach(self):
        """A compact N:M past the window boundary does not attach."""
        text = (
            "U.S. Patent No. 8,453,642 discloses a respiratory mask assembly "
            "with an improved vent arrangement for exhaust gas washout. "
            "Meanwhile the meeting ran from 5:12 onward."
        )
        cites = _cites(text)

        assert cites[0]["pincite"] is None

    def test_intervening_prose_blocks_attachment(self):
        """Within 80 chars but across real prose (not commas/'at'), no attach."""
        cites = _cites("the '642 patent was filed before the deadline of 5:12")

        assert cites[0]["pincite"] is None

    def test_section_symbol_flags_ambiguous(self):
        """An in-window match adjacent to '§' attaches but is flagged."""
        cites = _cites("the '642 patent, § 5:12")

        assert cites[0]["pincite"] is not None
        assert "ambiguous_pincite" in cites[0]["flags"]

    def test_timestamp_not_a_pincite(self):
        """'at 9:30 a.m.' near a citation is rejected (a.m./p.m. signal)."""
        cites = _cites("the '642 patent, at 9:30 a.m.")

        assert cites[0]["pincite"] is None


class TestParagraphPincites:
    """App-pub paragraph pincites."""

    def test_pilcrow_bracket_form(self):
        """'¶ [0042]' attaches as a paragraph pincite."""
        cites = _cites("U.S. Patent Application Pub. No. 2009/0151718 ¶ [0042].")

        assert cites[0]["pincite"] == {"kind": "paragraph", "paragraph": 42}

    def test_para_abbreviation(self):
        """'para. 0042' attaches."""
        cites = _cites("the '718 publication at para. 0042")

        assert cites[0]["pincite"] == {"kind": "paragraph", "paragraph": 42}

    def test_spelled_paragraph(self):
        """'paragraph 42' attaches."""
        cites = _cites("the '718 publication at paragraph 42")

        assert cites[0]["pincite"] == {"kind": "paragraph", "paragraph": 42}


class TestClaimPincites:
    """Claim references: attached backward, attached forward, or standalone."""

    def test_claims_attach_in_window(self):
        """'the '642 patent, claims 1-3' attaches a claims pincite."""
        cites = _cites("the '642 patent, claims 1-3")

        assert cites[0]["pincite"] == {
            "kind": "claims", "start_claim": 1, "end_claim": 3,
        }

    def test_claim_of_citation_attaches_forward(self):
        """'claim 1 of the '642 patent' attaches to the FOLLOWING citation."""
        cites = _cites("Defendant infringes claim 1 of the '642 patent.")

        assert len(cites) == 1
        assert cites[0]["citation_type"] == "patent_short"
        assert cites[0]["pincite"] == {
            "kind": "claims", "start_claim": 1, "end_claim": 1,
        }

    def test_standalone_claim_becomes_patent_claim_entry(self):
        """A claim ref with no adjacent citation is a standalone entry."""
        text = "U.S. Patent No. 8,453,642 is asserted. Claim 9 recites a vent."
        cites = _cites(text)

        assert len(cites) == 2
        standalone = cites[1]
        assert standalone["citation_type"] == "patent_claim"
        assert standalone["ref"] is None
        assert standalone["pincite"] == {
            "kind": "claims", "start_claim": 9, "end_claim": 9,
        }
        start, end = standalone["span"]
        assert text[start:end] == "Claim 9"

    def test_claim_number_in_plain_prose_without_any_patent(self):
        """Standalone claim entries are still emitted without a stack —
        resolution (and flagging) is Phase 4's job."""
        cites = _cites("Claim 1 was amended during prosecution.")

        assert len(cites) == 1
        assert cites[0]["citation_type"] == "patent_claim"


def _resolved(text: str) -> list[dict]:
    from patent_eyecite import (
        clean_patent_text, get_patent_citations, resolve_patent_citations,
    )
    return resolve_patent_citations(get_patent_citations(clean_patent_text(text)))


class TestShortFormResolution:
    """'NNN short forms resolve against the citation stack."""

    def test_simple_resolution(self):
        """'the '642 patent' resolves to the only matching full citation."""
        cites = _resolved(
            "U.S. Patent No. 8,453,642 is asserted. The '642 patent requires a vent."
        )

        short = cites[1]
        assert short["citation_type"] == "patent_short"
        assert short["resolved_to"] == {
            "index": 0, "full_citation": cites[0]["full_citation"],
        }
        assert short["flags"] == []

    def test_multi_patent_brief(self):
        """Each short form resolves to its own patent in a two-patent brief."""
        cites = _resolved(
            "U.S. Patent No. 8,453,642 and U.S. Patent No. 9,154,231 are asserted. "
            "The '642 patent claims a mask; the '231 patent claims a cushion."
        )

        assert cites[2]["resolved_to"]["index"] == 0
        assert cites[3]["resolved_to"]["index"] == 1

    def test_short_form_before_any_introduction_is_unresolved(self):
        """A short form with an empty stack is flagged, candidates empty."""
        cites = _resolved("The '642 patent requires a vent.")

        short = cites[0]
        assert short["resolved_to"] is None
        assert "unresolved_short_form" in short["flags"]
        assert short["candidates"] == []

    def test_colliding_last_three_digits(self):
        """Two distinct patents ending in the same 3 digits → unresolved
        with both as candidates."""
        cites = _resolved(
            "U.S. Patent No. 8,453,642 and U.S. Patent No. 7,100,642 are asserted. "
            "The '642 patent requires a vent."
        )

        short = cites[2]
        assert short["resolved_to"] is None
        assert "unresolved_short_form" in short["flags"]
        assert short["candidates"] == [0, 1]

    def test_same_patent_twice_is_not_a_collision(self):
        """The same canonical number on the stack twice resolves to the
        most recent occurrence, no flag."""
        cites = _resolved(
            "U.S. Patent No. 8,453,642 was filed in 2009. "
            "U.S. Patent No. 8,453,642 issued in 2013. "
            "The '642 patent is valid."
        )

        short = cites[2]
        assert short["resolved_to"]["index"] == 1
        assert "unresolved_short_form" not in short["flags"]

    def test_nickname_digits_resolve(self):
        """A nickname parenthetical registers its digits on the stack even
        when they differ from the patent number's own last 3."""
        cites = _resolved(
            'U.S. Patent No. 8,453,642 ("the \'642 patent") is asserted. '
            "The '642 patent requires a vent."
        )

        assert cites[1]["resolved_to"]["index"] == 0


class TestInventorNameResolution:
    """Inventor-name short forms resolve from in-text introductions."""

    def test_nickname_parenthetical_registers_name(self):
        """'(the Kwok patent)' introduces the name; later use resolves."""
        cites = _resolved(
            "U.S. Patent No. 8,453,642 (the Kwok patent) is asserted. "
            "The Kwok patent requires a vent."
        )

        assert len(cites) == 2
        assert cites[1]["resolved_to"]["index"] == 0

    def test_to_inventor_introduction_registers_name(self):
        """'Patent No. X to Kwok' introduces the name with zero network."""
        cites = _resolved(
            "U.S. Patent No. 8,453,642 to Kwok discloses a mask. "
            "The Kwok patent requires a vent."
        )

        assert cites[1]["resolved_to"]["index"] == 0

    def test_to_corporate_assignee_does_not_register_nickname(self):
        """'Patent No. X to Sony Corporation' should NOT register a nickname
        because 'Sony' is followed by a corporate marker (Corporation, Inc, etc).
        This ensures 'the Sony patent' remains unresolved."""
        cites = _resolved(
            "U.S. Patent No. 8,453,642 to Sony Corporation discloses a mask. "
            "The Sony patent requires a vent."
        )

        # The long form should NOT have a nickname set
        assert cites[0]["nickname"] is None
        # The short form "the Sony patent" should not resolve (no inventor intro)
        assert cites[1]["citation_type"] == "patent_short"
        assert cites[1]["resolved_to"] is None

    def test_to_corporate_assignee_with_comma_does_not_register_nickname(self):
        """'Patent No. X to Apple, Inc.' should NOT register a nickname.
        The comma immediately after the name is a corporate-name signal.
        This ensures 'the Apple patent' remains unresolved."""
        cites = _resolved(
            "U.S. Patent No. 8,453,642 to Apple, Inc. discloses a mask. "
            "The Apple patent requires a vent."
        )

        # The long form should NOT have a nickname set
        assert cites[0]["nickname"] is None
        # The short form should not resolve
        assert cites[1]["citation_type"] == "patent_short"
        assert cites[1]["resolved_to"] is None

    def test_to_corporate_assignee_multiword_does_not_register_nickname(self):
        """'Patent No. X to Sony Electronics Inc.' should NOT register a nickname.
        Multi-word company names (Sony Electronics) followed by a corporate marker.
        This ensures 'the Sony patent' remains unresolved."""
        cites = _resolved(
            "U.S. Patent No. 8,453,642 to Sony Electronics Inc. discloses a mask. "
            "The Sony patent requires a vent."
        )

        # The long form should NOT have a nickname set
        assert cites[0]["nickname"] is None
        # The short form should not resolve
        assert cites[1]["citation_type"] == "patent_short"
        assert cites[1]["resolved_to"] is None

    def test_to_single_word_inventor_does_register_nickname(self):
        """'Patent No. X to Kwok' (single word, no corporate marker) DOES
        register a nickname so 'the Kwok patent' can resolve."""
        cites = _cites(
            "U.S. Patent No. 8,453,642 to Kwok discloses a mask. "
            "The Kwok patent requires a vent."
        )

        # The long form SHOULD have a nickname from the "to Kwok" intro
        assert cites[0]["nickname"] == "the Kwok patent"

    def test_unintroduced_inventor_name_needs_metadata(self):
        """A name never introduced in text → unresolved + needs_metadata."""
        cites = _resolved(
            "U.S. Patent No. 8,453,642 is asserted. "
            "The Kwok patent requires a vent."
        )

        short = cites[1]
        assert short["resolved_to"] is None
        assert "unresolved_short_form" in short["flags"]
        assert "needs_metadata" in short["flags"]


class TestStandaloneClaimResolution:
    """Standalone patent_claim entries resolve to the nearest preceding patent."""

    def test_claim_resolves_to_nearest_preceding(self):
        cites = _resolved(
            "U.S. Patent No. 8,453,642 is asserted. Claim 9 recites a vent."
        )

        claim = cites[1]
        assert claim["citation_type"] == "patent_claim"
        assert claim["resolved_to"]["index"] == 0

    def test_claim_with_no_preceding_patent_is_unresolved(self):
        cites = _resolved("Claim 9 recites a vent.")

        claim = cites[0]
        assert claim["resolved_to"] is None
        assert "unresolved_short_form" in claim["flags"]

    def test_claim_picks_most_recent_of_two(self):
        cites = _resolved(
            "U.S. Patent No. 8,453,642 is asserted. "
            "U.S. Patent No. 9,154,231 is also asserted. Claim 9 is infringed."
        )

        assert cites[2]["resolved_to"]["index"] == 1


class TestResolutionViaCli:
    """main() runs resolution after extraction."""

    def test_cli_output_includes_resolution(self, capsys, monkeypatch):
        import io
        import json
        from patent_eyecite import main

        monkeypatch.setattr("sys.stdin", io.StringIO(
            "U.S. Patent No. 8,453,642 is asserted. The '642 patent controls."
        ))
        main([])

        out = json.loads(capsys.readouterr().out)
        assert out[1]["resolved_to"]["index"] == 0


class TestApplyInventorMetadata:
    """Pure re-resolution of needs_metadata short forms from inventor names."""

    def _needs_metadata_cites(self) -> list[dict]:
        return _resolved(
            "U.S. Patent No. 8,453,642 is asserted. "
            "The Kwok patent requires a vent."
        )

    def test_metadata_resolves_inventor_short_form(self):
        """First-named-inventor surname match resolves and clears flags."""
        from patent_eyecite import apply_inventor_metadata

        cites = self._needs_metadata_cites()
        apply_inventor_metadata(
            cites, {"8453642": ["Philip Rodney Kwok", "Ron Richard"]}
        )

        short = cites[1]
        assert short["resolved_to"] == {
            "index": 0, "full_citation": cites[0]["full_citation"],
        }
        assert "unresolved_short_form" not in short["flags"]
        assert "needs_metadata" not in short["flags"]

    def test_surname_match_is_case_insensitive(self):
        from patent_eyecite import apply_inventor_metadata

        cites = self._needs_metadata_cites()
        apply_inventor_metadata(cites, {"8453642": ["philip rodney KWOK"]})

        assert cites[1]["resolved_to"] is not None

    def test_non_matching_metadata_stays_flagged(self):
        """No surname match → flags stay; nothing resolved."""
        from patent_eyecite import apply_inventor_metadata

        cites = self._needs_metadata_cites()
        apply_inventor_metadata(cites, {"8453642": ["Jane Doe"]})

        assert cites[1]["resolved_to"] is None
        assert "needs_metadata" in cites[1]["flags"]

    def test_two_patents_same_surname_stays_ambiguous(self):
        """Two distinct patents with the same surname → still unresolved,
        both listed as candidates."""
        from patent_eyecite import apply_inventor_metadata

        cites = _resolved(
            "U.S. Patent No. 8,453,642 and U.S. Patent No. 9,154,231 are asserted. "
            "The Kwok patent requires a vent."
        )
        apply_inventor_metadata(cites, {
            "8453642": ["Philip Rodney Kwok"],
            "9154231": ["Alice Kwok"],
        })

        short = cites[2]
        assert short["resolved_to"] is None
        assert "unresolved_short_form" in short["flags"]
        assert short["candidates"] == [0, 1]


class TestResolveMetadataCli:
    """--resolve-metadata wiring and the no-network default guarantee."""

    def test_default_run_makes_no_network_calls(self, capsys, monkeypatch):
        """Flagless main() never opens a socket: urlopen is booby-trapped."""
        import io
        import urllib.request
        from patent_eyecite import main

        def _boom(*args, **kwargs):
            raise AssertionError("network call attempted in default run")

        monkeypatch.setattr(urllib.request, "urlopen", _boom)
        monkeypatch.setattr("sys.stdin", io.StringIO(
            "U.S. Patent No. 8,453,642 is asserted. The Kwok patent controls."
        ))

        assert main([]) == 0

    def test_resolve_metadata_flag_resolves_via_fixture(
        self, capsys, monkeypatch, tmp_path
    ):
        """--resolve-metadata resolves an unintroduced inventor name using a
        pre-seeded HTML cache (no live network)."""
        import io
        import json
        from pathlib import Path
        import patent_fetch
        from patent_eyecite import main

        fixture = (
            Path(__file__).resolve().parent.parent
            / "test_fixtures" / "google_patent_page.html"
        )
        cached = patent_fetch.page_cache_path(tmp_path, "US8453642")
        cached.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

        monkeypatch.setattr("sys.stdin", io.StringIO(
            "U.S. Patent No. 8,453,642 is asserted. The Kwok patent controls."
        ))
        result = main(["--resolve-metadata", "--cache-dir", str(tmp_path)])

        assert result == 0
        out = json.loads(capsys.readouterr().out)
        assert out[1]["resolved_to"]["index"] == 0
        assert "needs_metadata" not in out[1]["flags"]

    def test_non_us_citations_excluded_from_fetch_batch(
        self, capsys, monkeypatch, tmp_path
    ):
        """Non-US citations are excluded from metadata fetch.
        When both US and non-US patents appear, only US patents are batched."""
        import io
        import json
        from unittest.mock import patch
        from patent_eyecite import main

        # Input with EP (non-US), US (valid), and need-metadata short form
        monkeypatch.setattr("sys.stdin", io.StringIO(
            "EP1234567 and U.S. Patent No. 8,453,642 are asserted. "
            "The Kwok patent requires improvements."
        ))

        with patch("patent_fetch.fetch_patent_metadata_batch") as mock_fetch:
            mock_fetch.return_value = {}
            result = main(["--resolve-metadata", "--cache-dir", str(tmp_path)])

        assert result == 0
        # Verify fetch_patent_metadata_batch was called with only the US patent
        # (EP1234567 must be excluded due to kind guard)
        mock_fetch.assert_called_once()
        call_args = mock_fetch.call_args[0]
        assert len(call_args[0]) == 1
        assert call_args[0][0] == "US8453642"  # Only US patent in batch
