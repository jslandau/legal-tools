"""Integration and unit tests for patent_extract probe functionality."""
import json
from pathlib import Path

import pytest


class TestHasTextLayer:
    """Pure-function unit tests for the text-layer detection decision."""

    def test_empty_counts_no_text_layer(self):
        """No text layer when all pages have zero words."""
        from patent_extract import has_text_layer

        result = has_text_layer([0, 0, 0])
        assert result is False

    def test_substantial_counts_has_text_layer(self):
        """Text layer detected when sum exceeds threshold."""
        from patent_extract import has_text_layer

        result = has_text_layer([400, 300])
        assert result is True

    def test_boundary_min_total_words(self):
        """At MIN_TOTAL_WORDS boundary (True)."""
        from patent_extract import has_text_layer, MIN_TOTAL_WORDS

        result = has_text_layer([MIN_TOTAL_WORDS])
        assert result is True

    def test_boundary_min_total_words_minus_one(self):
        """Below MIN_TOTAL_WORDS boundary (False)."""
        from patent_extract import has_text_layer, MIN_TOTAL_WORDS

        result = has_text_layer([MIN_TOTAL_WORDS - 1])
        assert result is False


class TestPageWordCounts:
    """Tests for extracting per-page word counts from PDFs."""

    def test_born_digital_pdf_word_counts(self, born_digital_pdf: Path):
        """US9154231 (born-digital, 15 pages) has extractable words."""
        from patent_extract import page_word_counts

        counts = page_word_counts(born_digital_pdf)
        assert len(counts) == 15, f"Expected 15 pages, got {len(counts)}"
        assert all(isinstance(c, int) for c in counts)
        assert sum(counts) > 0, "Expected non-zero total words"

    def test_ocr_pdf_word_counts(self, ocr_pdf: Path):
        """US4731298 (scanned/OCR, 5 pages) has extractable words."""
        from patent_extract import page_word_counts

        counts = page_word_counts(ocr_pdf)
        assert len(counts) == 5, f"Expected 5 pages, got {len(counts)}"
        assert all(isinstance(c, int) for c in counts)
        assert sum(counts) > 0, "Expected non-zero total words"

    def test_no_text_layer_pdf_word_counts(self, no_text_layer_pdf: Path):
        """Raster-only PDF has zero extractable words."""
        from patent_extract import page_word_counts

        counts = page_word_counts(no_text_layer_pdf)
        assert len(counts) == 1, f"Expected 1 page, got {len(counts)}"
        assert counts[0] == 0, "Expected zero words for raster-only page"


class TestProbeFunction:
    """Integration tests for the probe function."""

    def test_probe_born_digital_has_text_layer(self, born_digital_pdf: Path):
        """AC1.1: Born-digital patent reports text layer + per-page counts."""
        from patent_extract import probe

        result = probe(born_digital_pdf)

        assert result["has_text_layer"] is True
        assert result["patent_id"] == "US9154231"
        assert result["source_path"] == str(born_digital_pdf)
        assert len(result["page_word_counts"]) == 15
        assert all(isinstance(c, int) for c in result["page_word_counts"])

    def test_probe_ocr_has_text_layer(self, ocr_pdf: Path):
        """AC1.1: OCR-layer patent reports text layer + per-page counts."""
        from patent_extract import probe

        result = probe(ocr_pdf)

        assert result["has_text_layer"] is True
        assert result["patent_id"] == "US4731298"
        assert result["source_path"] == str(ocr_pdf)
        assert len(result["page_word_counts"]) == 5
        assert all(isinstance(c, int) for c in result["page_word_counts"])

    def test_probe_no_text_layer(self, no_text_layer_pdf: Path):
        """AC1.2: Raster-only PDF reports no text layer."""
        from patent_extract import probe

        result = probe(no_text_layer_pdf)

        assert result["has_text_layer"] is False
        assert result["patent_id"] == "no_text_layer"
        assert result["source_path"] == str(no_text_layer_pdf)
        assert len(result["page_word_counts"]) == 1
        assert result["page_word_counts"][0] == 0


class TestMain:
    """Integration tests for CLI argument parsing and probe invocation."""

    def test_main_probe_born_digital(self, born_digital_pdf: Path, capsys):
        """Main with probe command outputs valid JSON with text-layer info."""
        from patent_extract import main

        exit_code = main(["probe", "--input", str(born_digital_pdf)])

        assert exit_code == 0
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["has_text_layer"] is True
        assert result["patent_id"] == "US9154231"
        assert len(result["page_word_counts"]) == 15

    def test_main_probe_no_text_layer(self, no_text_layer_pdf: Path, capsys):
        """Main with probe command on raster-only PDF reports False."""
        from patent_extract import main

        exit_code = main(["probe", "--input", str(no_text_layer_pdf)])

        assert exit_code == 0
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["has_text_layer"] is False

    def test_main_probe_missing_file(self, capsys):
        """Main handles missing file with error message and exit code 2."""
        from patent_extract import main

        exit_code = main(["probe", "--input", "/nonexistent/file.pdf"])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "no such file" in captured.err.lower()

    def test_main_help(self, capsys):
        """Help text is available (tests lazy import)."""
        from patent_extract import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "probe" in captured.out.lower()
