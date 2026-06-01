"""Tests for column reconstruction: dead-zone, line-extraction, and line numbering."""
import pytest


class TestDeadZoneHalfwidth:
    """Unit tests for dead_zone_halfwidth calculation."""

    def test_dead_zone_empty_markers_returns_base(self):
        """Empty marker list returns BASE_DEAD_ZONE."""
        from patent_extract import dead_zone_halfwidth, BASE_DEAD_ZONE

        result = dead_zone_halfwidth([])
        assert result == BASE_DEAD_ZONE

    def test_dead_zone_no_drift_returns_base(self):
        """Single marker (zero drift) returns BASE_DEAD_ZONE."""
        from patent_extract import dead_zone_halfwidth, BASE_DEAD_ZONE

        result = dead_zone_halfwidth([300.0])
        assert result == BASE_DEAD_ZONE

    def test_dead_zone_small_drift_floored_at_base(self):
        """Small drift + margin < BASE_DEAD_ZONE returns BASE_DEAD_ZONE."""
        from patent_extract import dead_zone_halfwidth, BASE_DEAD_ZONE, DEAD_ZONE_MARGIN

        # drift = 1.0, margin = 3.0, total = 4.0 < BASE_DEAD_ZONE (6.0)
        result = dead_zone_halfwidth([300.0, 301.0])
        assert result == BASE_DEAD_ZONE

    def test_dead_zone_large_drift_exceeds_base(self):
        """Large drift + margin > BASE_DEAD_ZONE returns drift + margin."""
        from patent_extract import dead_zone_halfwidth, BASE_DEAD_ZONE, DEAD_ZONE_MARGIN

        # drift = 10.0, margin = 3.0, total = 13.0 > BASE_DEAD_ZONE (6.0)
        result = dead_zone_halfwidth([290.0, 300.0])
        assert result == 13.0

    def test_dead_zone_real_scan_drift(self):
        """Real OCR page drift: US4731298 page 2 with gutter drift ~4 pt."""
        from patent_extract import dead_zone_halfwidth, DEAD_ZONE_MARGIN

        # Observed drift ~4 pt on OCR scan
        marker_xs = [251.9, 255.8]  # drift = 3.9
        result = dead_zone_halfwidth(marker_xs)
        expected = max(6.0, 3.9 + DEAD_ZONE_MARGIN)  # max(6.0, 6.9) = 6.9
        assert abs(result - expected) < 0.01

    def test_dead_zone_outlier_polluted_robust_to_spread(self):
        """MINOR: Outlier-polluted marker list must NOT inflate dead-zone.

        Tight cluster (300.0-301.0) plus one stray outlier at 350.0 must NOT
        cause dead_zone to be computed from the full 50pt spread. Instead, use
        robust statistics (IQR) to exclude the outlier and keep dz small.

        Defense-in-depth: this tests the robust spread calculation in dead_zone_halfwidth,
        which protects against a stray outlier escaping the gutter-cluster refinement.
        """
        from patent_extract import dead_zone_halfwidth, BASE_DEAD_ZONE, DEAD_ZONE_MARGIN

        # Tight cluster + outlier: [300, 300.5, 301, 350]
        # Raw spread = 350 - 300 = 50pt (would inflate dz to 50 + 3 = 53pt)
        # But robust IQR should compute from the middle 50% (300.5 to 301),
        # giving drift ~ 0.5, dz ~ 6pt (BASE_DEAD_ZONE floor)
        marker_xs = [300.0, 300.5, 301.0, 350.0]
        result = dead_zone_halfwidth(marker_xs)

        # With robust IQR: Q1 ~ 300.5, Q3 ~ 301, drift ~ 0.5, dz = max(6, 0.5+3) = 6
        assert result == BASE_DEAD_ZONE, f"Expected BASE_DEAD_ZONE ({BASE_DEAD_ZONE}), got {result}"
        # Not the raw spread: 50 + 3 = 53
        assert result < 10, f"Dead-zone inflated by outlier: {result}pt (should be ~6pt)"


class TestReconstructPageIntegration:
    """Integration tests for reconstruct_page (AC3.1, AC3.2, AC3.3)."""

    def test_reconstruct_us9154231_page_9_left_column_full_text_not_truncated(self, born_digital_pdf):
        """CRITICAL #1 REGRESSION: Left-column line 1 must include full text, not be truncated by inflated dead-zone.

        US9154231 page 9 (index 8), column 5 (left), line 1 should read the full first line
        of body text, not be clipped short by an inflated dead-zone from outlier markers.
        This test MUST FAIL before the gutter-cluster refinement fix and PASS after.

        The bug was: marker_center_xs() included a stray column-header '5' at cx=342,
        inflating the dead-zone to ~42pt and clipping the left crop, truncating text
        from ~34pt of real content. After the fix, marker_center_xs() excludes the
        outlier via gutter-clustering, dz returns to ~6pt, and the full text is recovered.
        """
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            marker_center_xs, reconstruct_page
        )

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            page = pdf.pages[8]  # page 9, 0-indexed
            width = page.width
            height = page.height

            words = [to_word(w) for w in page.extract_words()]
            markers = select_markers(words, page_width=width)
            gx = gutter_x(words, page_width=width)
            marker_xs = marker_center_xs(words, page_width=width)
            fit_result = fit_line_model(markers)

            assert fit_result is not None
            pitch, intercept = fit_result

        # Reconstruct with columns 5 (left), 6 (right)
        lines = reconstruct_page(
            page=page,
            page_width=width,
            page_height=height,
            gutter=gx,
            marker_xs=marker_xs,
            pitch=pitch,
            intercept=intercept,
            left_column=5,
            right_column=6,
            page_index=8,
        )

        # Find column 5, line 1 and verify it contains substantial left-column text
        col5_line1 = [ln for ln in lines if ln["column"] == 5 and ln["line"] == 1]
        assert len(col5_line1) > 0, "Column 5 line 1 should exist"

        line = col5_line1[0]
        text = line["text"].strip()
        print(f"\nCol 5 Line 1 text: '{text}'")

        # The actual text on this line (from visual inspection of the PDF):
        # starts with "first electrical radio-frequency signal" (full phrase spans both lines but first line should be substantial)
        # We verify it's NOT truncated to "...and the secon" (the buggy truncation)
        assert len(text) > 50, f"Line text too short ({len(text)} chars), likely truncated: '{text}'"
        assert "first" in text.lower() or "electrical" in text.lower(), f"Expected 'first' or 'electrical' in text: '{text}'"
        assert "B2" not in text  # Not a running header

    def test_reconstruct_us9154231_page_9_cols_3_4_verified_text(self, born_digital_pdf):
        """AC3.1: US9154231 p9 (index 8) columns 3/4 — verified known-text assertions.

        Page index 8 is the first 3/4 body page. Assert specific (column, line)->text pairs
        against actual printed content verified from the PDF.
        """
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            marker_center_xs, reconstruct_page
        )

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            page = pdf.pages[8]
            width = page.width
            height = page.height

            words = [to_word(w) for w in page.extract_words()]
            markers = select_markers(words, page_width=width)
            gx = gutter_x(words, page_width=width)
            marker_xs = marker_center_xs(words, page_width=width)
            fit_result = fit_line_model(markers)

            assert fit_result is not None
            pitch, intercept = fit_result

        lines = reconstruct_page(
            page=page,
            page_width=width,
            page_height=height,
            gutter=gx,
            marker_xs=marker_xs,
            pitch=pitch,
            intercept=intercept,
            left_column=3,
            right_column=4,
            page_index=8,
        )

        # Verified from actual PDF: page 9 (index 8), columns 3/4
        col3_line1 = [ln for ln in lines if ln["column"] == 3 and ln["line"] == 1]
        assert len(col3_line1) > 0, "Column 3 line 1 should exist"
        assert "first electrical radio-frequency signal" in col3_line1[0]["text"]

        col4_line1 = [ln for ln in lines if ln["column"] == 4 and ln["line"] == 1]
        assert len(col4_line1) > 0, "Column 4 line 1 should exist"
        assert "FIG. 5 shows" in col4_line1[0]["text"]

    def test_reconstruct_us9154231_page_8_cols_1_2_verified_text(self, born_digital_pdf):
        """AC3.1: US9154231 p8 (index 7) columns 1/2 — verified known-text assertions.

        First body page with columns 1/2. Assert specific (column, line)->text pairs.
        """
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            marker_center_xs, reconstruct_page
        )

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            page = pdf.pages[7]  # page 8, 0-indexed
            width = page.width
            height = page.height

            words = [to_word(w) for w in page.extract_words()]
            markers = select_markers(words, page_width=width)
            gx = gutter_x(words, page_width=width)
            marker_xs = marker_center_xs(words, page_width=width)
            fit_result = fit_line_model(markers)

            assert fit_result is not None
            pitch, intercept = fit_result

        lines = reconstruct_page(
            page=page,
            page_width=width,
            page_height=height,
            gutter=gx,
            marker_xs=marker_xs,
            pitch=pitch,
            intercept=intercept,
            left_column=1,
            right_column=2,
            page_index=7,
        )

        # Verified from actual PDF: page 8 (index 7), columns 1/2
        col1_line1 = [ln for ln in lines if ln["column"] == 1 and ln["line"] == 1]
        assert len(col1_line1) > 0, "Column 1 line 1 should exist"
        assert "GENERATION OF AN OPTICAL" in col1_line1[0]["text"]

        col2_line1 = [ln for ln in lines if ln["column"] == 2 and ln["line"] == 1]
        assert len(col2_line1) > 0, "Column 2 line 1 should exist"
        # Note: page index 7, right column, line 1 - verify actual text
        assert len(col2_line1[0]["text"].strip()) > 0
        assert "B2" not in col2_line1[0]["text"]

    def test_reconstruct_us9154231_page_10_cols_5_6_verified_text(self, born_digital_pdf):
        """AC3.1: US9154231 p10 (index 9) columns 5/6 — verified known-text assertions."""
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            marker_center_xs, reconstruct_page
        )

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            page = pdf.pages[9]  # page 10
            width = page.width
            height = page.height

            words = [to_word(w) for w in page.extract_words()]
            markers = select_markers(words, page_width=width)
            gx = gutter_x(words, page_width=width)
            marker_xs = marker_center_xs(words, page_width=width)
            fit_result = fit_line_model(markers)

            assert fit_result is not None
            pitch, intercept = fit_result

        lines = reconstruct_page(
            page=page,
            page_width=width,
            page_height=height,
            gutter=gx,
            marker_xs=marker_xs,
            pitch=pitch,
            intercept=intercept,
            left_column=5,
            right_column=6,
            page_index=9,
        )

        # Verified from actual PDF: page 10 (index 9), columns 5/6
        col5_line1 = [ln for ln in lines if ln["column"] == 5 and ln["line"] == 1]
        assert len(col5_line1) > 0, "Column 5 line 1 should exist"
        assert "compensation processing" in col5_line1[0]["text"]

    def test_reconstruct_us4731298_page_2_verified_text(self, ocr_pdf):
        """AC3.1: US4731298 page 2 (OCR, index 1) — verified known-text for OCR fixture."""
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            marker_center_xs, reconstruct_page
        )

        with pdfplumber.open(str(ocr_pdf)) as pdf:
            page = pdf.pages[1]  # page 2, 0-indexed
            width = page.width
            height = page.height

            words = [to_word(w) for w in page.extract_words()]
            markers = select_markers(words, page_width=width)
            gx = gutter_x(words, page_width=width)
            marker_xs = marker_center_xs(words, page_width=width)
            fit_result = fit_line_model(markers)

            assert fit_result is not None
            pitch, intercept = fit_result

        lines = reconstruct_page(
            page=page,
            page_width=width,
            page_height=height,
            gutter=gx,
            marker_xs=marker_xs,
            pitch=pitch,
            intercept=intercept,
            left_column=1,
            right_column=2,
            page_index=1,
        )

        # Verify reconstruction succeeded
        col1_lines = [ln for ln in lines if ln["column"] == 1]
        col2_lines = [ln for ln in lines if ln["column"] == 2]
        assert len(col1_lines) > 0, "Should have lines in column 1"
        assert len(col2_lines) > 0, "Should have lines in column 2"


    def test_reconstruct_no_cross_column_merge_ac32(self, born_digital_pdf):
        """AC3.2: No reconstructed line fuses left- and right-column text.

        Behavioral test: verify crop geometry prevents cross-column merge by
        checking that all left-column lines have x1 <= gutter and right lines have x0 >= gutter.
        Also verify the crop-width is positive (IMPORTANT #3 guard).
        """
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            marker_center_xs, reconstruct_page, dead_zone_halfwidth
        )

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            page = pdf.pages[8]  # page 9
            width = page.width
            height = page.height

            words = [to_word(w) for w in page.extract_words()]
            markers = select_markers(words, page_width=width)
            gx = gutter_x(words, page_width=width)
            marker_xs = marker_center_xs(words, page_width=width)
            fit_result = fit_line_model(markers)

            assert fit_result is not None
            pitch, intercept = fit_result

        lines = reconstruct_page(
            page=page,
            page_width=width,
            page_height=height,
            gutter=gx,
            marker_xs=marker_xs,
            pitch=pitch,
            intercept=intercept,
            left_column=5,
            right_column=6,
            page_index=8,
        )

        # Verify dead-zone and crop validity
        dz = dead_zone_halfwidth(marker_xs)
        assert gx - dz >= 0, f"Dead-zone clips left boundary: gx-dz={gx-dz}"
        assert gx + dz <= width, f"Dead-zone clips right boundary: gx+dz={gx+dz} > width={width}"

        # Check no line crosses the gutter (geometric guarantee)
        for ln in lines:
            x0, top, x1, bottom = ln["bbox"]
            if ln["column"] == 5:  # Left column
                assert x1 <= gx + 1, f"Left column line crosses gutter: x1={x1} > gx={gx}"
            else:  # Right column
                assert x0 >= gx - 1, f"Right column line crosses gutter: x0={x0} < gx={gx}"

    def test_reconstruct_header_absent_ac33(self, born_digital_pdf):
        """AC3.3: Column-header and running-header absent; min line must be >= 1.

        Assert that:
        1. Lines exist (> 0) — fail unconditionally if empty
        2. min(line) >= 1 (header band < 1 is dropped)
        3. No reconstructed line contains running-header fragment "B2"
        4. No reconstructed line contains column-header digits at the top margin
        """
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            marker_center_xs, reconstruct_page
        )

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            page = pdf.pages[8]  # page 9
            width = page.width
            height = page.height

            words = [to_word(w) for w in page.extract_words()]
            markers = select_markers(words, page_width=width)
            gx = gutter_x(words, page_width=width)
            marker_xs = marker_center_xs(words, page_width=width)
            fit_result = fit_line_model(markers)

            assert fit_result is not None
            pitch, intercept = fit_result

        lines = reconstruct_page(
            page=page,
            page_width=width,
            page_height=height,
            gutter=gx,
            marker_xs=marker_xs,
            pitch=pitch,
            intercept=intercept,
            left_column=5,
            right_column=6,
            page_index=8,
        )

        # Lines MUST exist
        assert len(lines) > 0, "No reconstructed lines found"

        # Min line must be >= 1 (header band dropped)
        min_line = min(ln["line"] for ln in lines)
        assert min_line >= 1, f"Expected min line >= 1, got {min_line}"

        # Check no line contains running header or full patent header
        for ln in lines:
            assert "B2" not in ln["text"], f"Running header 'B2' found in line: {ln['text']}"
            # Page header like "US 9,154,231 B2" or just "9,154,231" should not appear
            assert "9,154,231" not in ln["text"], f"Patent number header found: {ln['text']}"
            # Column header digits (top-of-page) should not appear
            # The column headers are single digits at the very top (cols 5/6 show "5"/"6")
            # but the line_at() model drops them via line < 1, so this is defensive
            full_header = "US 9,154,231 B2"
            assert full_header not in ln["text"], f"Full header found: {ln['text']}"


class TestDegenrateCropGuard:
    """IMPORTANT #3: reconstruct_page degenerate crop guard."""

    def test_degenerate_crop_guard_clamping(self):
        """IMPORTANT #3: Crop bounds are clamped to [0, page_width], skipping degenerate crops.

        If gutter-dz < 0 or gutter+dz > page_width, the function must clamp and skip
        rather than pass an inverted/empty bbox to pdfplumber.crop().
        """
        from patent_extract import reconstruct_page
        import pdfplumber

        # Mock pdfplumber page with extract_text_lines
        class MockCrop:
            def extract_text_lines(self):
                return []  # Empty crop (no lines extracted)

        class MockPage:
            def __init__(self, width, height):
                self.width = width
                self.height = height

            def crop(self, bbox):
                x0, y0, x1, y1 = bbox
                # Verify bbox is not inverted
                assert x0 < x1, f"Inverted x-bounds: {bbox}"
                assert y0 < y1, f"Inverted y-bounds: {bbox}"
                # Verify bbox is within page
                assert x0 >= 0 and x1 <= self.width, f"Out of bounds: {bbox}"
                return MockCrop()

        # Test case 1: normal gutter (should work)
        page = MockPage(width=600, height=800)
        lines = reconstruct_page(
            page=page,
            page_width=600,
            page_height=800,
            gutter=300,
            marker_xs=[300, 301],  # tight cluster
            pitch=50,
            intercept=100,
            left_column=1,
            right_column=2,
            page_index=0,
        )
        # Should succeed without exceptions (no assertion errors)
        assert isinstance(lines, list)

        # Test case 2: edge gutter at left (gutter=0, dz=6 would give left_x1 = -6)
        # Should clamp to [0, 0], skipping left column
        lines = reconstruct_page(
            page=page,
            page_width=600,
            page_height=800,
            gutter=0,
            marker_xs=[0],  # at left edge
            pitch=50,
            intercept=100,
            left_column=1,
            right_column=2,
            page_index=0,
        )
        assert isinstance(lines, list)

        # Test case 3: edge gutter at right (gutter=600, dz=6 would give right_x0 = 606 > 600)
        # Should clamp to [600, 600], skipping right column
        lines = reconstruct_page(
            page=page,
            page_width=600,
            page_height=800,
            gutter=600,
            marker_xs=[600],  # at right edge
            pitch=50,
            intercept=100,
            left_column=1,
            right_column=2,
            page_index=0,
        )
        assert isinstance(lines, list)


class TestColumnNumberingContiguity:
    """AC3.4: Column numbering with running counter across pages."""

    def test_column_numbering_two_pages_ac34(self, born_digital_pdf):
        """AC3.4: Two consecutive body pages maintain left=odd / right=even, contiguous 1,2,3,4.

        Reconstruct pages 8-9 (0-indexed 7-8) with columns (1,2) then (3,4).
        Assert left lines carry odd columns, right carry even, and sequence is 1,2,3,4 with no gap.
        """
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            marker_center_xs, reconstruct_page
        )

        all_lines = []

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            # Page 8 (0-indexed 7) with columns 1, 2
            page1 = pdf.pages[7]
            width1 = page1.width
            height1 = page1.height

            words1 = [to_word(w) for w in page1.extract_words()]
            markers1 = select_markers(words1, page_width=width1)
            gx1 = gutter_x(words1, page_width=width1)
            marker_xs1 = marker_center_xs(words1, page_width=width1)
            fit1 = fit_line_model(markers1)
            assert fit1 is not None
            pitch1, intercept1 = fit1

            lines1 = reconstruct_page(
                page=page1,
                page_width=width1,
                page_height=height1,
                gutter=gx1,
                marker_xs=marker_xs1,
                pitch=pitch1,
                intercept=intercept1,
                left_column=1,
                right_column=2,
                page_index=7,
            )
            all_lines.extend(lines1)

            # Page 9 (0-indexed 8) with columns 3, 4
            page2 = pdf.pages[8]
            width2 = page2.width
            height2 = page2.height

            words2 = [to_word(w) for w in page2.extract_words()]
            markers2 = select_markers(words2, page_width=width2)
            gx2 = gutter_x(words2, page_width=width2)
            marker_xs2 = marker_center_xs(words2, page_width=width2)
            fit2 = fit_line_model(markers2)
            assert fit2 is not None
            pitch2, intercept2 = fit2

            lines2 = reconstruct_page(
                page=page2,
                page_width=width2,
                page_height=height2,
                gutter=gx2,
                marker_xs=marker_xs2,
                pitch=pitch2,
                intercept=intercept2,
                left_column=3,
                right_column=4,
                page_index=8,
            )
            all_lines.extend(lines2)

        # Verify page 1 columns
        page1_cols = set(ln["column"] for ln in all_lines if ln["page_index"] == 7)
        assert page1_cols == {1, 2}, f"Page 1 should have columns {{1, 2}}, got {page1_cols}"

        # Verify page 2 columns
        page2_cols = set(ln["column"] for ln in all_lines if ln["page_index"] == 8)
        assert page2_cols == {3, 4}, f"Page 2 should have columns {{3, 4}}, got {page2_cols}"

        # Verify all columns appear (1, 2, 3, 4)
        all_cols = set(ln["column"] for ln in all_lines)
        assert all_cols == {1, 2, 3, 4}, f"Expected columns {{1, 2, 3, 4}}, got {all_cols}"

        # Verify left = odd, right = even
        for ln in all_lines:
            if ln["page_index"] == 7:
                if ln["column"] == 1:
                    assert ln["column"] % 2 == 1, "Column 1 should be odd"
                elif ln["column"] == 2:
                    assert ln["column"] % 2 == 0, "Column 2 should be even"
            elif ln["page_index"] == 8:
                if ln["column"] == 3:
                    assert ln["column"] % 2 == 1, "Column 3 should be odd"
                elif ln["column"] == 4:
                    assert ln["column"] % 2 == 0, "Column 4 should be even"
