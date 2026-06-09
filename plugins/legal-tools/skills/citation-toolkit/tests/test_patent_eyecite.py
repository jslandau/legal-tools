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
