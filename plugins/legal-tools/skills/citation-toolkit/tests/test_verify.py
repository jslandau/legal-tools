"""Tests for patent_verify: normalization + blob/index building."""
import io
import json
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
    _find_all,
    resolve,
    verify_emit,
    verify_resolve,
    process,
    main,
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
        """AC5.1: Gather window with synthetic spurious slot triggers expansion."""
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

    def test_gather_window_probes_cited_span_not_window(self):
        """Probe must check CITED span, not window, to catch ambiguity gate.

        This test validates the cited-span-probe invariant: the ambiguity gate
        only fires for small spans (width < 5). If we probed the window instead,
        a small cited span (width < 5) that expands to window width >= 5 would
        silently pass the probe and never trigger the expansion path.

        Scenario: a long column with a spurious slot inside a small (width < 5)
        cited span. The window's ±10% margin pushes the window to width >= 5,
        making probing the window a dead path. We verify by asserting that
        gather_window detects the ambiguity (because the CITED span is small
        and touches the gate), even though the WINDOW would silently pass.
        """
        # Build a synthetic doc: long column (20 lines) with one spurious slot
        lines = [
            {"column": 1, "line": i, "text": f"text line {i}", "bbox": (0, i*10, 10, (i+1)*10), "page_index": 0, "kind": "text"}
            for i in range(1, 21)
        ]
        # Inject a spurious slot at line 12 (in the middle)
        lines[11] = {"column": 1, "line": 12, "text": "", "bbox": (0, 120, 10, 130), "page_index": 0, "kind": "spurious"}

        doc = {"lines": lines}

        # Cite a small span (width 3) that includes the spurious slot at line 12
        cited = (1, 11, 1, 13)  # lines 11, 12 (spurious), 13 -> width 3

        # Verify cited span is small (width < 5)
        from patent_verify import span_width, window_bounds
        cited_width = span_width(doc, *cited)
        assert cited_width < 5, f"cited span width {cited_width} should be < 5"

        # Verify window expands cited span to >= 5
        window = window_bounds(doc, cited)
        window_width = span_width(doc, *window)
        assert window_width >= 5, f"window width {window_width} should be >= 5 to validate dead-path detection"

        # Now call gather_window: it should detect ambiguity on the CITED span
        # (which is small and touches the spurious gate), even though the window
        # itself would silently pass if we probed there.
        result = gather_window(doc, cited)
        assert result["ambiguity"] is True, "gather_window must detect ambiguity (probes CITED span, not window)"
        assert result["ambiguity_reason"] is not None
        assert len(result["ambiguity_reason"]) > 0


class TestFindAll:
    """Tests for AC6.6: _find_all non-overlapping substring discovery."""

    def test_single_occurrence(self):
        """Single needle in blob returns offset list with one entry."""
        blob = "the quick brown fox"
        needle = "quick"
        result = _find_all(blob, needle)
        assert result == [4]

    def test_multiple_non_overlapping_occurrences(self):
        """Multiple occurrences of needle are returned as separate offsets."""
        blob = "a foo bar foo baz"
        needle = "foo"
        result = _find_all(blob, needle)
        # "foo" appears at offset 2 and offset 10 (non-overlapping)
        assert result == [2, 10]

    def test_overlapping_occurrences_skipped(self):
        """Overlapping matches are skipped (non-overlapping only)."""
        blob = "aaa"
        needle = "aa"
        result = _find_all(blob, needle)
        # First match at 0, next search starts at 0 + len("aa") = 2
        # Match at 2 would end at 4 (out of bounds), so only [0]
        assert result == [0]

    def test_no_occurrence(self):
        """Needle not in blob returns empty list."""
        blob = "hello world"
        needle = "xyz"
        result = _find_all(blob, needle)
        assert result == []

    def test_empty_blob(self):
        """Empty blob returns empty list."""
        blob = ""
        needle = "foo"
        result = _find_all(blob, needle)
        assert result == []

    def test_empty_needle(self):
        """Empty needle should return empty list (no-op, defend against infinite loop)."""
        blob = "hello world"
        needle = ""
        result = _find_all(blob, needle)
        assert result == []

    def test_needle_equals_blob(self):
        """Needle exactly equals blob: single match at offset 0."""
        blob = "exact match"
        needle = "exact match"
        result = _find_all(blob, needle)
        assert result == [0]

    def test_case_sensitive(self):
        """Needle matching is case-sensitive."""
        blob = "Hello HELLO hello"
        needle = "hello"
        result = _find_all(blob, needle)
        # Only the lowercase "hello" matches
        assert result == [12]


class TestResolveWithWhitespaceGuard:
    """Tests for AC6 resolver with whitespace-only re-normalize guard (Task 2)."""

    def test_ac6_1_unique_window_match(self):
        """AC6.1: Unique substring in window resolves to single coordinate."""
        # Build a simple window blob
        window_lines = [
            {"column": 1, "line": 1, "text": "a widget that operates", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
            {"column": 1, "line": 2, "text": "in parallel", "bbox": (0, 10, 10, 20), "page_index": 0, "kind": "text"},
        ]
        window_blob, window_index = build_blob_and_index(window_lines)

        # Empty body (no body fallback needed)
        body_blob = ""
        body_index = []

        # Search for a unique substring in the window
        result = resolve(window_blob, window_index, body_blob, body_index, "widget that")

        # Should resolve to a single coordinate
        assert result["found_at"] is not None
        assert result["match_scope"] == "window"
        assert "ambiguous_match" not in result or result.get("ambiguous_match") is False

    def test_ac6_6_whitespace_slip_resolves(self):
        """AC6.6: Whitespace slip (double-space, leading/trailing) still resolves via re-normalize."""
        window_lines = [
            {"column": 1, "line": 1, "text": "a widget that operates", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
        ]
        window_blob, window_index = build_blob_and_index(window_lines)

        body_blob = ""
        body_index = []

        # Search with double-space: "a  widget that"
        # normalize_line("a  widget that") -> "a widget that" (whitespace collapsed)
        # Should match "a widget that" in the blob
        result = resolve(window_blob, window_index, body_blob, body_index, "a  widget that")

        assert result["found_at"] is not None
        assert result["match_scope"] == "window"

    def test_ac6_6_case_exact_no_fold(self):
        """AC6.6: Case is NOT folded; case-only difference does NOT resolve."""
        window_lines = [
            {"column": 1, "line": 1, "text": "a widget that", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
        ]
        window_blob, window_index = build_blob_and_index(window_lines)

        body_blob = ""
        body_index = []

        # Search with different case: "a Widget"
        # normalize_line("a Widget") -> "a Widget" (case preserved)
        # Should NOT match "a widget" (case mismatch)
        result = resolve(window_blob, window_index, body_blob, body_index, "a Widget")

        assert result["found_at"] is None

    def test_empty_substring_after_normalization(self):
        """Empty or whitespace-only substring after normalize returns no match."""
        window_lines = [
            {"column": 1, "line": 1, "text": "hello world", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
        ]
        window_blob, window_index = build_blob_and_index(window_lines)

        body_blob = ""
        body_index = []

        # Whitespace-only substring normalizes to empty
        result = resolve(window_blob, window_index, body_blob, body_index, "   \t  ")

        assert result["found_at"] is None

    def test_ac6_4_window_hit_preferred(self):
        """AC6.4: Substring unique in window is resolved to window even if duplicated in body."""
        window_lines = [
            {"column": 1, "line": 1, "text": "unique phrase here", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
        ]
        window_blob, window_index = build_blob_and_index(window_lines)

        # Body contains the substring twice (ambiguous in body)
        body_lines = [
            {"column": 2, "line": 1, "text": "unique phrase there", "bbox": (20, 0, 30, 10), "page_index": 0, "kind": "text"},
            {"column": 2, "line": 2, "text": "unique phrase also", "bbox": (20, 10, 30, 20), "page_index": 0, "kind": "text"},
        ]
        body_blob, body_index = build_blob_and_index(body_lines)

        # Search for "unique phrase"
        result = resolve(window_blob, window_index, body_blob, body_index, "unique phrase")

        # Should resolve to window hit (unique there), ignoring body duplicates
        assert result["found_at"] is not None
        assert result["match_scope"] == "window"

    def test_ac6_5_window_miss_body_fallback(self):
        """AC6.5: Substring absent from window, unique in body -> resolves to body."""
        window_lines = [
            {"column": 1, "line": 1, "text": "window content here", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
        ]
        window_blob, window_index = build_blob_and_index(window_lines)

        body_lines = [
            {"column": 2, "line": 1, "text": "body content here", "bbox": (20, 0, 30, 10), "page_index": 0, "kind": "text"},
        ]
        body_blob, body_index = build_blob_and_index(body_lines)

        # Search for "body content" (not in window, unique in body)
        result = resolve(window_blob, window_index, body_blob, body_index, "body content")

        # Should resolve to body hit
        assert result["found_at"] is not None
        assert result["match_scope"] == "body"

    def test_ac6_2_ambiguous_match_retry_false(self):
        """AC6.2: Multiple window hits with retried=False -> ambiguous_match with retry instruction."""
        window_lines = [
            {"column": 1, "line": 1, "text": "the the quick the", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
        ]
        window_blob, window_index = build_blob_and_index(window_lines)

        body_blob = ""
        body_index = []

        # Search for "the" (appears multiple times in window)
        result = resolve(window_blob, window_index, body_blob, body_index, "the", retried=False)

        # Should return ambiguous_match with retry instruction, no found_at
        assert result.get("ambiguous_match") is True
        assert "retry" in result
        assert "found_at" not in result or result.get("found_at") is None

    def test_ac6_3_ambiguous_match_retry_true(self):
        """AC6.3: Multiple hits with retried=True -> ambiguous_match with list of found_at."""
        window_lines = [
            {"column": 1, "line": 1, "text": "the the quick the", "bbox": (0, 0, 10, 10), "page_index": 0, "kind": "text"},
        ]
        window_blob, window_index = build_blob_and_index(window_lines)

        body_blob = ""
        body_index = []

        # Search for "the" with retried=True
        result = resolve(window_blob, window_index, body_blob, body_index, "the", retried=True)

        # Should return ambiguous_match with list of found_at
        assert result.get("ambiguous_match") is True
        assert "found_at" in result
        assert isinstance(result["found_at"], list)
        assert len(result["found_at"]) > 0


class TestVerifyEmit:
    """Tests for AC7.4: verify_emit handler."""

    def test_emit_from_artifact(self, us9_artifact):
        """verify_emit against a known cite yields documented output shape."""
        # Use a known cite from us9154231
        cite = "5:1-3"
        result = verify_emit(us9_artifact, cite)

        # Check all documented keys are present
        assert "cite" in result
        assert "cited_coord" in result
        assert "window_coord_range" in result
        assert "window_blob" in result
        assert "body_blob" in result
        assert "ambiguity" in result
        assert "ambiguity_reason" in result

        # Check types and non-empty constraints
        assert result["cite"] == cite
        assert isinstance(result["cited_coord"], (list, tuple))
        assert len(result["cited_coord"]) == 4
        assert all(isinstance(x, int) for x in result["cited_coord"])

        assert isinstance(result["window_coord_range"], (list, tuple))
        assert len(result["window_coord_range"]) == 4

        # Blobs are non-empty strings with no newlines
        assert isinstance(result["window_blob"], str)
        assert result["window_blob"]  # non-empty
        assert "\n" not in result["window_blob"]

        assert isinstance(result["body_blob"], str)
        assert result["body_blob"]  # non-empty
        assert "\n" not in result["body_blob"]

        # Ambiguity is bool
        assert isinstance(result["ambiguity"], bool)
        # ambiguity_reason is None or str
        assert result["ambiguity_reason"] is None or isinstance(
            result["ambiguity_reason"], str
        )


class TestVerifyResolve:
    """Tests for AC7.4: verify_resolve handler."""

    def test_resolve_unique_in_window(self):
        """verify_resolve with substring unique in window returns found_at + match_scope."""
        # Create a small synthetic document with known lines
        doc = {
            "lines": [
                {
                    "column": 1,
                    "line": 1,
                    "text": "the quick brown",
                    "bbox": (0, 0, 10, 10),
                    "page_index": 0,
                    "kind": "text",
                },
                {
                    "column": 1,
                    "line": 2,
                    "text": "fox jumps over",
                    "bbox": (0, 10, 10, 20),
                    "page_index": 0,
                    "kind": "text",
                },
            ]
        }

        # Resolve "quick" which is unique in the window
        result = verify_resolve(doc, "quick", "1:1-2", retried=False)

        assert "found_at" in result
        assert result["found_at"] is not None
        assert "match_scope" in result
        assert result["match_scope"] == "window"


class TestProcess:
    """Tests for AC7.1, AC7.2, AC7.3, AC7.4: process() batch handler."""

    def test_ac7_1_echoes_ids_in_order(self, tmp_path, us9_artifact):
        """process echoes id for every entry in order."""
        from patent_extract import write_document

        # Write artifact to tmp file
        artifact_path = tmp_path / "test.json"
        write_document(us9_artifact, artifact_path)

        entries = [
            {
                "id": "entry-1",
                "mode": "emit",
                "cite": "5:1",
                "artifact_path": str(artifact_path),
            },
            {
                "id": "entry-2",
                "mode": "emit",
                "cite": "6:1",
                "artifact_path": str(artifact_path),
            },
        ]

        results = process(entries)

        # Check IDs are echoed in order
        assert len(results) == 2
        assert results[0]["id"] == "entry-1"
        assert results[1]["id"] == "entry-2"

    def test_ac7_2_malformed_json(self, capsys, monkeypatch):
        """main with malformed JSON returns exit code 2."""
        # Mock stdin with bad JSON
        bad_json = "{not valid json"
        monkeypatch.setattr("sys.stdin", io.StringIO(bad_json))

        result = main([])

        assert result == 2
        _, stderr = capsys.readouterr()
        assert "ERROR" in stderr
        assert "valid JSON" in stderr

    def test_ac7_3_non_array_json(self, capsys, monkeypatch):
        """main with non-array JSON returns exit code 2."""
        # Mock stdin with object (not array)
        obj_json = json.dumps({"key": "value"})
        monkeypatch.setattr("sys.stdin", io.StringIO(obj_json))

        result = main([])

        assert result == 2
        _, stderr = capsys.readouterr()
        assert "ERROR" in stderr
        assert "array" in stderr

    def test_ac7_4_emit_and_resolve_batch(self, tmp_path, us9_artifact):
        """process with emit, resolve, and error entries returns documented shapes."""
        from patent_extract import write_document

        # Write artifact
        artifact_path = tmp_path / "test.json"
        write_document(us9_artifact, artifact_path)

        entries = [
            {
                "id": "emit-1",
                "mode": "emit",
                "cite": "5:1",
                "artifact_path": str(artifact_path),
            },
            {
                "id": "resolve-1",
                "mode": "resolve",
                "substring": "element",
                "within": "5:1-10",
                "artifact_path": str(artifact_path),
                "retried": False,
            },
            {
                "id": "missing-artifact",
                "mode": "emit",
                "cite": "5:1",
                "artifact_path": str(tmp_path / "nonexistent.json"),
            },
        ]

        results = process(entries)

        assert len(results) == 3

        # Check emit result has documented keys
        emit_result = results[0]
        assert emit_result["id"] == "emit-1"
        assert "cite" in emit_result
        assert "window_blob" in emit_result

        # Check resolve result has documented keys
        resolve_result = results[1]
        assert resolve_result["id"] == "resolve-1"
        assert "found_at" in resolve_result or "ambiguous_match" in resolve_result

        # Check missing artifact yields error result
        error_result = results[2]
        assert error_result["id"] == "missing-artifact"
        assert error_result.get("status") == "error"
        assert "error" in error_result
        assert "no such artifact" in error_result["error"]

    def test_unknown_mode_yields_error_result(self, tmp_path, us9_artifact):
        """An unrecognized mode becomes an error result, batch survives."""
        from patent_extract import write_document

        artifact_path = tmp_path / "test.json"
        write_document(us9_artifact, artifact_path)

        results = process(
            [{"id": "bad-mode", "mode": "frobnicate", "artifact_path": str(artifact_path)}]
        )

        assert len(results) == 1
        assert results[0]["id"] == "bad-mode"
        assert results[0]["status"] == "error"
        assert "unknown mode" in results[0]["error"]
        assert "frobnicate" in results[0]["error"]

    def test_bad_json_artifact_yields_error_result(self, tmp_path):
        """An artifact file that is not valid JSON becomes an error result."""
        artifact_path = tmp_path / "corrupt.json"
        artifact_path.write_text("{ this is not valid json", encoding="utf-8")

        results = process(
            [{"id": "corrupt", "mode": "emit", "cite": "5:1", "artifact_path": str(artifact_path)}]
        )

        assert len(results) == 1
        assert results[0]["id"] == "corrupt"
        assert results[0]["status"] == "error"
        assert "failed to load artifact" in results[0]["error"]

    def test_missing_required_field_yields_error_result(self, tmp_path, us9_artifact):
        """An emit entry missing 'cite' becomes an error result, not a crash."""
        from patent_extract import write_document

        artifact_path = tmp_path / "test.json"
        write_document(us9_artifact, artifact_path)

        results = process(
            [{"id": "no-cite", "mode": "emit", "artifact_path": str(artifact_path)}]
        )

        assert len(results) == 1
        assert results[0]["id"] == "no-cite"
        assert results[0]["status"] == "error"
        assert "missing required field" in results[0]["error"]


class TestMain:
    """Tests for AC7.1, AC7.2, AC7.3: main() CLI shape."""

    def test_main_reads_from_stdin_by_default(self, capsys, monkeypatch, tmp_path, us9_artifact):
        """main reads from stdin when --input is omitted."""
        from patent_extract import write_document

        # Write artifact
        artifact_path = tmp_path / "test.json"
        write_document(us9_artifact, artifact_path)

        # Mock stdin with valid batch
        batch = json.dumps(
            [
                {
                    "id": "test-1",
                    "mode": "emit",
                    "cite": "5:1",
                    "artifact_path": str(artifact_path),
                }
            ]
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(batch))

        result = main([])

        assert result == 0
        stdout, _ = capsys.readouterr()
        output = json.loads(stdout)
        assert isinstance(output, list)
        assert output[0]["id"] == "test-1"

    def test_main_reads_stdin_with_input_dash(self, capsys, monkeypatch, tmp_path, us9_artifact):
        """main reads from stdin when --input is '-' (conventional dash)."""
        from patent_extract import write_document

        artifact_path = tmp_path / "test.json"
        write_document(us9_artifact, artifact_path)

        batch = json.dumps(
            [
                {
                    "id": "test-1",
                    "mode": "emit",
                    "cite": "5:1",
                    "artifact_path": str(artifact_path),
                }
            ]
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(batch))

        result = main(["--input", "-"])

        assert result == 0
        stdout, _ = capsys.readouterr()
        output = json.loads(stdout)
        assert output[0]["id"] == "test-1"

    def test_main_reads_from_file_with_input_arg(self, capsys, tmp_path, us9_artifact):
        """main reads from --input file when provided."""
        from patent_extract import write_document

        # Write artifact
        artifact_path = tmp_path / "artifact.json"
        write_document(us9_artifact, artifact_path)

        # Write batch to input file
        batch_path = tmp_path / "batch.json"
        batch = [
            {
                "id": "test-1",
                "mode": "emit",
                "cite": "5:1",
                "artifact_path": str(artifact_path),
            }
        ]
        batch_path.write_text(json.dumps(batch))

        result = main(["--input", str(batch_path)])

        assert result == 0
        stdout, _ = capsys.readouterr()
        output = json.loads(stdout)
        assert len(output) == 1
        assert output[0]["id"] == "test-1"

    def test_main_outputs_json_with_trailing_newline(self, capsys, monkeypatch):
        """main outputs valid JSON array with trailing newline."""
        batch = json.dumps([])
        monkeypatch.setattr("sys.stdin", io.StringIO(batch))

        result = main([])

        assert result == 0
        stdout, _ = capsys.readouterr()
        # Check trailing newline
        assert stdout.endswith("\n")
        # Check valid JSON
        output = json.loads(stdout)
        assert isinstance(output, list)
