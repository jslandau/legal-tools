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
