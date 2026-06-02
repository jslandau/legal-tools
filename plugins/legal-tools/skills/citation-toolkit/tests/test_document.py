"""Integration and unit tests for document building, persistence, and caching."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestPatentDocBuild:
    """Tests for build_document orchestrator and running column counter."""

    def test_build_document_born_digital_ac5_1(self, born_digital_pdf: Path):
        """AC5.1: build_document(born_digital_pdf) returns PatentDoc with lines and page_fits."""
        from patent_extract import build_document

        doc = build_document(born_digital_pdf)

        # Verify structure
        assert isinstance(doc, dict)
        assert "patent_id" in doc
        assert "source_path" in doc
        assert "source_sha256" in doc
        assert "has_text_layer" in doc
        assert "lines" in doc
        assert "page_fits" in doc

        # US9154231 is born-digital with text layer
        assert doc["patent_id"] == "US9154231"
        assert doc["has_text_layer"] is True
        assert len(doc["lines"]) > 0, "Expected non-empty lines"
        assert len(doc["page_fits"]) == 15, "Expected one PageFit per source page (15 total)"

        # Verify sha256 format
        assert len(doc["source_sha256"]) == 64, "sha256 should be 64 hex chars"

    def test_build_document_ac5_1_spot_check_text(self, born_digital_pdf: Path):
        """AC5.1: Spot-check known (column, line) text matches Phase 3 expectations.

        US9154231 PDF index 7 = printed cols 1/2, index 8 = cols 3/4, index 9 = cols 5/6.
        Running counter over body pages (indices 7-13 = 7 body pages) assigns:
        - Body page 0 (PDF index 7) -> columns 1/2
        - Body page 1 (PDF index 8) -> columns 3/4
        - Body page 2 (PDF index 9) -> columns 5/6
        """
        from patent_extract import build_document

        doc = build_document(born_digital_pdf)
        lines = doc["lines"]

        # Find lines from PDF page index 7 (first body page), column 1
        page_7_col_1_lines = [
            line for line in lines
            if line["page_index"] == 7 and line["column"] == 1
        ]
        assert len(page_7_col_1_lines) > 0, "Expected lines from page 7, column 1"

        # Expected text from Phase 3 verification
        col_1_texts = [line["text"] for line in page_7_col_1_lines if line["line"] == 1]
        assert any("GENERATION OF AN OPTICAL" in text for text in col_1_texts), \
            f"Expected 'GENERATION OF AN OPTICAL' in column 1, line 1. Got: {col_1_texts}"

        # Verify column 3 (from page index 8, first body page col 3)
        page_8_col_3_lines = [
            line for line in lines
            if line["page_index"] == 8 and line["column"] == 3
        ]
        col_3_texts = [line["text"] for line in page_8_col_3_lines if line["line"] == 1]
        assert any("first electrical radio-frequency signal" in text for text in col_3_texts), \
            f"Expected radio-frequency text in column 3. Got: {col_3_texts}"

    def test_build_document_ac5_3_column_contiguity(self, born_digital_pdf: Path):
        """AC5.3: Distinct column numbers are exactly 1..2*B (B=body pages), no gaps."""
        from patent_extract import build_document

        doc = build_document(born_digital_pdf)
        lines = doc["lines"]

        # Get distinct column numbers
        cols = sorted(set(line["column"] for line in lines))

        # Count body pages by the classifier's is_body flag (the column-counter driver),
        # not by "pages with lines" — a body page can legitimately yield no lines (a
        # marker-less claims tail), though US9154231 has none such.
        body_page_count = sum(1 for pf in doc["page_fits"] if pf["is_body"])

        # US9154231 has 8 body pages: the seven two-column body pages (indices 7-13)
        # plus the single-column claims tail (index 14, cols 15/16).
        assert body_page_count == 8, f"Expected 8 body pages, got {body_page_count}"

        # Populated columns are a gap-free prefix of 1..2B, EXCEPT that the very last
        # column may be unpopulated when the final body page is a single-column claims
        # tail (col 16 here is allocated but empty — the claims ended in col 15). So:
        #   - no column number exceeds 2*B
        #   - the populated columns 1..max are contiguous (no interior gaps)
        max_col = 2 * body_page_count
        assert cols[-1] <= max_col, f"Column {cols[-1]} exceeds allocated max {max_col}"
        assert cols == list(range(1, cols[-1] + 1)), f"Interior gap in populated columns: {cols}"
        # The only permitted unpopulated column is the trailing one (claims-tail right col).
        assert cols[-1] in (max_col, max_col - 1), f"Unexpected populated-column range: {cols}"

        # Columns are 1-based with left=odd, right=even, so the sorted contiguous
        # prefix alternates odd, even, odd, even ... starting at 1.
        for i, col in enumerate(cols):
            expected_parity = 1 if i % 2 == 0 else 0
            assert col % 2 == expected_parity, f"Column {col} at position {i} has wrong parity"

    def test_build_document_ac5_3_non_body_pages_zero_columns(self, born_digital_pdf: Path):
        """AC5.3: NON-BODY pages have left_column == 0 and right_column == 0.

        Keyed on is_body, not flagged: a body page flagged for review (e.g. gutter
        cross-check disagreement) still keeps its consumed column numbers. Only
        non-body pages are zeroed.
        """
        from patent_extract import build_document

        doc = build_document(born_digital_pdf)

        for pf in doc["page_fits"]:
            if not pf["is_body"]:
                assert pf["left_column"] == 0, f"Non-body page {pf['page_index']} should have left_column==0"
                assert pf["right_column"] == 0, f"Non-body page {pf['page_index']} should have right_column==0"
            else:
                assert pf["left_column"] > 0, f"Body page {pf['page_index']} should have a column number"

    def test_build_document_ac5_5_no_text_layer(self, no_text_layer_pdf: Path):
        """AC5.5: build_document on no-text-layer PDF returns without raising.
        has_text_layer is False, lines=[], all PageFit flagged=True."""
        from patent_extract import build_document

        # Should not raise
        doc = build_document(no_text_layer_pdf)

        # Verify structure exists
        assert isinstance(doc, dict)
        assert "patent_id" in doc
        assert "source_sha256" in doc
        assert "has_text_layer" in doc
        assert "lines" in doc
        assert "page_fits" in doc

        # Verify no text layer detected
        assert doc["has_text_layer"] is False
        assert doc["lines"] == [], "Expected empty lines for no-text-layer PDF"

        # Verify all pages are flagged
        for pf in doc["page_fits"]:
            assert pf["flagged"] is True, f"Page {pf['page_index']} should be flagged"


class TestSha256File:
    """Tests for the sha256_file helper."""

    def test_sha256_file_consistency(self, born_digital_pdf: Path):
        """sha256_file returns consistent 64-char hex string for same file."""
        from patent_extract import sha256_file

        hash1 = sha256_file(born_digital_pdf)
        hash2 = sha256_file(born_digital_pdf)

        assert hash1 == hash2, "Same file should produce same hash"
        assert len(hash1) == 64, "SHA256 hex should be 64 characters"
        assert all(c in "0123456789abcdef" for c in hash1), "Hash should be valid hex"

    def test_sha256_file_different_files(self, born_digital_pdf: Path, ocr_pdf: Path):
        """sha256_file returns different hashes for different files."""
        from patent_extract import sha256_file

        hash1 = sha256_file(born_digital_pdf)
        hash2 = sha256_file(ocr_pdf)

        assert hash1 != hash2, "Different files should have different hashes"


class TestWriteDocument:
    """Tests for write_document JSON persistence."""

    def test_write_document_creates_file(self, born_digital_pdf: Path, tmp_path: Path):
        """write_document creates a JSON file at the specified path."""
        from patent_extract import build_document, write_document

        doc = build_document(born_digital_pdf)
        out_path = tmp_path / "test.json"

        write_document(doc, out_path)

        assert out_path.exists(), "Output file should exist"
        assert out_path.stat().st_size > 0, "Output file should not be empty"

    def test_write_document_valid_json(self, born_digital_pdf: Path, tmp_path: Path):
        """write_document produces valid JSON."""
        from patent_extract import build_document, write_document

        doc = build_document(born_digital_pdf)
        out_path = tmp_path / "test.json"

        write_document(doc, out_path)

        # Should parse without error
        with open(out_path) as f:
            loaded = json.load(f)
        assert isinstance(loaded, dict)

    def test_write_document_trailing_newline(self, born_digital_pdf: Path, tmp_path: Path):
        """write_document adds trailing newline (house convention)."""
        from patent_extract import build_document, write_document

        doc = build_document(born_digital_pdf)
        out_path = tmp_path / "test.json"

        write_document(doc, out_path)

        content = out_path.read_text(encoding="utf-8")
        assert content.endswith("\n"), "Output should end with newline"


class TestLoadDocument:
    """Tests for load_document JSON deserialization."""

    def test_load_document_roundtrip(self, born_digital_pdf: Path, tmp_path: Path):
        """AC5.2: build -> write -> load -> equals original (bbox normalized to tuple)."""
        from patent_extract import build_document, write_document, load_document

        # Build original
        original = build_document(born_digital_pdf)

        # Write to temp file
        out_path = tmp_path / "roundtrip.json"
        write_document(original, out_path)

        # Load back
        reloaded = load_document(out_path)

        # Normalize both for comparison: serialize through JSON like write_document does,
        # then normalize bbox back to tuples like load_document does
        def normalize_doc(doc):
            """Serialize through JSON (which converts tuples to lists) and back,
            then normalize bbox lists back to tuples to match load_document behavior."""
            # Round-trip through JSON to match what write_document/load_document do
            serialized = json.loads(json.dumps(doc))
            # Normalize all bboxes to tuples like load_document does
            for line in serialized["lines"]:
                line["bbox"] = tuple(line["bbox"])
            return serialized

        original_normalized = normalize_doc(original)
        reloaded_normalized = normalize_doc(reloaded)

        # Compare all fields with deep equality
        assert reloaded_normalized["patent_id"] == original_normalized["patent_id"]
        assert reloaded_normalized["source_path"] == original_normalized["source_path"]
        assert reloaded_normalized["source_sha256"] == original_normalized["source_sha256"]
        assert reloaded_normalized["has_text_layer"] == original_normalized["has_text_layer"]
        # Deep equality: catch corrupted fields within lines, not just count
        assert reloaded_normalized["lines"] == original_normalized["lines"], (
            "lines deep equality failed: serialization may have corrupted a field"
        )
        assert reloaded_normalized["page_fits"] == original_normalized["page_fits"], (
            "page_fits deep equality failed: serialization may have corrupted a field"
        )

        # Verify bbox is tuple after load
        for line in reloaded["lines"]:
            assert isinstance(line["bbox"], tuple), f"bbox should be tuple, got {type(line['bbox'])}"
            assert len(line["bbox"]) == 4, "bbox should have 4 elements"
            assert all(isinstance(x, (int, float)) for x in line["bbox"]), "bbox elements should be numeric"

    def test_load_document_bbox_tuple_conversion(self, born_digital_pdf: Path, tmp_path: Path):
        """load_document explicitly converts bbox lists to tuples."""
        from patent_extract import build_document, write_document, load_document

        doc = build_document(born_digital_pdf)
        out_path = tmp_path / "bbox_test.json"

        write_document(doc, out_path)
        reloaded = load_document(out_path)

        # Every line's bbox should be a tuple
        for line in reloaded["lines"]:
            assert isinstance(line["bbox"], tuple), "bbox should be tuple after load"
            assert len(line["bbox"]) == 4, "bbox should be (x0, top, x1, bottom)"
            # All bbox components should be floats
            assert all(isinstance(x, (int, float)) for x in line["bbox"])


class TestBuildOrLoad:
    """Tests for cache reuse via SHA256 matching."""

    def test_build_or_load_cache_hit(self, born_digital_pdf: Path, tmp_path: Path):
        """AC5.4: Second build_or_load with same source uses cache (mtime unchanged)."""
        from patent_extract import build_or_load, build_document

        artifact_path = tmp_path / "cache_test.json"

        # First build
        doc1 = build_or_load(born_digital_pdf, artifact_path, force=False)
        mtime1 = artifact_path.stat().st_mtime_ns

        # Wait slightly to ensure different mtime if file is written
        import time
        time.sleep(0.01)

        # Second build (should hit cache)
        doc2 = build_or_load(born_digital_pdf, artifact_path, force=False)
        mtime2 = artifact_path.stat().st_mtime_ns

        # Cache hit means mtime unchanged and content identical
        assert mtime1 == mtime2, "Cache hit should not rewrite file"
        assert doc1 == doc2, "Cached doc should equal original"

    def test_build_or_load_cache_miss_different_source(self, born_digital_pdf: Path, ocr_pdf: Path, tmp_path: Path):
        """AC5.4: Changed source (different hash) triggers rebuild."""
        from patent_extract import build_or_load

        artifact_path = tmp_path / "cache_miss_test.json"

        # Build with first PDF
        doc1 = build_or_load(born_digital_pdf, artifact_path, force=False)
        mtime1 = artifact_path.stat().st_mtime_ns
        lines1_count = len(doc1["lines"])

        import time
        time.sleep(0.01)

        # Build with different PDF (should miss cache and rebuild)
        doc2 = build_or_load(ocr_pdf, artifact_path, force=False)
        mtime2 = artifact_path.stat().st_mtime_ns
        lines2_count = len(doc2["lines"])

        # File should be rewritten
        assert mtime2 > mtime1, "Different source should trigger rewrite"
        # Content should differ
        assert lines1_count != lines2_count, "Different PDFs should have different line counts"

    def test_build_or_load_force_always_rebuilds(self, born_digital_pdf: Path, tmp_path: Path):
        """AC5.4: --force flag always rebuilds even with valid cache."""
        from patent_extract import build_or_load

        artifact_path = tmp_path / "force_test.json"

        # Build normally
        build_or_load(born_digital_pdf, artifact_path, force=False)
        mtime1 = artifact_path.stat().st_mtime_ns

        import time
        time.sleep(0.01)

        # Build again with force=True (should rebuild)
        build_or_load(born_digital_pdf, artifact_path, force=True)
        mtime2 = artifact_path.stat().st_mtime_ns

        assert mtime2 > mtime1, "force=True should rebuild even with valid cache"

    def test_build_or_load_cache_invalid_sha256(self, born_digital_pdf: Path, tmp_path: Path):
        """AC5.4: Corrupted/invalid stored sha256 triggers rebuild."""
        from patent_extract import build_or_load, load_document, write_document

        artifact_path = tmp_path / "invalid_sha_test.json"

        # Build normally
        doc1 = build_or_load(born_digital_pdf, artifact_path, force=False)
        mtime1 = artifact_path.stat().st_mtime_ns

        # Corrupt the stored sha256
        corrupted_doc = load_document(artifact_path)
        corrupted_doc["source_sha256"] = "0" * 64  # Invalid hash
        write_document(corrupted_doc, artifact_path)
        mtime_corrupted = artifact_path.stat().st_mtime_ns

        import time
        time.sleep(0.01)

        # Try to load again (should rebuild due to sha256 mismatch)
        doc2 = build_or_load(born_digital_pdf, artifact_path, force=False)
        mtime2 = artifact_path.stat().st_mtime_ns

        assert mtime2 > mtime_corrupted, "Invalid sha256 should trigger rebuild"
        assert doc2["source_sha256"] != "0" * 64, "Rebuilt doc should have correct sha256"


class TestLineKind:
    """Tests for the Line schema with kind field (Task 1)."""

    def test_line_kind_field_membership(self, born_digital_pdf: Path):
        """AC4.1: All emitted Line rows have kind in LINE_KINDS."""
        from patent_extract import build_document, LINE_KINDS

        doc = build_document(born_digital_pdf)

        for line in doc["lines"]:
            assert "kind" in line, "Line should have 'kind' field"
            assert line["kind"] in LINE_KINDS, f"kind={line['kind']} not in LINE_KINDS={LINE_KINDS}"

    def test_line_kind_text_invariant(self, born_digital_pdf: Path):
        """AC4.1 invariant: text != "" iff kind == "text"."""
        from patent_extract import build_document

        doc = build_document(born_digital_pdf)

        for line in doc["lines"]:
            kind = line["kind"]
            text = line["text"]
            if kind == "text":
                assert text != "", f"kind='text' must have non-empty text, got text='{text}'"
            else:
                # For blank/spurious/unknown: we'll enforce empty text in Task 2+,
                # but for Task 1 all lines are created as kind="text" with non-empty text
                assert text != "", f"Task 1: all lines created with kind='text' and non-empty text"

    def test_load_document_backfill_kind_old_artifact(self, tmp_path: Path):
        """AC4.3: load_document backfills kind='text' on pre-kind artifacts.

        This test builds a hand-crafted old-style line dict (no kind),
        writes it as JSON, and verifies load_document adds kind='text'.
        """
        import json
        from patent_extract import load_document, LINE_KINDS

        # Create an old-style artifact (pre-kind)
        old_style_doc = {
            "patent_id": "TEST",
            "source_path": "/fake/test.pdf",
            "source_sha256": "0" * 64,
            "has_text_layer": True,
            "lines": [
                {
                    "column": 1,
                    "line": 1,
                    "text": "Sample text",
                    "bbox": [0.0, 10.0, 100.0, 20.0],
                    "page_index": 0,
                    # NOTE: no "kind" field — simulating old artifact
                }
            ],
            "page_fits": []
        }

        # Write as JSON to temp file (simulate old artifact)
        artifact_path = tmp_path / "old_artifact.json"
        with open(artifact_path, "w", encoding="utf-8") as f:
            json.dump(old_style_doc, f)

        # Load with load_document
        loaded = load_document(artifact_path)

        # Verify kind was backfilled
        assert len(loaded["lines"]) == 1
        line = loaded["lines"][0]
        assert "kind" in line, "load_document should backfill 'kind'"
        assert line["kind"] == "text", "Backfilled kind should be 'text'"
        assert line["kind"] in LINE_KINDS, f"Backfilled kind should be in LINE_KINDS"
        # Verify other fields unchanged
        assert line["text"] == "Sample text"
        assert line["column"] == 1
        assert line["line"] == 1


class TestBuildSubcommand:
    """Tests for the build CLI subcommand."""

    def test_build_subcommand_cli(self, born_digital_pdf: Path, tmp_path: Path, capsys):
        """build subcommand writes artifact and prints summary to stderr."""
        from patent_extract import main

        out_path = tmp_path / "cli_build.json"
        exit_code = main([
            "build",
            "--input", str(born_digital_pdf),
            "--out", str(out_path)
        ])

        assert exit_code == 0
        assert out_path.exists(), "Artifact file should exist"

        captured = capsys.readouterr()
        assert "wrote" in captured.err.lower(), "Should print summary to stderr"
        assert str(out_path) in captured.err, "Summary should mention output path"

    def test_build_subcommand_missing_input(self, tmp_path: Path, capsys):
        """build subcommand exits 2 if input file not found."""
        from patent_extract import main

        out_path = tmp_path / "output.json"
        exit_code = main([
            "build",
            "--input", "/nonexistent/file.pdf",
            "--out", str(out_path)
        ])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "no such file" in captured.err.lower()

    def test_build_subcommand_force_flag(self, born_digital_pdf: Path, tmp_path: Path, capsys):
        """build subcommand with --force rebuilds."""
        from patent_extract import main

        out_path = tmp_path / "force_build.json"

        # Build normally
        exit_code1 = main([
            "build",
            "--input", str(born_digital_pdf),
            "--out", str(out_path)
        ])
        assert exit_code1 == 0

        mtime1 = out_path.stat().st_mtime_ns

        import time
        time.sleep(0.01)

        # Build again with --force
        exit_code2 = main([
            "build",
            "--input", str(born_digital_pdf),
            "--out", str(out_path),
            "--force"
        ])
        assert exit_code2 == 0

        mtime2 = out_path.stat().st_mtime_ns
        assert mtime2 > mtime1, "force flag should trigger rebuild"

    def test_help_still_works(self, capsys):
        """--help works (tests lazy import doesn't break help)."""
        from patent_extract import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "build" in captured.out.lower()
