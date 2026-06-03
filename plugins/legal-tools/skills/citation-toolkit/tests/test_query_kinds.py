"""Tests for patent_query.py — kind-aware span rendering (Phase 3 Task 2).

Tests use hand-built artifact dicts with explicit kinds, fast and deterministic.
"""
from pathlib import Path

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


class TestAC91SmallSpanTouchingSpurious:
    """AC9.1: Small span touching spurious/unknown raises AmbiguousCiteError with likely_text."""

    def test_ac9_1_small_span_width_2_touching_spurious(self):
        """Span width 2 crossing spurious at endpoint raises AmbiguousCiteError.

        Artifact: 12=text, 13=spurious, 14=text
        Cite 12-13 (width 2, < AMBIGUITY_MAX_SPAN=5)
        Should raise AmbiguousCiteError with likely_text = two consecutive text lines (12, 14).
        """
        from patent_query import AmbiguousCiteError, lookup_cite

        artifact = {
            "patent_id": "test",
            "source_path": "test.pdf",
            "source_sha256": "0000",
            "has_text_layer": True,
            "lines": [
                {"column": 1, "line": 12, "text": "<12>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
                {"column": 1, "line": 13, "text": "", "kind": "spurious", "bbox": (0, 0, 1, 1), "page_index": 0},
                {"column": 1, "line": 14, "text": "<14>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            ],
            "page_fits": [],
            "column_diagnostics": [],
        }

        with pytest.raises(AmbiguousCiteError) as exc_info:
            lookup_cite(artifact, "1:12-13")

        err = exc_info.value
        assert err.reason == "span width 2 may not match printed gutter numbering near a grid artifact"
        assert err.likely_text == "<12>\n<14>", f"Got: {err.likely_text!r}"


class TestAC92SingleSpuriousCite:
    """AC9.2: Single cite to spurious/unknown slot raises AmbiguousCiteError."""

    def test_ac9_2_single_spurious_cite(self):
        """Single cite to spurious slot raises AmbiguousCiteError with neighbors.

        Artifact: 12=text, 13=spurious, 14=text
        Cite 13 (single line, spurious)
        Should raise AmbiguousCiteError with neighbors = (above_text, below_text).
        """
        from patent_query import AmbiguousCiteError, lookup_cite

        artifact = {
            "patent_id": "test",
            "source_path": "test.pdf",
            "source_sha256": "0000",
            "has_text_layer": True,
            "lines": [
                {"column": 1, "line": 12, "text": "<12>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
                {"column": 1, "line": 13, "text": "", "kind": "spurious", "bbox": (0, 0, 1, 1), "page_index": 0},
                {"column": 1, "line": 14, "text": "<14>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            ],
            "page_fits": [],
            "column_diagnostics": [],
        }

        with pytest.raises(AmbiguousCiteError) as exc_info:
            lookup_cite(artifact, "1:13")

        err = exc_info.value
        assert err.reason == "cited line is a numbering-grid slot, not a printed line"
        assert err.likely_text == "<12>\n<14>", f"Got: {err.likely_text!r}"
        assert err.neighbors == ("<12>", "<14>"), f"Got: {err.neighbors!r}"


class TestAC94CLIExitCodes:
    """AC9.4: main() handles AmbiguousCiteError with exit code 3."""

    def test_ac9_4_ambiguous_exit_3(self, tmp_path: Path):
        """Ambiguous citation (small span touching spurious) exits with code 3."""
        from patent_query import main
        import sys
        from io import StringIO

        artifact = {
            "patent_id": "test",
            "source_path": "test.pdf",
            "source_sha256": "0000",
            "has_text_layer": True,
            "lines": [
                {"column": 1, "line": 12, "text": "<12>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
                {"column": 1, "line": 13, "text": "", "kind": "spurious", "bbox": (0, 0, 1, 1), "page_index": 0},
                {"column": 1, "line": 14, "text": "<14>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            ],
            "page_fits": [],
            "column_diagnostics": [],
        }

        artifact_file = tmp_path / "test.json"
        import json

        with open(artifact_file, "w", encoding="utf-8") as f:
            json.dump(artifact, f)

        # Capture stderr
        old_stderr = sys.stderr
        sys.stderr = StringIO()
        try:
            exit_code = main(["--artifact", str(artifact_file), "--cite", "1:12-13"])
        finally:
            stderr_output = sys.stderr.getvalue()
            sys.stderr = old_stderr

        assert exit_code == 3, f"Expected exit code 3, got {exit_code}"
        assert "ambiguous" in stderr_output.lower(), f"stderr: {stderr_output!r}"
        assert "<12>" in stderr_output, f"stderr should contain likely text, got: {stderr_output!r}"

    def test_ac9_4_normal_cite_exit_0(self, tmp_path: Path):
        """Normal citation (renders without error) exits with code 0."""
        from patent_query import main
        import json

        artifact = {
            "patent_id": "test",
            "source_path": "test.pdf",
            "source_sha256": "0000",
            "has_text_layer": True,
            "lines": [
                {"column": 1, "line": 1, "text": "<1>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            ],
            "page_fits": [],
            "column_diagnostics": [],
        }

        artifact_file = tmp_path / "test.json"
        with open(artifact_file, "w", encoding="utf-8") as f:
            json.dump(artifact, f)

        exit_code = main(["--artifact", str(artifact_file), "--cite", "1:1"])
        assert exit_code == 0, f"Expected exit code 0, got {exit_code}"

    def test_ac9_4_cite_error_exit_1(self, tmp_path: Path):
        """Out-of-range citation exits with code 1."""
        from patent_query import main
        import json

        artifact = {
            "patent_id": "test",
            "source_path": "test.pdf",
            "source_sha256": "0000",
            "has_text_layer": True,
            "lines": [
                {"column": 1, "line": 1, "text": "<1>", "kind": "text", "bbox": (0, 0, 1, 1), "page_index": 0},
            ],
            "page_fits": [],
            "column_diagnostics": [],
        }

        artifact_file = tmp_path / "test.json"
        with open(artifact_file, "w", encoding="utf-8") as f:
            json.dump(artifact, f)

        exit_code = main(["--artifact", str(artifact_file), "--cite", "1:999"])
        assert exit_code == 1, f"Expected exit code 1 for CiteError, got {exit_code}"


class TestAC93LargeSpanNoRaise:
    """AC9.3: Large spans (>= AMBIGUITY_MAX_SPAN) touching spurious/unknown render without raising."""

    def test_ac9_3_large_span_no_raise(self, artifact_with_spurious: dict):
        """Span width >= 5 crossing spurious renders normally (Task 2 verified this)."""
        from patent_query import lookup_cite

        # artifact_with_spurious has lines 10-16 with 13=spurious (width 7, >= 5)
        # Should render without raising
        text = lookup_cite(artifact_with_spurious, "1:10-16")
        expected = "<10>\n<11>\n<12>\n<14>\n<15>\n<16>"
        assert text == expected, f"Got: {text!r}"


# Integration tests on real US9154231 artifact
class TestIntegrationUS9154231:
    """Integration tests on US9154231: test real artifact behavior."""

    @pytest.fixture
    def us9_artifact(self, tmp_path: Path) -> dict:
        """Build and load the US9154231 artifact."""
        from patent_extract import build_document, write_document, load_document

        pdf = Path(__file__).resolve().parent.parent / "test_fixtures" / "US9154231.pdf"
        artifact_path = tmp_path / "us9.json"

        doc = build_document(pdf)
        write_document(doc, artifact_path)
        return load_document(artifact_path)

    def test_us9_page_3_small_span_ambiguous(self, us9_artifact: dict):
        """US9154231 page 3, cols 3, lines 12-13: small span touching spurious raises AmbiguousCiteError."""
        from patent_query import AmbiguousCiteError, lookup_cite

        # First, inspect what's at 3:12-14 to capture expected text
        # We'll build the expected text from the artifact
        try:
            lookup_cite(us9_artifact, "3:12-13")
            assert False, "Should have raised AmbiguousCiteError"
        except AmbiguousCiteError as e:
            # Capture the actual likely_text for assertion
            # Both neighbors should be real text lines
            assert len(e.likely_text.split("\n")) == 2, f"Expected 2 text lines in likely_text, got: {e.likely_text!r}"
            # Both should be non-empty text
            for line in e.likely_text.split("\n"):
                assert line.strip(), f"Expected non-empty text lines in: {e.likely_text!r}"

    def test_us9_page_3_blank_rendering(self, us9_artifact: dict):
        """US9154231 page 3, lines 49-51: span with true blank at 50 renders with empty line."""
        from patent_query import lookup_cite

        text = lookup_cite(us9_artifact, "3:49-51")
        lines = text.split("\n")
        assert len(lines) == 3, f"Expected 3 lines (49, blank, 51), got {len(lines)}: {lines}"
        assert lines[1] == "", f"Expected blank at line 50 (index 1), got: {lines[1]!r}"
        # Lines 49 and 51 should have text
        assert lines[0].strip(), f"Expected text at line 49, got: {lines[0]!r}"
        assert lines[2].strip(), f"Expected text at line 51, got: {lines[2]!r}"

    def test_us9_page_3_large_span_touching_spurious(self, us9_artifact: dict):
        """US9154231 page 3, lines 10-20 (width 11, >= 5): large span touching spurious renders without raising."""
        from patent_query import lookup_cite

        # This should render normally even if it touches spurious/unknown
        text = lookup_cite(us9_artifact, "3:10-20")
        lines = text.split("\n")
        # Should have multiple lines (some may be blank, none should raise)
        assert len(lines) > 0, f"Expected non-empty result, got: {text!r}"
