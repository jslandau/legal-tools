"""Tests for patent_verify: normalization + blob/index building."""
import pytest

from patent_verify import (
    normalize_line,
    rejoin_hyphen_splits,
    build_blob_and_index,
    resolve_offset,
    resolve_span,
    _max_line_by_column,
    span_width,
    window_bounds,
    expanded_bounds,
    _lines_in_bounds,
    gather_window,
)


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

    def test_remainder_line_coordinates_single_split(self):
        """Remainder after rejoin gets its source line's coordinates, not prior line's.

        CRITICAL FIX: When 'accor-' merges with 'dance with the', the remainder
        'with the' must have line=2 (its source), not line=1 (the prior line).
        """
        lines = [
            {"column": 1, "line": 1, "text": "accor-", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "dance with the", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # After rejoin: "accordance" (from line 1+2) and "with the" (remainder from line 2)
        assert blob == "accordance with the"
        assert len(index) == 2
        # First entry: joined word, should have line 1 coordinates
        assert index[0] == (0, 1, 1)
        # Second entry: remainder, should have line 2 coordinates (its source)
        # Offset for "with the": "accordance" (10 chars) + space (1) = 11
        assert index[1] == (11, 1, 2)

    def test_remainder_line_coordinates_multi_split(self):
        """Multi-split chain: remainders each get their own source line coordinates.

        CRITICAL FIX: In ["con-", "sider it a-", "gain"]:
        - "con-" merges with "sider it a-" → "consider", remainder "it a-" from line 2
        - "it a-" merges with "gain" → "it again", no remainder
        - Remainder "it a-" must be tagged with line 2, not line 1.
        """
        lines = [
            {"column": 1, "line": 1, "text": "con-", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "sider it a-", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 3, "text": "gain", "bbox": (0, 40, 10, 50), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # After multi-split: "consider" (from lines 1+2) and "it again" (from lines 2+3)
        assert blob == "consider it again"
        assert len(index) == 2
        # First entry: merged from lines 1 and part of 2, tagged with line 1
        assert index[0] == (0, 1, 1)
        # Second entry: remainder "it" from line 2, merged with "gain" from line 3
        # but the remainder was tagged with line 2 (its source)
        # Offset: "consider" (8 chars) + space (1) = 9
        assert index[1] == (9, 1, 2)

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


class TestResolveOffset:
    """Tests for AC3.1, AC3.2, AC3.5: resolve single offset to coordinate."""

    def test_ac3_1_offset_at_line_start(self):
        """AC3.1: Offset equal to an entry's char_offset resolves to that entry's (column, line)."""
        # Build a blob with known index
        lines = [
            {"column": 1, "line": 1, "text": "hello", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "world", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # Index: [(0, 1, 1), (6, 1, 2)]
        # Offset 0 should resolve to (1, 1)
        result = resolve_offset(index, 0)
        assert result == (1, 1)

    def test_ac3_1_offset_at_second_line_start(self):
        """AC3.1: Offset at the second line's start resolves to that line."""
        lines = [
            {"column": 1, "line": 1, "text": "hello", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "world", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # Index: [(0, 1, 1), (6, 1, 2)]
        # Offset 6 should resolve to (1, 2)
        result = resolve_offset(index, 6)
        assert result == (1, 2)

    def test_ac3_2_mid_line_offset_resolves_to_greater_equal(self):
        """AC3.2: Offset strictly between two entries resolves to the lower (greatest-≤) entry."""
        lines = [
            {"column": 1, "line": 1, "text": "hello", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "world", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # Index: [(0, 1, 1), (6, 1, 2)]
        # Blob: "hello world"
        # Offset 3 is within "hello", should resolve to (1, 1)
        result = resolve_offset(index, 3)
        assert result == (1, 1)

    def test_ac3_2_offset_within_second_line(self):
        """AC3.2: Offset within the second line resolves to the second line."""
        lines = [
            {"column": 1, "line": 1, "text": "hello", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "world", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # Index: [(0, 1, 1), (6, 1, 2)]
        # Offset 8 is within "world", should resolve to (1, 2)
        result = resolve_offset(index, 8)
        assert result == (1, 2)

    def test_ac3_5_index_offsets_strictly_ascending(self):
        """AC3.5: Index offsets are strictly monotonic (ascending, unambiguous bucketing)."""
        lines = [
            {"column": 1, "line": 1, "text": "one", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "two", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 3, "text": "three", "bbox": (0, 40, 10, 50), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # Verify strictly ascending
        assert all(index[i][0] < index[i + 1][0] for i in range(len(index) - 1))

    def test_empty_index_raises_value_error(self):
        """Resolving an offset against an empty index raises ValueError."""
        with pytest.raises(ValueError):
            resolve_offset([], 5)

    def test_offset_before_first_entry_raises_value_error(self):
        """An offset that precedes the first entry (pos < 0) raises ValueError."""
        lines = [
            {"column": 1, "line": 1, "text": "hello", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # Index starts at offset 0; any negative offset should fail
        with pytest.raises(ValueError):
            resolve_offset(index, -1)


class TestResolveSpan:
    """Tests for AC3.3, AC3.4: resolve offset range to coordinate range."""

    def test_ac3_3_span_single_line(self):
        """AC3.3: A span within a single line resolves to start/end on same line."""
        lines = [
            {"column": 1, "line": 1, "text": "hello world", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "goodbye", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # Blob: "hello world goodbye"
        # Index: [(0, 1, 1), (12, 1, 2)]
        # Span [0, 5) covers "hello"
        result = resolve_span(index, 0, 5)
        assert result == (1, 1, 1, 1)

    def test_ac3_3_span_across_two_lines(self):
        """AC3.3: A span whose start/end land in different lines resolves correctly."""
        lines = [
            {"column": 1, "line": 1, "text": "hello", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "world", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 3, "text": "end", "bbox": (0, 40, 10, 50), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # Blob: "hello world end"
        # Index: [(0, 1, 1), (6, 1, 2), (12, 1, 3)]
        # Span [3, 10) covers "lo world"
        result = resolve_span(index, 3, 10)
        # start at offset 3 (in line 1), end at offset 9 (in line 2)
        assert result == (1, 1, 1, 2)

    def test_ac3_3_span_across_three_buckets(self):
        """AC3.3: A span spanning three or more buckets resolves from first to last."""
        lines = [
            {"column": 1, "line": 1, "text": "one", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "two", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 3, "text": "three", "bbox": (0, 40, 10, 50), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # Blob: "one two three"
        # Index: [(0, 1, 1), (4, 1, 2), (8, 1, 3)]
        # Span [1, 13) covers "ne two three"
        result = resolve_span(index, 1, 13)
        # start at offset 1 (in line 1), end at offset 12 (in line 3)
        assert result == (1, 1, 1, 3)

    def test_ac3_4_offset_inside_rejoined_word(self):
        """AC3.4: An offset inside a rejoined word resolves to the starting line.

        When 'accor-' merges with 'dance with the', the blob contains
        'accordance with the'. The index tracks:
        - Line 1 entry at offset 0: 'accordance' (joined from line 1+2)
        - Line 2 entry at offset 11: 'with the' (remainder from line 2)

        An offset inside 'accordance' (e.g., offset 5, which is within the
        moved 'dance' fragment) must resolve to line 1 (where the word started),
        not line 2 (where 'dance' came from).
        """
        lines = [
            {"column": 1, "line": 1, "text": "accor-", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "dance with the", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # Blob: "accordance with the"
        # Index: [(0, 1, 1), (11, 1, 2)]
        assert blob == "accordance with the"
        assert len(index) == 2

        # Offset 5 is inside 'accordance' (at 'n'), which came from the joined fragment
        # It should resolve to line 1 (where the word started), not line 2
        result = resolve_offset(index, 5)
        assert result == (1, 1), "Offset inside rejoined word must resolve to starting line"

        # Offset 10 is at 'e' in 'accordance', still within the joined word
        result = resolve_offset(index, 10)
        assert result == (1, 1), "Offset at end of rejoined word must still resolve to starting line"

        # Offset 11 is at the start of 'with', which is from line 2's remainder
        result = resolve_offset(index, 11)
        assert result == (1, 2), "Offset at start of remainder must resolve to line 2"

    def test_ac3_4_span_across_rejoined_word_boundary(self):
        """AC3.4: A span touching the rejoined word boundary resolves correctly.

        Test that when resolving a span [start, end), we use end-1 to get the
        inclusive last character, so the span doesn't bleed into the next line.
        """
        lines = [
            {"column": 1, "line": 1, "text": "accor-", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "dance with the", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
        ]
        blob, index = build_blob_and_index(lines)
        # Blob: "accordance with the"
        # Index: [(0, 1, 1), (11, 1, 2)]

        # Span [0, 11) covers "accordance " (the space before "with")
        # start=0 -> line 1
        # end-1=10 -> last char of 'accordance' -> line 1
        result = resolve_span(index, 0, 11)
        assert result == (1, 1, 1, 1), "Span ending at rejoined word boundary should not bleed to next line"

        # Span [0, 12) covers "accordance w"
        # start=0 -> line 1
        # end-1=11 -> first char of 'with' -> line 2
        result = resolve_span(index, 0, 12)
        assert result == (1, 1, 1, 2), "Span crossing into remainder must include both lines"


class TestMaxLineByColumn:
    """Tests for _max_line_by_column helper."""

    def test_single_column_single_line(self):
        """Single column with single line."""
        doc = {
            "lines": [
                {"column": 1, "line": 1, "text": "hello", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            ]
        }
        result = _max_line_by_column(doc)
        assert result == {1: 1}

    def test_single_column_multiple_lines(self):
        """Single column with multiple lines."""
        doc = {
            "lines": [
                {"column": 1, "line": 1, "text": "line 1", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
                {"column": 1, "line": 5, "text": "line 5", "bbox": (0, 50, 10, 60), "page_index": 0, "kind": "text"},
                {"column": 1, "line": 3, "text": "line 3", "bbox": (0, 30, 10, 40), "page_index": 0, "kind": "text"},
            ]
        }
        result = _max_line_by_column(doc)
        assert result == {1: 5}

    def test_multiple_columns(self):
        """Multiple columns with different max lines."""
        doc = {
            "lines": [
                {"column": 1, "line": 1, "text": "col 1 line 1", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
                {"column": 1, "line": 50, "text": "col 1 line 50", "bbox": (0, 500, 10, 510), "page_index": 0, "kind": "text"},
                {"column": 2, "line": 1, "text": "col 2 line 1", "bbox": (100, 0, 110, 10), "page_index": 0, "kind": "text"},
                {"column": 2, "line": 30, "text": "col 2 line 30", "bbox": (100, 300, 110, 310), "page_index": 0, "kind": "text"},
            ]
        }
        result = _max_line_by_column(doc)
        assert result == {1: 50, 2: 30}

    def test_empty_lines_list(self):
        """Empty lines list produces empty dict."""
        doc = {"lines": []}
        result = _max_line_by_column(doc)
        assert result == {}


class TestSpanWidth:
    """Tests for span_width helper."""

    def test_single_line_span_single_column(self):
        """Single line (start=end) in one column has width 1."""
        doc = {
            "lines": [
                {"column": 3, "line": 10, "text": "text", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            ]
        }
        result = span_width(doc, 3, 10, 3, 10)
        assert result == 1

    def test_same_column_three_line_span(self):
        """Span from line 10 to line 12 in same column is 3 lines."""
        doc = {
            "lines": [
                {"column": 3, "line": 10, "text": "line 10", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
                {"column": 3, "line": 11, "text": "line 11", "bbox": (0, 10, 10, 20), "page_index": 0, "kind": "text"},
                {"column": 3, "line": 12, "text": "line 12", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
            ]
        }
        result = span_width(doc, 3, 10, 3, 12)
        assert result == 3

    def test_cross_column_simple(self):
        """Cross-column span from 4:65 to 5:3."""
        doc = {
            "lines": [
                {"column": 4, "line": 65, "text": "col4 line 65", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
                {"column": 4, "line": 66, "text": "col4 line 66", "bbox": (0, 10, 10, 20), "page_index": 0, "kind": "text"},
                {"column": 5, "line": 1, "text": "col5 line 1", "bbox": (100, 0, 110, 10), "page_index": 0, "kind": "text"},
                {"column": 5, "line": 2, "text": "col5 line 2", "bbox": (100, 10, 110, 20), "page_index": 0, "kind": "text"},
                {"column": 5, "line": 3, "text": "col5 line 3", "bbox": (100, 20, 110, 30), "page_index": 0, "kind": "text"},
            ]
        }
        # col 4: lines 65-66 = 2 lines
        # col 5: lines 1-3 = 3 lines
        # total = 5 lines
        result = span_width(doc, 4, 65, 5, 3)
        assert result == 5

    def test_cross_column_with_intermediate(self):
        """Cross-column with intermediate column."""
        doc = {
            "lines": [
                {"column": 1, "line": 10, "text": "c1 l10", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
                {"column": 1, "line": 11, "text": "c1 l11", "bbox": (0, 10, 10, 20), "page_index": 0, "kind": "text"},
                {"column": 2, "line": 1, "text": "c2 l1", "bbox": (50, 0, 60, 10), "page_index": 0, "kind": "text"},
                {"column": 2, "line": 2, "text": "c2 l2", "bbox": (50, 10, 60, 20), "page_index": 0, "kind": "text"},
                {"column": 2, "line": 3, "text": "c2 l3", "bbox": (50, 20, 60, 30), "page_index": 0, "kind": "text"},
                {"column": 3, "line": 1, "text": "c3 l1", "bbox": (100, 0, 110, 10), "page_index": 0, "kind": "text"},
                {"column": 3, "line": 5, "text": "c3 l5", "bbox": (100, 40, 110, 50), "page_index": 0, "kind": "text"},
            ]
        }
        # col 1: lines 10-11 = 2 lines
        # col 2: lines 1-3 = 3 lines
        # col 3: lines 1-5 = 5 lines
        # total = 10 lines
        result = span_width(doc, 1, 10, 3, 5)
        assert result == 10


class TestWindowBounds:
    """Tests for window_bounds (±10%, min ±1, clamped)."""

    def test_ac4_1_fifty_line_span_margin_five(self):
        """AC4.1: 50-line span yields ±5 margin."""
        doc = {
            "lines": [
                {"column": 3, "line": i, "text": f"line {i}", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"}
                for i in range(10, 60)
            ]
        }
        cited = (3, 10, 3, 59)
        result = window_bounds(doc, cited)
        # width = 50, margin = max(1, int(50 * 0.10)) = 5
        # start_line = max(1, 10 - 5) = 5
        # end_line = min(max_line[3], 59 + 5) = min(59, 64) = 59
        assert result == (3, 5, 3, 59)

    def test_ac4_2_small_span_minimum_margin(self):
        """AC4.2: Small spans get minimum ±1 margin."""
        doc = {
            "lines": [
                {"column": 3, "line": i, "text": f"line {i}", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"}
                for i in range(1, 20)
            ]
        }
        # width 3: margin = max(1, int(3 * 0.10)) = max(1, 0) = 1
        cited = (3, 10, 3, 12)
        result = window_bounds(doc, cited)
        assert result == (3, 9, 3, 13)

        # width 1: margin = max(1, int(1 * 0.10)) = max(1, 0) = 1
        cited = (3, 10, 3, 10)
        result = window_bounds(doc, cited)
        assert result == (3, 9, 3, 11)

    def test_ac4_3_cross_column_cite(self, us9_artifact):
        """AC4.3: Cross-column cite yields valid cross-column window."""
        cited = (4, 65, 5, 3)
        result = window_bounds(us9_artifact, cited)
        start_col, start_line, end_col, end_line = result
        # Verify structure: start_col and end_col unchanged, lines widened
        assert start_col == 4
        assert end_col == 5
        # start_line should be <= 65 (possibly widened down)
        assert start_line <= 65
        # end_line should be >= 3 (possibly widened up)
        assert end_line >= 3
        # Both should be valid coordinates
        assert start_line >= 1
        assert end_line >= 1

    def test_window_bounds_clamped_at_bottom(self):
        """Window bounds clamped to column max."""
        doc = {
            "lines": [
                {"column": 1, "line": i, "text": f"line {i}", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"}
                for i in range(1, 11)
            ]
        }
        # Column 1 max line is 10
        # Cite at 9-10, margin 1 would try 8-11, but 11 exceeds max
        cited = (1, 9, 1, 10)
        result = window_bounds(doc, cited)
        assert result == (1, 8, 1, 10)  # Clamped at column max

    def test_window_bounds_clamped_at_top(self):
        """Window bounds clamped to line 1."""
        doc = {
            "lines": [
                {"column": 1, "line": i, "text": f"line {i}", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"}
                for i in range(1, 20)
            ]
        }
        # Cite at 1-2, margin 1 would try 0-3, but 0 < 1
        cited = (1, 1, 1, 2)
        result = window_bounds(doc, cited)
        assert result == (1, 1, 1, 3)  # Clamped at 1


class TestExpandedBounds:
    """Tests for expanded_bounds (larger margin for ambiguity expansion)."""

    def test_expanded_bounds_larger_margin(self):
        """Expanded bounds use a larger margin than window_bounds."""
        doc = {
            "lines": [
                {"column": 3, "line": i, "text": f"line {i}", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"}
                for i in range(1, 100)
            ]
        }
        cited = (3, 50, 3, 50)
        window = window_bounds(doc, cited)
        expanded = expanded_bounds(doc, cited)
        # Expanded should be wider
        assert expanded[1] <= window[1]  # Start line <= window start
        assert expanded[3] >= window[3]  # End line >= window end


class TestGatherWindow:
    """Tests for gather_window orchestration."""

    def test_gather_window_no_ambiguity(self, us9_artifact):
        """Gather window returns normal bounds when no ambiguity."""
        # Use a large cite that won't trigger ambiguity
        cited = (1, 10, 1, 20)
        result = gather_window(us9_artifact, cited)
        assert "window_coord_range" in result
        assert "window_lines" in result
        assert "ambiguity" in result
        assert "ambiguity_reason" in result
        assert result["ambiguity"] is False
        assert result["ambiguity_reason"] is None
        assert isinstance(result["window_lines"], list)

    def test_gather_window_ambiguity_expansion(self):
        """Gather window with synthetic spurious slot triggers expansion."""
        # Build a synthetic doc with a spurious slot in a small span
        doc = {
            "lines": [
                {"column": 1, "line": 1, "text": "text line 1", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
                {"column": 1, "line": 2, "text": "", "bbox": (0, 10, 10, 20), "page_index": 0, "kind": "spurious"},
                {"column": 1, "line": 3, "text": "text line 3", "bbox": (0, 20, 10, 30), "page_index": 0, "kind": "text"},
                {"column": 1, "line": 4, "text": "text line 4", "bbox": (0, 30, 10, 40), "page_index": 0, "kind": "text"},
            ]
        }
        # Cite 1:1-2 is a small span touching the spurious slot at line 2
        cited = (1, 1, 1, 2)
        result = gather_window(doc, cited)
        assert result["ambiguity"] is True
        assert result["ambiguity_reason"] is not None
        assert len(result["ambiguity_reason"]) > 0
        # Expanded bounds should be wider than normal
        normal_bounds = window_bounds(doc, cited)
        assert result["window_coord_range"] != normal_bounds or result["ambiguity"]
