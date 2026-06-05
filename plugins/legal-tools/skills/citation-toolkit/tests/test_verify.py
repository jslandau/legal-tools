"""Tests for patent_verify: normalization + blob/index building."""
import pytest

from patent_verify import normalize_line, rejoin_hyphen_splits, build_blob_and_index


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


class TestBuildBlobAndIndex:
    """Tests for AC1.4, AC2.1, AC2.2: blob building and index creation."""

    def test_ac1_4_filters_non_text_kinds(self):
        """Only 'text' kind lines are included; blank/spurious/unknown omitted."""
        lines = [
            {"column": 1, "line": 1, "text": "hello", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "blank"},
            {"column": 1, "line": 3, "text": "world", "bbox": (0, 40, 10, 50), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # Only "hello" and "world" included
        assert "blank" not in blob
        assert blob == "hello world"
        assert len(index) == 2

    def test_ac2_1_no_newlines_in_blob(self):
        """Blob contains no newline characters."""
        lines = [
            {"column": 1, "line": 1, "text": "line one", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "line two", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        assert "\n" not in blob

    def test_ac2_2_characters_preserved_in_order(self):
        """Every character is preserved in the blob (modulo normalization)."""
        lines = [
            {"column": 1, "line": 1, "text": "abc def", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "ghi jkl", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # Characters in order (spaces collapse, no newlines, join with single space)
        assert blob == "abc def ghi jkl"

    def test_index_one_entry_per_text_line(self):
        """Index has one entry per text line."""
        lines = [
            {"column": 1, "line": 1, "text": "first", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 2, "line": 1, "text": "second", "bbox": (20, 0, 30, 10), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        assert len(index) == 2
        # Check that each entry is (char_offset, column, line)
        assert all(len(entry) == 3 for entry in index)

    def test_index_offsets_strictly_ascending(self):
        """Index offsets are strictly ascending."""
        lines = [
            {"column": 1, "line": 1, "text": "hello", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "world", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        offsets = [entry[0] for entry in index]
        # First line starts at 0: "hello" (5 chars) + space (1) = 6
        # Second line starts at 6: "world"
        assert offsets == [0, 6]
        # Verify strictly ascending
        for i in range(1, len(offsets)):
            assert offsets[i] > offsets[i - 1]

    def test_index_column_and_line_preserved(self):
        """Index entries preserve column and line numbers from input."""
        lines = [
            {"column": 5, "line": 10, "text": "hello", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 5, "line": 11, "text": "world", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        assert index[0] == (0, 5, 10)
        assert index[1] == (6, 5, 11)

    def test_hyphen_split_rejoined_in_blob(self):
        """Hyphen-split words are rejoined in the blob."""
        lines = [
            {"column": 1, "line": 1, "text": "com-", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "prises a widget", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # After rejoin: "comprises" and "a widget"
        assert blob == "comprises a widget"
        assert len(index) == 2
        # First line offset is 0: "comprises" (9 chars) + space (1) = 10
        # Second line offset is 10: "a widget"
        assert index[0][0] == 0
        assert index[1][0] == 10

    def test_empty_input_list(self):
        """Empty input list produces empty blob and empty index."""
        blob, index = build_blob_and_index([])
        assert blob == ""
        assert index == []

    def test_whitespace_collapsed_in_lines(self):
        """Multiple spaces within a line collapse to single space."""
        lines = [
            {"column": 1, "line": 1, "text": "hello    world", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # Normalized: "hello world"
        assert blob == "hello world"

    def test_only_blank_and_spurious_lines(self):
        """If all lines are blank/spurious/unknown, blob is empty."""
        lines = [
            {"column": 1, "line": 1, "text": "", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "blank"},
            {"column": 1, "line": 2, "text": "", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "spurious"},
        ]
        blob, index = build_blob_and_index(lines)
        assert blob == ""
        assert index == []
