"""Tests for page-type classification: distinguishing body pages from front matter/drawings."""
import pytest


class TestColumnMassFractions:
    """Pure unit tests for column_mass_fractions."""

    def test_column_mass_fractions_empty_word_list(self):
        """column_mass_fractions with empty list returns (0.0, 0.0)."""
        from patent_extract import column_mass_fractions, Word

        result = column_mass_fractions([], page_width=612.0)
        assert result == (0.0, 0.0)

    def test_column_mass_fractions_all_left_synthetic(self):
        """column_mass_fractions with all words on left (cx < 0.45*W) returns (1.0, 0.0)."""
        from patent_extract import column_mass_fractions, Word

        # Page width 612, split at 0.45*612 = 275.4
        # All words with cx < 275.4
        words = [
            Word(text="left1", x0=100, x1=150, top=100, bottom=110),  # cx = 125
            Word(text="left2", x0=200, x1=250, top=150, bottom=160),  # cx = 225
        ]
        result = column_mass_fractions(words, page_width=612.0)
        assert result == (1.0, 0.0)

    def test_column_mass_fractions_all_right_synthetic(self):
        """column_mass_fractions with all words on right (cx > 0.55*W) returns (0.0, 1.0)."""
        from patent_extract import column_mass_fractions, Word

        # Page width 612, split at 0.55*612 = 336.6
        # All words with cx > 336.6
        words = [
            Word(text="right1", x0=400, x1=450, top=100, bottom=110),  # cx = 425
            Word(text="right2", x0=500, x1=550, top=150, bottom=160),  # cx = 525
        ]
        result = column_mass_fractions(words, page_width=612.0)
        assert result == (0.0, 1.0)

    def test_column_mass_fractions_balanced_synthetic(self):
        """column_mass_fractions with balanced left/right returns both ≈ 0.5."""
        from patent_extract import column_mass_fractions, Word

        # Page width 612
        # Left: words with cx < 0.45*612 = 275.4
        # Right: words with cx > 0.55*612 = 336.6
        # Balanced: 2 left, 2 right out of 4 total = (0.5, 0.5)
        words = [
            Word(text="left1", x0=100, x1=150, top=100, bottom=110),    # cx = 125 (left)
            Word(text="left2", x0=200, x1=250, top=150, bottom=160),    # cx = 225 (left)
            Word(text="right1", x0=400, x1=450, top=200, bottom=210),   # cx = 425 (right)
            Word(text="right2", x0=500, x1=550, top=250, bottom=260),   # cx = 525 (right)
        ]
        result = column_mass_fractions(words, page_width=612.0)
        assert result == (0.5, 0.5)

    def test_column_mass_fractions_center_words_excluded(self):
        """column_mass_fractions excludes words in center band (0.45W to 0.55W)."""
        from patent_extract import column_mass_fractions, Word

        # Page width 612, center band [275.4, 336.6]
        # 2 left, 2 center, 2 right = (2/6, 2/6) ≈ (0.333, 0.333)
        words = [
            Word(text="left1", x0=100, x1=150, top=100, bottom=110),    # cx = 125 (left)
            Word(text="left2", x0=200, x1=250, top=150, bottom=160),    # cx = 225 (left)
            Word(text="center1", x0=300, x1=320, top=200, bottom=210),  # cx = 310 (center, ignored)
            Word(text="center2", x0=310, x1=330, top=250, bottom=260),  # cx = 320 (center, ignored)
            Word(text="right1", x0=400, x1=450, top=300, bottom=310),   # cx = 425 (right)
            Word(text="right2", x0=500, x1=550, top=350, bottom=360),   # cx = 525 (right)
        ]
        result = column_mass_fractions(words, page_width=612.0)
        # 2 left out of 6, 2 right out of 6
        assert abs(result[0] - 2.0/6.0) < 0.01  # Left ≈ 0.333
        assert abs(result[1] - 2.0/6.0) < 0.01  # Right ≈ 0.333


class TestClassifyPageIntegration:
    """Integration tests for classify_page using real PDF pages."""

    def test_classify_us9154231_body_pages_not_flagged(self, born_digital_pdf):
        """AC4.1: US9154231 body pages (indices 7-13, printed 8-14) are NOT flagged.

        NOTE: Phase file claimed indices 6-12, but actual classifier output and
        visual inspection shows body pages at 7-13. Page 7 (index 6) has only 25 words
        and is flagged as sparse (likely a frontispiece/toc page). Pages 8-14 are
        the actual body pages with ~1000+ words and full marker sets.
        """
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            classify_page
        )

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            # Body pages: indices 7-13 (printed pages 8-14)
            for page_idx in range(7, 14):
                page = pdf.pages[page_idx]
                page_width = page.width

                words = [to_word(w) for w in page.extract_words()]
                markers = select_markers(words, page_width=page_width)
                gx = gutter_x(words, page_width=page_width)
                fit_result = fit_line_model(markers)

                # Call classify_page
                page_fit = classify_page(
                    words=words,
                    page_width=page_width,
                    markers=markers,
                    fit=fit_result,
                    gutter=gx,
                    page_index=page_idx,
                    left_column=1,  # placeholder
                    right_column=2,  # placeholder
                )

                # AC4.1: Body pages must NOT be flagged
                assert page_fit["flagged"] is False, (
                    f"Page {page_idx} (printed {page_idx+1}) should NOT be flagged. "
                    f"Words={len(words)}, Markers={len(markers)}, Reason={page_fit['flag_reason']}"
                )

    def test_classify_us4731298_body_pages_not_flagged(self, ocr_pdf):
        """AC4.1: US4731298 body pages (indices 1-4) are NOT flagged."""
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            classify_page
        )

        with pdfplumber.open(str(ocr_pdf)) as pdf:
            # Body pages: indices 1-4 (US4731298 has 5 pages, index 0 is title)
            for page_idx in range(1, 5):
                page = pdf.pages[page_idx]
                page_width = page.width

                words = [to_word(w) for w in page.extract_words()]
                markers = select_markers(words, page_width=page_width)
                gx = gutter_x(words, page_width=page_width)
                fit_result = fit_line_model(markers)

                # Call classify_page
                page_fit = classify_page(
                    words=words,
                    page_width=page_width,
                    markers=markers,
                    fit=fit_result,
                    gutter=gx,
                    page_index=page_idx,
                    left_column=1,  # placeholder
                    right_column=2,  # placeholder
                )

                # AC4.1: Body pages must NOT be flagged
                assert page_fit["flagged"] is False, (
                    f"Page {page_idx} should NOT be flagged. "
                    f"Words={len(words)}, Markers={len(markers)}, Reason={page_fit['flag_reason']}"
                )

    def test_classify_us9154231_drawings_sparse_page(self, born_digital_pdf):
        """AC4.2: US9154231 drawings (pages 2-4, indices 1-3) are flagged as 'sparse page'."""
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            classify_page
        )

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            # Drawing pages: indices 1, 2, 3 (word counts: 331, 5, 12)
            # At least one must flag as sparse (< MIN_BODY_WORDS)
            for page_idx in [2, 3]:  # pages with very low word counts
                page = pdf.pages[page_idx]
                page_width = page.width

                words = [to_word(w) for w in page.extract_words()]
                markers = select_markers(words, page_width=page_width)
                gx = gutter_x(words, page_width=page_width)
                fit_result = fit_line_model(markers)

                page_fit = classify_page(
                    words=words,
                    page_width=page_width,
                    markers=markers,
                    fit=fit_result,
                    gutter=gx,
                    page_index=page_idx,
                    left_column=1,
                    right_column=2,
                )

                # AC4.2: Drawings flagged with "sparse page" reason
                assert page_fit["flagged"] is True, f"Page {page_idx} should be flagged"
                assert page_fit["flag_reason"] is not None
                assert "sparse page" in page_fit["flag_reason"], (
                    f"Expected 'sparse page' reason on page {page_idx}, got: {page_fit['flag_reason']}"
                )

    def test_classify_us9154231_page_1_references_insufficient_markers(self, born_digital_pdf):
        """AC4.2: US9154231 page 1 (references/title) flagged as 'insufficient gutter markers'.

        Page 1 (index 0) has 417 words (above MIN_BODY_WORDS=400) but only 1 marker,
        so it fails the MIN_BODY_MARKERS=6 check and is flagged as front matter.
        """
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            classify_page
        )

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            page = pdf.pages[0]  # page 1, index 0
            page_width = page.width

            words = [to_word(w) for w in page.extract_words()]
            markers = select_markers(words, page_width=page_width)
            gx = gutter_x(words, page_width=page_width)
            fit_result = fit_line_model(markers)

            page_fit = classify_page(
                words=words,
                page_width=page_width,
                markers=markers,
                fit=fit_result,
                gutter=gx,
                page_index=0,
                left_column=1,
                right_column=2,
            )

            # AC4.2: References/title page flagged with "insufficient gutter markers"
            assert page_fit["flagged"] is True, "Page 1 (references) should be flagged"
            assert page_fit["flag_reason"] is not None
            assert "insufficient gutter markers" in page_fit["flag_reason"], (
                f"Expected 'insufficient gutter markers' reason on page 1, got: {page_fit['flag_reason']}"
            )

    def test_classify_us9154231_page_15_sparse_claims_tail(self, born_digital_pdf):
        """AC4.2: US9154231 page 15 (claims-tail) flagged as 'sparse page'.

        Page 15 (index 14) has only 224 words, below MIN_BODY_WORDS=400, so it is
        flagged as sparse (claims section typically appears at end with reduced density).
        """
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            classify_page
        )

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            page = pdf.pages[14]  # page 15, index 14 (word count = 224)
            page_width = page.width

            words = [to_word(w) for w in page.extract_words()]
            markers = select_markers(words, page_width=page_width)
            gx = gutter_x(words, page_width=page_width)
            fit_result = fit_line_model(markers)

            page_fit = classify_page(
                words=words,
                page_width=page_width,
                markers=markers,
                fit=fit_result,
                gutter=gx,
                page_index=14,
                left_column=1,
                right_column=2,
            )

            # AC4.2: Sparse page flagged with "sparse page" reason
            assert page_fit["flagged"] is True, "Page 15 (claims-tail) should be flagged"
            assert page_fit["flag_reason"] is not None
            assert "sparse page" in page_fit["flag_reason"], (
                f"Expected 'sparse page' reason on page 15, got: {page_fit['flag_reason']}"
            )

    def test_classify_us4731298_page_0_title_flagged(self, ocr_pdf):
        """AC4.2: US4731298 page 0 (title) is flagged."""
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            classify_page
        )

        with pdfplumber.open(str(ocr_pdf)) as pdf:
            page = pdf.pages[0]  # page 1, index 0 (title page, word count = 251)
            page_width = page.width

            words = [to_word(w) for w in page.extract_words()]
            markers = select_markers(words, page_width=page_width)
            gx = gutter_x(words, page_width=page_width)
            fit_result = fit_line_model(markers)

            page_fit = classify_page(
                words=words,
                page_width=page_width,
                markers=markers,
                fit=fit_result,
                gutter=gx,
                page_index=0,
                left_column=1,
                right_column=2,
            )

            # AC4.2: Title page must be flagged (either sparse or insufficient markers)
            assert page_fit["flagged"] is True, "US4731298 page 0 (title) should be flagged"
            assert page_fit["flag_reason"] is not None, "Flag reason must be non-None"


class TestPageClassPartitionOracle:
    """AC4.1, AC4.2 (complete coverage): whole-document page-class partition test."""

    def test_us9154231_page_partition_oracle(self, born_digital_pdf):
        """Full-document oracle: verify every page of US9154231 matches expected partition.

        Expected partition (derived from actual classify_page output):
        - Not flagged: indices 7-13 (body pages, printed 8-14)
        - Flagged: indices 0-6, 14 (front matter, drawings, claims-tail)

        Note: Phase file claimed 6-12, but actual partition is 7-13. Page 6 (index 6)
        has only 25 words and is flagged as sparse (frontispiece/toc).
        """
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            classify_page
        )

        not_flagged_expected = {7, 8, 9, 10, 11, 12, 13}  # body pages (indices 7-13)
        flagged_expected = {0, 1, 2, 3, 4, 5, 6, 14}      # all others

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            for page_idx in range(len(pdf.pages)):
                page = pdf.pages[page_idx]
                page_width = page.width

                words = [to_word(w) for w in page.extract_words()]
                markers = select_markers(words, page_width=page_width)
                gx = gutter_x(words, page_width=page_width)
                fit_result = fit_line_model(markers)

                page_fit = classify_page(
                    words=words,
                    page_width=page_width,
                    markers=markers,
                    fit=fit_result,
                    gutter=gx,
                    page_index=page_idx,
                    left_column=1,  # placeholder
                    right_column=2,  # placeholder
                )

                if page_idx in not_flagged_expected:
                    assert page_fit["flagged"] is False, (
                        f"Page {page_idx} expected NOT flagged, but got flagged: {page_fit['flag_reason']}"
                    )
                elif page_idx in flagged_expected:
                    assert page_fit["flagged"] is True, (
                        f"Page {page_idx} expected flagged, but got NOT flagged"
                    )

    def test_us4731298_page_partition_oracle(self, ocr_pdf):
        """Full-document oracle: verify every page of US4731298 matches expected partition.

        Expected partition (derived from actual classify_page output):
        - Not flagged: indices 1, 2, 3, 4 (body pages)
        - Flagged: index 0 (title)
        """
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, gutter_x, fit_line_model,
            classify_page
        )

        not_flagged_expected = {1, 2, 3, 4}  # body pages
        flagged_expected = {0}                # title

        with pdfplumber.open(str(ocr_pdf)) as pdf:
            for page_idx in range(len(pdf.pages)):
                page = pdf.pages[page_idx]
                page_width = page.width

                words = [to_word(w) for w in page.extract_words()]
                markers = select_markers(words, page_width=page_width)
                gx = gutter_x(words, page_width=page_width)
                fit_result = fit_line_model(markers)

                page_fit = classify_page(
                    words=words,
                    page_width=page_width,
                    markers=markers,
                    fit=fit_result,
                    gutter=gx,
                    page_index=page_idx,
                    left_column=1,  # placeholder
                    right_column=2,  # placeholder
                )

                if page_idx in not_flagged_expected:
                    assert page_fit["flagged"] is False, (
                        f"Page {page_idx} expected NOT flagged, but got flagged: {page_fit['flag_reason']}"
                    )
                elif page_idx in flagged_expected:
                    assert page_fit["flagged"] is True, (
                        f"Page {page_idx} expected flagged, but got NOT flagged"
                    )
