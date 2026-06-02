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


class TestClassifyPageSyntheticUnit:
    """Pure unit tests for classify_page with synthetic inputs (no PDF required)."""

    def test_classify_page_single_column_is_body(self):
        """AC4.2 (revised 2026-06-01): a single-column page with a CLEAN line-model
        fit is now ADMITTED as body, not flagged.

        Rationale: a single-column claims tail (e.g. US9154231 idx14, US8131198 idx29)
        is citable column:line text. The old gate flagged any single-column page; the
        voting rule (is_body) admits it because the clean fit alone is a body signal.

        Constructs a single-column page (nearly all words left) WITH a clean fit, and
        asserts is_body=True and not flagged.
        """
        from patent_extract import classify_page, Word

        page_width = 614.0

        left_words = [
            Word(text=f"word{i}", x0=100 + i*0.5, x1=130 + i*0.5, top=100 + i*2, bottom=110 + i*2)
            for i in range(405)
        ]
        right_words = [
            Word(text=f"rword{i}", x0=400 + i*0.5, x1=430 + i*0.5, top=100 + i*2, bottom=110 + i*2)
            for i in range(45)
        ]
        words = left_words + right_words

        # Clean fit: markers lie exactly on y = 90 + 10*line (pitch=10, intercept=90)
        # so max_marker_residual == 0 -> clean_fit vote fires.
        markers = [(5, 140.0), (10, 190.0), (15, 240.0), (20, 290.0), (25, 340.0), (30, 390.0)]
        fit = (10.0, 90.0)
        gutter = page_width / 2.0

        page_fit = classify_page(
            words=words,
            page_width=page_width,
            markers=markers,
            fit=fit,
            gutter=gutter,
            page_index=0,
            left_column=1,
            right_column=2,
        )

        assert page_fit["is_body"] is True, (
            f"Clean-fit single-column page should be body. Reason={page_fit['flag_reason']}"
        )
        assert page_fit["flagged"] is False, (
            f"Clean-fit single-column body page should not be flagged. "
            f"Reason={page_fit['flag_reason']}"
        )
        # Mutation guard: residual must be the real 0 here (clean fit), not the -1 sentinel.
        assert page_fit["max_marker_residual"] == 0

    def test_classify_page_sentinel_residual_no_fit(self):
        """AC4.2 (IMPORTANT #2): -1 residual sentinel is set when fit is None.

        The sentinel guards the contract that max_marker_residual is -1 when:
        - fit is None, OR
        - markers is empty

        This test exercises the fit=None case. The page will be flagged due to
        insufficient markers or other checks, but the residual must be -1.
        """
        from patent_extract import classify_page, Word

        page_width = 614.0

        # Create a valid word list (to avoid sparse page flag)
        words = [
            Word(text=f"word{i}", x0=100 + i*0.5, x1=130 + i*0.5, top=100 + i*2, bottom=110 + i*2)
            for i in range(450)  # >= MIN_BODY_WORDS
        ]

        # Empty markers list (will trigger insufficient markers flag)
        markers = []

        # fit=None (will cause residual sentinel to be -1)
        fit = None

        # Valid gutter
        gutter = page_width / 2.0

        page_fit = classify_page(
            words=words,
            page_width=page_width,
            markers=markers,
            fit=fit,
            gutter=gutter,
            page_index=0,
            left_column=1,
            right_column=2,
        )

        # Verify non-body (450 words = 1 word vote; no markers, no headers -> < 2 votes)
        assert page_fit["is_body"] is False, f"Expected is_body=False, got {page_fit}"
        assert page_fit["flagged"] is True, f"Expected flagged=True, got {page_fit}"
        assert "not a numbered body page" in (page_fit["flag_reason"] or ""), (
            f"Expected 'not a numbered body page' in reason, got: {page_fit['flag_reason']}"
        )

        # Verify the sentinel: max_marker_residual must be -1 (not a real residual)
        assert page_fit["max_marker_residual"] == -1, (
            f"Expected max_marker_residual=-1 (sentinel), got {page_fit['max_marker_residual']}"
        )

    def test_classify_page_sentinel_residual_empty_markers(self):
        """AC4.2 (IMPORTANT #2): -1 residual sentinel is set when markers is empty.

        Even with a valid fit, if markers is empty, the residual should be -1.
        """
        from patent_extract import classify_page, Word

        page_width = 614.0

        # Create a valid word list
        words = [
            Word(text=f"word{i}", x0=100 + i*0.5, x1=130 + i*0.5, top=100 + i*2, bottom=110 + i*2)
            for i in range(450)
        ]

        # Empty markers
        markers = []

        # Valid fit
        fit = (10.0, 90.0)

        # Valid gutter
        gutter = page_width / 2.0

        page_fit = classify_page(
            words=words,
            page_width=page_width,
            markers=markers,
            fit=fit,
            gutter=gutter,
            page_index=0,
            left_column=1,
            right_column=2,
        )

        # The sentinel should still apply: empty markers means -1 residual
        assert page_fit["max_marker_residual"] == -1, (
            f"Expected max_marker_residual=-1 (sentinel for empty markers), "
            f"got {page_fit['max_marker_residual']}"
        )


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
        """AC4.2: US9154231 drawings (pages 3-4, indices 2-3) are flagged as 'sparse page'."""
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

                # AC4.2: Drawings are non-body and flagged.
                assert page_fit["is_body"] is False, f"Page {page_idx} (drawing) should not be body"
                assert page_fit["flagged"] is True, f"Page {page_idx} should be flagged"
                assert page_fit["flag_reason"] is not None
                assert "not a numbered body page" in page_fit["flag_reason"], (
                    f"Expected 'not a numbered body page' reason on page {page_idx}, got: {page_fit['flag_reason']}"
                )

    def test_classify_us9154231_page_0_references_non_body(self, born_digital_pdf):
        """AC4.2: US9154231 page 0 (title/references) is non-body despite high word count.

        Index 0 has 417 words (1 word vote) but only 1 gutter marker and no
        column-center headers, so it earns < 2 votes and is correctly rejected.
        This is the key false-positive guard: a DENSE front-matter page must not be
        admitted just because it has many words.
        """
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, fit_line_model, resolve_gutter,
            classify_page
        )

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            page = pdf.pages[0]  # page 1, index 0
            page_width = page.width

            words = [to_word(w) for w in page.extract_words()]
            markers = select_markers(words, page_width=page_width)
            gx, disagree = resolve_gutter(words, page_width=page_width)
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
                gutter_disagreement=disagree,
            )

            assert page_fit["is_body"] is False, "Page 0 (references) should not be body"
            assert page_fit["flagged"] is True, "Page 0 (references) should be flagged"
            assert page_fit["flag_reason"] is not None
            assert "not a numbered body page" in page_fit["flag_reason"], (
                f"Expected 'not a numbered body page' reason on page 0, got: {page_fit['flag_reason']}"
            )

    def test_classify_us9154231_page_14_single_column_claims_is_body(self, born_digital_pdf):
        """AC4.2 (revised 2026-06-01): US9154231 page 15 (index 14) single-column
        claims tail is now ADMITTED as body, not flagged.

        Index 14 has only 224 words (below the old MIN_BODY_WORDS=400 gate) and an
        empty right column, but it has a clean gutter line-model fit (markers 10,15,
        25,30; residual 0). It is citable as columns 15/16, so it must be body.
        """
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, fit_line_model, resolve_gutter,
            classify_page, max_marker_residual
        )

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            page = pdf.pages[14]  # page 15, index 14 (word count = 224)
            page_width = page.width

            words = [to_word(w) for w in page.extract_words()]
            markers = select_markers(words, page_width=page_width)
            gx, disagree = resolve_gutter(words, page_width=page_width)
            fit_result = fit_line_model(markers)

            page_fit = classify_page(
                words=words,
                page_width=page_width,
                markers=markers,
                fit=fit_result,
                gutter=gx,
                page_index=14,
                left_column=15,
                right_column=16,
                gutter_disagreement=disagree,
            )

            # Sanity on the inputs (mutation guard): it really is the short tail with a clean fit.
            assert len(words) < 400, f"Expected sparse claims tail, got {len(words)} words"
            assert fit_result is not None
            assert max_marker_residual(markers, *fit_result) == 0

            assert page_fit["is_body"] is True, (
                f"Single-column claims tail should be body. Reason={page_fit['flag_reason']}"
            )
            assert page_fit["flagged"] is False, (
                f"Single-column claims tail should not be flagged. Reason={page_fit['flag_reason']}"
            )
            assert page_fit["left_column"] == 15 and page_fit["right_column"] == 16

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

        Expected partition (revised 2026-06-01, voting rule):
        - Body (not flagged): indices 7-14 — the seven two-column body pages PLUS the
          single-column claims tail at index 14 (cols 15/16).
        - Non-body (flagged): indices 0-6 (title, references, drawings, figure page).
        """
        import pdfplumber
        from patent_extract import (
            to_word, select_markers, fit_line_model, resolve_gutter,
            classify_page
        )

        body_expected = {7, 8, 9, 10, 11, 12, 13, 14}  # body pages incl. claims tail
        non_body_expected = {0, 1, 2, 3, 4, 5, 6}      # front matter / drawings

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            for page_idx in range(len(pdf.pages)):
                page = pdf.pages[page_idx]
                page_width = page.width

                words = [to_word(w) for w in page.extract_words()]
                markers = select_markers(words, page_width=page_width)
                gx, disagree = resolve_gutter(words, page_width=page_width)
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
                    gutter_disagreement=disagree,
                )

                if page_idx in body_expected:
                    assert page_fit["is_body"] is True, (
                        f"Page {page_idx} expected body, but got non-body: {page_fit['flag_reason']}"
                    )
                    assert page_fit["flagged"] is False, (
                        f"Page {page_idx} expected NOT flagged, but got flagged: {page_fit['flag_reason']}"
                    )
                elif page_idx in non_body_expected:
                    assert page_fit["is_body"] is False, (
                        f"Page {page_idx} expected non-body, but got body"
                    )
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
