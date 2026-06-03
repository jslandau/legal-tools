"""Tests for patent_query.py — kind-aware span rendering (Phase 3 Task 2).

Tests use hand-built artifact dicts with explicit kinds, fast and deterministic.
"""
import pytest


@pytest.fixture
def artifact_simple() -> dict:
    """Hand-built minimal artifact with 3 columns of 3 lines each.

    Column 1: all text
    Column 2: line 1=text, line 2=blank, line 3=text
    Column 3: all text

    Used for AC8.1 (blank rendering) and AC8.3 (out-of-range).
    """
    return {
        "patent_id": "test",
        "source_path": "test.pdf",
        "source_sha256": "0000",
        "has_text_layer": True,
        "lines": [
            {"column": 1, "line": 1, "text": "<1.1>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            {"column": 1, "line": 2, "text": "<1.2>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            {"column": 1, "line": 3, "text": "<1.3>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            {"column": 2, "line": 1, "text": "<2.1>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            {"column": 2, "line": 2, "text": "", "kind": "blank", "bbox": (0, 0, 1, 1), "page_index": 0},
            {"column": 2, "line": 3, "text": "<2.3>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            {"column": 3, "line": 1, "text": "<3.1>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            {"column": 3, "line": 2, "text": "<3.2>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            {"column": 3, "line": 3, "text": "<3.3>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
        ],
        "page_fits": [],
        "column_diagnostics": [],
    }


@pytest.fixture
def artifact_with_spurious() -> dict:
    """Hand-built artifact with spurious slots for AC8.2 and AC9.3 testing.

    Column 1: lines 10-16, where 13 is spurious
    Line kinds: 10=text, 11=text, 12=text, 13=spurious, 14=text, 15=text, 16=text
    (width 7, contains spurious at position 13)
    """
    return {
        "patent_id": "test",
        "source_path": "test.pdf",
        "source_sha256": "0000",
        "has_text_layer": True,
        "lines": [
            {"column": 1, "line": 10, "text": "<10>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            {"column": 1, "line": 11, "text": "<11>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            {"column": 1, "line": 12, "text": "<12>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            {"column": 1, "line": 13, "text": "", "kind": "spurious", "bbox": (0, 0, 1, 1), "page_index": 0},
            {"column": 1, "line": 14, "text": "<14>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            {"column": 1, "line": 15, "text": "<15>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            {"column": 1, "line": 16, "text": "<16>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
        ],
        "page_fits": [],
        "column_diagnostics": [],
    }


class TestAC81BlankRendering:
    """AC8.1: Blank slots render as empty lines within a span."""

    def test_ac8_1_blank_rendered(self, artifact_simple: dict):
        """Span crossing a blank slot renders the blank as empty string.

        Citation 2:1-3 crosses column 2 where line 2 is blank.
        Expected: "<2.1>\n\n<2.3>" (blank rendered as empty string between newlines).
        """
        from patent_query import lookup_cite

        text = lookup_cite(artifact_simple, "2:1-3")
        assert text == "<2.1>\n\n<2.3>", f"Got: {text!r}"


class TestAC82Spurious:
    """AC8.2: Spurious slots are skipped silently (no blank line for them)."""

    def test_ac8_2_spurious_skipped(self, artifact_with_spurious: dict):
        """Span crossing a spurious slot skips it (no blank rendered).

        Citation 1:10-16 (width 7) crosses spurious at 13.
        Spurious should be skipped (not rendered), so output has 6 text lines, not 7.
        This is AC8.2 + AC9.3 (large span, no raise).
        Expected: "<10>\n<11>\n<12>\n<14>\n<15>\n<16>" (13 is skipped).
        """
        from patent_query import lookup_cite

        text = lookup_cite(artifact_with_spurious, "1:10-16")
        # Should have 6 text lines (10,11,12,14,15,16), no blank for 13
        expected = "<10>\n<11>\n<12>\n<14>\n<15>\n<16>"
        assert text == expected, f"Got: {text!r}"


class TestAC83OutOfRange:
    """AC8.3: Out-of-range lines and absent columns raise CiteError."""

    def test_ac8_3_line_out_of_range(self, artifact_simple: dict):
        """Citation to a line beyond max_line in a column raises CiteError."""
        from patent_query import CiteError, lookup_cite

        # Column 1 max_line is 3; cite to line 999
        with pytest.raises(CiteError, match="out of range"):
            lookup_cite(artifact_simple, "1:999")

    def test_ac8_3_column_absent(self, artifact_simple: dict):
        """Citation to a non-existent column raises CiteError."""
        from patent_query import CiteError, lookup_cite

        # Column 999 doesn't exist
        with pytest.raises(CiteError, match="column 999 not present"):
            lookup_cite(artifact_simple, "999:1")


class TestUnknownKindSkipped:
    """Unknown slots are skipped during normal rendering (like spurious).

    Task 3's ambiguity gate will decide whether to raise before rendering,
    but rendering itself must skip unknown like spurious.
    """

    def test_unknown_skipped_in_large_span(self):
        """Span crossing an unknown slot skips it (like spurious)."""
        from patent_query import lookup_cite

        artifact = {
            "patent_id": "test",
            "source_path": "test.pdf",
            "source_sha256": "0000",
            "has_text_layer": True,
            "lines": [
                {"column": 1, "line": 10, "text": "<10>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
                {"column": 1, "line": 11, "text": "<11>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
                {"column": 1, "line": 12, "text": "", "kind": "unknown", "bbox": (0, 0, 1, 1), "page_index": 0},
                {"column": 1, "line": 13, "text": "<13>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
                {"column": 1, "line": 14, "text": "<14>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            ],
            "page_fits": [],
            "column_diagnostics": [],
        }

        # Span 1:10-14 (width 5, >= AMBIGUITY_MAX_SPAN) crosses unknown at 12
        # Should render without raising (Task 3 gate doesn't apply to large spans)
        text = lookup_cite(artifact, "1:10-14")
        # unknown at 12 is skipped, so: <10>, <11>, <13>, <14>
        expected = "<10>\n<11>\n<13>\n<14>"
        assert text == expected, f"Got: {text!r}"
