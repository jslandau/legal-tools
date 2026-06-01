"""Tests for patent_query.py — pinpoint patent citation lookups."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def us9_artifact(tmp_path: Path) -> dict:
    """Build and load the US9154231 artifact once for all tests."""
    from patent_extract import build_document, write_document, load_document

    pdf = Path(__file__).resolve().parent.parent / "test_fixtures" / "US9154231.pdf"
    artifact_path = tmp_path / "us9.json"

    doc = build_document(pdf)
    write_document(doc, artifact_path)
    return load_document(artifact_path)


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
    """Pure unit tests for parse_cite."""

    def test_parse_cite_single_line(self):
        """parse_cite('4:32') returns (4, 32, 32)."""
        from patent_query import parse_cite

        col, start, end = parse_cite("4:32")
        assert col == 4
        assert start == 32
        assert end == 32

    def test_parse_cite_span(self):
        """parse_cite('4:32-38') returns (4, 32, 38)."""
        from patent_query import parse_cite

        col, start, end = parse_cite("4:32-38")
        assert col == 4
        assert start == 32
        assert end == 38

    def test_parse_cite_whitespace_tolerated(self):
        """parse_cite tolerates whitespace: '4 : 32 - 38' works."""
        from patent_query import parse_cite

        col, start, end = parse_cite("4 : 32 - 38")
        assert col == 4
        assert start == 32
        assert end == 38

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

    def test_parse_cite_end_before_start(self):
        """parse_cite('5:3-1') (end < start) raises CiteError."""
        from patent_query import CiteError, parse_cite

        with pytest.raises(CiteError, match="end line.*precedes.*start"):
            parse_cite("5:3-1")


class TestLookup:
    """Tests for lookup and lookup_cite on real artifacts."""

    def test_ac6_1_single_line_us9(self, us9_artifact: dict):
        """AC6.1: lookup_cite(doc, '5:1') on US9154231 returns known col-5 line-1 text."""
        from patent_query import lookup_cite

        text = lookup_cite(us9_artifact, "5:1")
        # Known value from build: "compensation processing (e.g., polarization-mode-disper"
        assert "compensation processing (e.g., polarization-mode-d" in text

    def test_ac6_1_single_line_us4(self, us4_artifact: dict):
        """AC6.1: lookup_cite(doc, '1:2') on US4731298 returns known col-1 line-2 text."""
        from patent_query import lookup_cite

        text = lookup_cite(us4_artifact, "1:2")
        # Known value from build: "CARBON FIBER-REINFORCED LIGHT METAL"
        assert "CARBON FIBER-REINFORCED LIGHT METAL" in text

    def test_ac6_2_span_us9(self, us9_artifact: dict):
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

    def test_ac6_2_span_us4(self, us4_artifact: dict):
        """AC6.2: lookup_cite(doc, '1:2-3') returns two lines joined by newline on US4."""
        from patent_query import lookup_cite

        text = lookup_cite(us4_artifact, "1:2-3")

        line2 = lookup_cite(us4_artifact, "1:2")
        line3 = lookup_cite(us4_artifact, "1:3")

        expected = f"{line2}\n{line3}"
        assert text == expected

    def test_ac6_3_column_absent(self, us9_artifact: dict):
        """AC6.3: lookup_cite(doc, '999:1') raises CiteError (column absent)."""
        from patent_query import CiteError, lookup_cite

        with pytest.raises(CiteError, match="column 999 not present"):
            lookup_cite(us9_artifact, "999:1")

    def test_ac6_3_line_absent(self, us9_artifact: dict):
        """AC6.3: lookup_cite(doc, '5:9999') raises CiteError (line absent), message names it."""
        from patent_query import CiteError, lookup_cite

        with pytest.raises(CiteError, match="line"):
            lookup_cite(us9_artifact, "5:9999")

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
        assert text is not None
        assert len(text) > 0

    def test_boundary_first_line_first_column_us4(self, us4_artifact: dict):
        """Boundary: query 1:2 (first line present in column 1) on US4731298."""
        from patent_query import lookup_cite

        text = lookup_cite(us4_artifact, "1:2")
        assert text is not None
        assert len(text) > 0

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
        assert text is not None
        assert len(text) > 0

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
        assert text is not None
        assert len(text) > 0

    def test_cross_sample_single_query_us4(self, us4_artifact: dict):
        """Cross-sample: single-line queries work on US4731298 artifact."""
        from patent_query import lookup_cite

        text = lookup_cite(us4_artifact, "2:2")
        assert text is not None
        assert len(text) > 0

    def test_cross_sample_span_query_us4(self, us4_artifact: dict):
        """Cross-sample: span queries work on US4731298 artifact."""
        from patent_query import lookup_cite

        text = lookup_cite(us4_artifact, "2:2-5")
        assert text is not None
        assert "\n" in text, "Span should have multiple lines"

    def test_whole_span_equals_concatenation_us9(self, us9_artifact: dict):
        """Whole-span concatenation: query full 1-N span equals joining all lines."""
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
