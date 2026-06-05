"""Tests for patent_verify: normalization + blob/index building."""
import pytest

from patent_verify import normalize_line, rejoin_hyphen_splits


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


class TestRejoinHyphenSplits:
    """Tests for AC1.2, AC1.3: rejoin line-break hyphens intelligently."""

    def test_ac1_2_lowercase_next_line_rejoins(self):
        """A hyphen followed by lowercase on next line is a split word."""
        lines = ["com-", "prises a widget"]
        result = rejoin_hyphen_splits(lines)
        # "com-" + "prises" = "comprises", next line's remainder is "a widget"
        assert result == ["comprises", "a widget"]

    def test_ac1_3_capitalized_next_line_does_not_rejoin(self):
        """A hyphen followed by uppercase is NOT a split word."""
        lines = ["United-", "States law"]
        result = rejoin_hyphen_splits(lines)
        # Not rejoined; lines unchanged
        assert result == ["United-", "States law"]

    def test_ac1_3_mid_line_hyphen_untouched(self):
        """Hyphens not at line end are never touched (e.g., real-time)."""
        lines = ["a real-time clock"]
        result = rejoin_hyphen_splits(lines)
        # Single line, not modified
        assert result == ["a real-time clock"]

    def test_empty_remainder_dropped(self):
        """If the entire next line is the moved word, no empty remainder entry."""
        lines = ["accor-", "dance"]
        result = rejoin_hyphen_splits(lines)
        # "accor-" + "dance" = "accordance", but "dance" is the whole next line
        # so there's no remainder. Result is just one entry.
        assert result == ["accordance"]

    def test_remainder_after_moved_word(self):
        """Remainder after the moved word becomes next line's entry."""
        lines = ["accor-", "dance with the"]
        result = rejoin_hyphen_splits(lines)
        # "accor-" + "dance" = "accordance", remainder "with the"
        assert result == ["accordance", "with the"]

    def test_no_next_line_preserves_hyphen(self):
        """A trailing hyphen with no next line is preserved."""
        lines = ["some-"]
        result = rejoin_hyphen_splits(lines)
        assert result == ["some-"]

    def test_multiple_splits_in_sequence(self):
        """Multiple hyphen splits are processed via remainder chaining."""
        lines = ["con-", "sider it a-", "gain"]
        result = rejoin_hyphen_splits(lines)
        # Step 1: "con-" + first_word("sider it a-") = "consider", remainder "it a-"
        # Step 2: remainder "it a-" + first_word("gain") = "it again", no remainder
        # Result: ["consider", "it again"]
        assert result == ["consider", "it again"]

    def test_digit_after_hyphen_no_rejoin(self):
        """Hyphen followed by digit is NOT a split."""
        lines = ["foo-", "42 bar"]
        result = rejoin_hyphen_splits(lines)
        assert result == ["foo-", "42 bar"]

    def test_punctuation_after_hyphen_no_rejoin(self):
        """Hyphen followed by punctuation is NOT a split."""
        lines = ["foo-", "...bar"]
        result = rejoin_hyphen_splits(lines)
        assert result == ["foo-", "...bar"]

    def test_empty_list(self):
        """Empty input list returns empty."""
        result = rejoin_hyphen_splits([])
        assert result == []

    def test_single_line_no_hyphen(self):
        """Single line without hyphen is unchanged."""
        result = rejoin_hyphen_splits(["hello world"])
        assert result == ["hello world"]
