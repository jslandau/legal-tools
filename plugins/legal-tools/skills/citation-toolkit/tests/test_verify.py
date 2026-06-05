"""Tests for patent_verify: normalization + blob/index building."""
import pytest

from patent_verify import normalize_line


class TestNormalizeLine:
    """Tests for AC1.1: normalize whitespace within lines."""

    def test_collapses_multiple_spaces_to_single(self):
        """Multiple spaces become one."""
        result = normalize_line("foo   bar")
        assert result == "foo bar"

    def test_collapses_mixed_whitespace(self):
        """Tabs and spaces all collapse to single space."""
        result = normalize_line("foo   bar\tbaz")
        assert result == "foo bar baz"

    def test_strips_leading_whitespace(self):
        """Leading whitespace is removed."""
        result = normalize_line("   foo bar")
        assert result == "foo bar"

    def test_strips_trailing_whitespace(self):
        """Trailing whitespace is removed."""
        result = normalize_line("foo bar   ")
        assert result == "foo bar"

    def test_strips_both_ends(self):
        """Leading and trailing whitespace both stripped."""
        result = normalize_line("   foo bar   ")
        assert result == "foo bar"

    def test_already_normalized_unchanged(self):
        """Already-clean text is unchanged."""
        result = normalize_line("foo bar")
        assert result == "foo bar"

    def test_empty_string(self):
        """Empty string remains empty."""
        result = normalize_line("")
        assert result == ""

    def test_only_whitespace(self):
        """Whitespace-only string becomes empty."""
        result = normalize_line("   \t  ")
        assert result == ""
