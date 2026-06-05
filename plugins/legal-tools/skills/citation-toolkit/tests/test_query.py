"""Tests for patent_query.py — pinpoint patent citation lookups.

Task 13-14: Cross-column citation span support. parse_cite() returns a 4-tuple
(start_col, start_line, end_col, end_line), supporting both same-column and
cross-column citations. lookup() reads across column boundaries in document order.
"""
import json
from pathlib import Path

import pytest


@pytest.fixture
def us4_artifact(tmp_path: Path) -> dict:
    """Build and load the US4731298 artifact once for all tests."""
    from patent_extract import build_document, write_document, load_document

    pdf = Path(__file__).resolve().parent.parent / "test_fixtures" / "US4731298.pdf"
    artifact_path = tmp_path / "us4.json"

    doc = build_document(pdf)
    write_document(doc, artifact_path)
    return load_document(artifact_path)


class TestParseCite:
    """Pure unit tests for parse_cite — now returns 4-tuple (start_col, start_line, end_col, end_line)."""

    def test_parse_cite_single_line(self):
        """parse_cite('5:1') returns (5, 1, 5, 1) — same column start and end."""
        from patent_query import parse_cite

        start_col, start_line, end_col, end_line = parse_cite("5:1")
        assert start_col == 5
        assert start_line == 1
        assert end_col == 5
        assert end_line == 1

    def test_parse_cite_same_column_span(self):
        """parse_cite('5:1-3') returns (5, 1, 5, 3) — same column, range of lines."""
        from patent_query import parse_cite

        start_col, start_line, end_col, end_line = parse_cite("5:1-3")
        assert start_col == 5
        assert start_line == 1
        assert end_col == 5
        assert end_line == 3

    def test_parse_cite_cross_column_span(self):
        """parse_cite('4:65-5:3') returns (4, 65, 5, 3) — explicit end column and line."""
        from patent_query import parse_cite

        start_col, start_line, end_col, end_line = parse_cite("4:65-5:3")
        assert start_col == 4
        assert start_line == 65
        assert end_col == 5
        assert end_line == 3

    def test_parse_cite_bare_end_line_inherits_column(self):
        """parse_cite('4:32-38') — bare end line (no col:) inherits start column — returns (4, 32, 4, 38)."""
        from patent_query import parse_cite

        start_col, start_line, end_col, end_line = parse_cite("4:32-38")
        assert start_col == 4
        assert start_line == 32
        assert end_col == 4
        assert end_line == 38

    def test_parse_cite_whitespace_tolerated(self):
        """Whitespace around numbers/colons/hyphen is tolerated."""
        from patent_query import parse_cite

        start_col, start_line, end_col, end_line = parse_cite("4 : 32 - 38")
        assert start_col == 4
        assert start_line == 32
        assert end_col == 4
        assert end_line == 38

    def test_parse_cite_malformed_no_colon(self):
        """parse_cite('foo') raises CiteError."""
        from patent_query import CiteError, parse_cite

        with pytest.raises(CiteError, match="malformed citation"):
            parse_cite("foo")

    def test_parse_cite_malformed_missing_line(self):
        """parse_cite('5:') raises CiteError."""
        from patent_query import CiteError, parse_cite

        with pytest.raises(CiteError, match="malformed citation"):
            parse_cite("5:")

    def test_parse_cite_malformed_missing_end_line(self):
        """parse_cite('5:1-') raises CiteError."""
        from patent_query import CiteError, parse_cite

        with pytest.raises(CiteError, match="malformed citation"):
            parse_cite("5:1-")

    def test_parse_cite_backwards_same_column(self):
        """parse_cite('5:3-1') (end line < start line in same column) raises CiteError."""
        from patent_query import CiteError, parse_cite

        with pytest.raises(CiteError, match="precedes.*start"):
            parse_cite("5:3-1")

    def test_parse_cite_backwards_cross_column(self):
        """parse_cite('5:3-4:1') (end col:line lexicographically precedes start) raises CiteError."""
        from patent_query import CiteError, parse_cite

        # (4, 1) comes before (5, 3), so this is backwards
        with pytest.raises(CiteError, match="precedes.*start"):
            parse_cite("5:3-4:1")

    def test_parse_cite_malformed_invalid_cross_column_format(self):
        """parse_cite('4:-5:3') raises CiteError (missing start line)."""
        from patent_query import CiteError, parse_cite

        with pytest.raises(CiteError, match="malformed citation"):
            parse_cite("4:-5:3")


class TestLookup:
    """Tests for lookup and lookup_cite on real artifacts."""

    def test_ac6_1_single_line_us9(self, us9_artifact: dict):
        """AC6.1: lookup_cite(doc, '5:1') on US9154231 returns known col-5 line-1 text."""
        from patent_query import lookup_cite

        text = lookup_cite(us9_artifact, "5:1")
        # Known value from build: column 5, line 1
        assert "compensation processing (e.g., polarization-mode-d" in text

    def test_ac6_1_single_line_us4(self, us4_artifact: dict):
        """AC6.1: lookup_cite(doc, '1:2') on US4731298 returns known col-1 line-2 text."""
        from patent_query import lookup_cite

        text = lookup_cite(us4_artifact, "1:2")
        # Known value from build: "CARBON FIBER-REINFORCED LIGHT METAL"
        assert "CARBON FIBER-REINFORCED LIGHT METAL" in text

    def test_ac6_2_span_same_column_us9(self, us9_artifact: dict):
        """AC6.2: lookup_cite(doc, '5:1-3') returns three lines joined by newline."""
        from patent_query import lookup_cite

        text = lookup_cite(us9_artifact, "5:1-3")

        # Get the three lines individually
        line1 = lookup_cite(us9_artifact, "5:1")
        line2 = lookup_cite(us9_artifact, "5:2")
        line3 = lookup_cite(us9_artifact, "5:3")

        # Span should be lines joined by newlines
        expected = f"{line1}\n{line2}\n{line3}"
        assert text == expected

    def test_ac6_2_span_same_column_us4(self, us4_artifact: dict):
        """AC6.2: lookup_cite(doc, '1:2-3') returns two lines joined by newline on US4."""
        from patent_query import lookup_cite

        text = lookup_cite(us4_artifact, "1:2-3")

        line2 = lookup_cite(us4_artifact, "1:2")
        line3 = lookup_cite(us4_artifact, "1:3")

        expected = f"{line2}\n{line3}"
        assert text == expected

    def test_ac6_2_cross_column_span_us9(self, us9_artifact: dict):
        """AC6.2 (NEW): lookup_cite with cross-column span (adjacent columns) reads in document order.

        For US9154231, columns 5 and 6 are both gap-free (no missing lines 1..max).
        This test spans from line 67 of column 5 to line 1 of column 6.
        The cross-column reading order includes ALL lines from start_line to
        max_line(start_col), then end_col:1 to end_line. Column 5 has max=68,
        so the span includes 5:67, 5:68, and 6:1.
        """
        from patent_query import lookup_cite

        start_col = 5
        end_col = 6
        start_line = 67  # Line 67 of column 5
        end_line = 1    # Line 1 of column 6

        # Get the individual lines (including 5:68 per cross-column reading order)
        line_5_67 = lookup_cite(us9_artifact, "5:67")
        line_5_68 = lookup_cite(us9_artifact, "5:68")
        line_6_1 = lookup_cite(us9_artifact, "6:1")

        # Expected: 5:67, 5:68, then 6:1 joined
        expected = f"{line_5_67}\n{line_5_68}\n{line_6_1}"

        # Test the cross-column cite
        cite = f"{start_col}:{start_line}-{end_col}:{end_line}"
        text = lookup_cite(us9_artifact, cite)

        assert text == expected, (
            f"Cross-column span {cite} should join col 5 lines 67-68 + col 6 line 1; "
            f"got {text!r}"
        )

    def test_ac6_2_cross_column_span_renders_blank_lines(self, us9_artifact: dict):
        """NEW BEHAVIOR: Large span through column with gaps renders by kind.

        For US9154231, column 3 has interior gaps at lines [13, 33, 50, 52].
        These gaps are marked kind="spurious" or "blank" in the artifact.
        A LARGE span (width >= AMBIGUITY_MAX_SPAN) skips spurious/unknown slots
        and renders true blank slots as "" (preserving vertical gaps).

        Column 3 actually has NO true kind="blank" slots — all gaps are kind="spurious".
        Therefore, a large span through column 3 will skip all gap lines silently
        (no blank output lines). This test verifies that the text lines are still
        captured correctly in a large span.
        """
        from patent_query import lookup_cite

        # Test a large span covering much of column 3: lines 1-20 (width >= 5)
        # This avoids ambiguity and should render all text lines, skipping spurious gaps
        cite = "3:1-20"
        text = lookup_cite(us9_artifact, cite)

        # Verify the span includes known text lines
        # Column 3 has gaps at [13, 33, 50, 52], so expect no blank output at position 13
        # (since it's spurious, not true blank)
        parts = text.split("\n")

        # Collect expected text lines for 1-20, skipping spurious/blank
        expected_lines = []
        for line in us9_artifact["lines"]:
            if line["column"] == 3 and 1 <= line["line"] <= 20:
                if line["kind"] == "text":
                    expected_lines.append(line["text"])
                elif line["kind"] == "blank":
                    expected_lines.append("")

        # Verify result matches
        assert parts == expected_lines, (
            f"Span 3:1-20 should render text and blank lines, skipping spurious; "
            f"got {len(parts)} parts"
        )

    def test_ac6_2_same_column_span_with_blank_line(self, us9_artifact: dict):
        """Small span touching a spurious slot raises AmbiguousCiteError.

        Directly test the '3:12-14' case: line 13 is kind="spurious" (a grid artifact,
        not a true blank). A small span (width=3 < AMBIGUITY_MAX_SPAN=5) that touches
        a spurious or unknown slot raises AmbiguousCiteError with likely_text carrying
        the next 3 text lines starting from the start line (skipping spurious).
        """
        from patent_query import AmbiguousCiteError, lookup_cite

        cite = "3:12-14"

        with pytest.raises(AmbiguousCiteError, match="span width 3 may not match"):
            lookup_cite(us9_artifact, cite)

        # Verify the exception carries the likely-intended text
        try:
            lookup_cite(us9_artifact, cite)
            pytest.fail("Expected AmbiguousCiteError")
        except AmbiguousCiteError as e:
            # The likely_text is computed by physical_lines_from(col_lines, 12, 3)
            # which extracts 3 consecutive text lines starting from line 12,
            # skipping spurious/blank lines. That's lines 12, 14, 15 in column 3.
            expected_lines = [
                "having a second polarization orthogonal to the first polariza",  # line 12
                "tion, wherein the optical input signal is one of said first and",  # line 14
                "second optical components.",  # line 15
            ]
            expected_likely = "\n".join(expected_lines)
            assert e.likely_text == expected_likely, (
                f"likely_text mismatch; got {e.likely_text!r}"
            )

    def test_ac6_3_column_absent(self, us9_artifact: dict):
        """AC6.3: lookup_cite(doc, '999:1') raises CiteError (column absent)."""
        from patent_query import CiteError, lookup_cite

        with pytest.raises(CiteError, match="column 999 not present"):
            lookup_cite(us9_artifact, "999:1")

    def test_ac6_3_line_absent_same_column(self, us9_artifact: dict):
        """AC6.3: lookup_cite(doc, '5:9999') raises CiteError (line absent), message names it."""
        from patent_query import CiteError, lookup_cite

        with pytest.raises(CiteError, match="line"):
            lookup_cite(us9_artifact, "5:9999")

    def test_ac6_3_end_column_absent_cross_column(self, us9_artifact: dict):
        """AC6.3: cross-column cite to absent end column raises CiteError."""
        from patent_query import CiteError, lookup_cite

        with pytest.raises(CiteError, match="column"):
            lookup_cite(us9_artifact, "1:1-999:1")

    def test_ac6_4_error_messages_are_clear(self, us9_artifact: dict):
        """AC6.3/AC6.4: Error messages are informative."""
        from patent_query import CiteError, lookup_cite

        # Test that missing line message names the line
        try:
            lookup_cite(us9_artifact, "5:9999")
            pytest.fail("Expected CiteError")
        except CiteError as e:
            assert "9999" in str(e), f"Error message should name line 9999: {e}"


class TestBoundaryAndCrossSample:
    """Tests for boundary cases and cross-sample verification (Task 14)."""

    def test_boundary_first_line_first_column_us9(self, us9_artifact: dict):
        """Boundary: query 1:1 (first line of first body column) on US9154231."""
        from patent_query import lookup_cite

        text = lookup_cite(us9_artifact, "1:1")
        # Assert exact text (get the known first line from artifact)
        expected = next(
            line["text"] for line in us9_artifact["lines"]
            if line["column"] == 1 and line["line"] == 1
        )
        assert text == expected

    def test_boundary_first_line_first_column_us4(self, us4_artifact: dict):
        """Boundary: query 1:2 (first line present in column 1) on US4731298."""
        from patent_query import lookup_cite

        text = lookup_cite(us4_artifact, "1:2")
        # Assert exact text from artifact
        expected = next(
            line["text"] for line in us4_artifact["lines"]
            if line["column"] == 1 and line["line"] == 2
        )
        assert text == expected

    def test_boundary_last_line_us9(self, us9_artifact: dict):
        """Boundary: query the last line of a column on US9154231."""
        from patent_query import lookup_cite

        # Get max line in column 1
        max_line = max(
            line["line"]
            for line in us9_artifact["lines"]
            if line["column"] == 1
        )

        text = lookup_cite(us9_artifact, f"1:{max_line}")
        # Assert exact text from artifact
        expected = next(
            line["text"] for line in us9_artifact["lines"]
            if line["column"] == 1 and line["line"] == max_line
        )
        assert text == expected

    def test_boundary_last_line_us4(self, us4_artifact: dict):
        """Boundary: query the last line of a column on US4731298."""
        from patent_query import lookup_cite

        # Get max line in column 1
        max_line = max(
            line["line"]
            for line in us4_artifact["lines"]
            if line["column"] == 1
        )

        text = lookup_cite(us4_artifact, f"1:{max_line}")
        # Assert exact text from artifact
        expected = next(
            line["text"] for line in us4_artifact["lines"]
            if line["column"] == 1 and line["line"] == max_line
        )
        assert text == expected

    def test_cross_sample_single_query_us4(self, us4_artifact: dict):
        """Cross-sample: single-line queries work on US4731298 artifact."""
        from patent_query import lookup_cite

        text = lookup_cite(us4_artifact, "2:2")
        # Assert exact text from artifact
        expected = next(
            line["text"] for line in us4_artifact["lines"]
            if line["column"] == 2 and line["line"] == 2
        )
        assert text == expected

    def test_cross_sample_span_query_us4(self, us4_artifact: dict):
        """Cross-sample: span queries work on US4731298 artifact."""
        from patent_query import lookup_cite

        text = lookup_cite(us4_artifact, "2:2-5")
        # Assert exact text: lines 2-5 of column 2
        expected_lines = []
        for ln in range(2, 6):  # 2, 3, 4, 5
            line_text = next(
                line["text"] for line in us4_artifact["lines"]
                if line["column"] == 2 and line["line"] == ln
            )
            expected_lines.append(line_text)
        expected = "\n".join(expected_lines)
        assert text == expected, f"Span 2:2-5 should join lines 2-5 of column 2"

    def test_whole_span_equals_concatenation_us9(self, us9_artifact: dict):
        """Whole-span concatenation: query full contiguous span equals joining all lines."""
        from patent_query import lookup_cite, CiteError

        # Pick column 1 and get contiguous lines
        lines_in_col1 = sorted([
            line["line"] for line in us9_artifact["lines"] if line["column"] == 1
        ])
        if not lines_in_col1:
            pytest.skip("Column 1 has no lines")

        # Find a contiguous span
        min_line = lines_in_col1[0]
        # Find a small contiguous range (first few lines)
        contiguous_end = min_line
        for ln in lines_in_col1[1:]:
            if ln == contiguous_end + 1:
                contiguous_end = ln
            else:
                break

        # Query the contiguous span
        full_span = lookup_cite(us9_artifact, f"1:{min_line}-{contiguous_end}")

        # Manually join all lines in the range
        line_texts = []
        for ln in range(min_line, contiguous_end + 1):
            try:
                line_texts.append(lookup_cite(us9_artifact, f"1:{ln}"))
            except CiteError:
                # Line doesn't exist; this shouldn't happen in a contiguous range
                pytest.fail(f"Line {ln} should exist in contiguous range")

        if line_texts:
            expected = "\n".join(line_texts)
            assert full_span == expected

    def test_whole_span_equals_concatenation_us4(self, us4_artifact: dict):
        """Whole-span concatenation: query full contiguous span on US4731298."""
        from patent_query import lookup_cite, CiteError

        # Pick column 1 (which starts at line 2)
        lines_in_col1 = sorted([
            line["line"] for line in us4_artifact["lines"] if line["column"] == 1
        ])
        if not lines_in_col1:
            pytest.skip("Column 1 has no lines")

        # Find a contiguous span from the start
        min_line = lines_in_col1[0]
        contiguous_end = min_line
        for ln in lines_in_col1[1:]:
            if ln == contiguous_end + 1:
                contiguous_end = ln
            else:
                break

        # Query the contiguous span
        full_span = lookup_cite(us4_artifact, f"1:{min_line}-{contiguous_end}")

        # Manually join all lines in the range
        line_texts = []
        for ln in range(min_line, contiguous_end + 1):
            try:
                line_texts.append(lookup_cite(us4_artifact, f"1:{ln}"))
            except CiteError:
                # Line doesn't exist; this shouldn't happen in a contiguous range
                pytest.fail(f"Line {ln} should exist in contiguous range")

        if line_texts:
            expected = "\n".join(line_texts)
            assert full_span == expected

    def test_cross_column_whole_span_sanity_us9(self, us9_artifact: dict):
        """Cross-column whole-span sanity: span start_col full + end_col partial.

        For US9154231, columns 5 and 6 are both gap-free.
        Span from line 67 of column 5 to line 10 of column 6.
        The cross-column reading order includes ALL lines from 67 to max(5),
        then all lines 1 to 10 of column 6. Column 5 max is 68, so the span
        includes 5:67, 5:68, and 6:1 through 6:10.
        """
        from patent_query import lookup_cite

        start_col = 5
        end_col = 6
        start_line = 67  # Line 67 of column 5
        end_line = 10    # End at line 10 of column 6

        # Build expected text: line 67 of col 5, all the way to max (68),
        # then lines 1-10 of col 6
        expected_lines = []
        expected_lines.append(lookup_cite(us9_artifact, f"{start_col}:{start_line}"))
        expected_lines.append(lookup_cite(us9_artifact, f"{start_col}:68"))
        for ln in range(1, end_line + 1):
            expected_lines.append(lookup_cite(us9_artifact, f"{end_col}:{ln}"))

        expected = "\n".join(expected_lines)

        # Build the cross-column cite
        cite = f"{start_col}:{start_line}-{end_col}:{end_line}"
        result_text = lookup_cite(us9_artifact, cite)

        assert result_text == expected, (
            f"Cross-column span {cite} should join col 5 lines 67-68 + col 6 lines 1-10; "
            f"got {result_text!r}"
        )
