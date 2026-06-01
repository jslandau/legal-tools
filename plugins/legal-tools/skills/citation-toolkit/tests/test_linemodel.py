"""Tests for linemodel: gutter detection, line fitting, and residual validation."""
import pytest


class TestMarkerLine:
    """Unit tests for _marker_line predicate (single source of truth for marker selection)."""

    def test_marker_line_non_digit_returns_none(self):
        """_marker_line rejects non-digit tokens."""
        from patent_extract import _marker_line

        word = {"text": "hello", "x0": 100.0, "x1": 150.0, "top": 50.0, "bottom": 60.0}
        result = _marker_line(word, page_width=612.0)
        assert result is None

    def test_marker_line_valid_marker_returns_value(self):
        """_marker_line accepts valid marker: multiple of 5, within center band, <= max_line."""
        from patent_extract import _marker_line

        # Page center is 306. Band is ±(0.06 * 612) = ±36.72, so [269.28, 342.72].
        word = {"text": "30", "x0": 295.0, "x1": 315.0, "top": 150.0, "bottom": 160.0}
        result = _marker_line(word, page_width=612.0)
        assert result == 30

    def test_marker_line_off_center_returns_none(self):
        """_marker_line rejects tokens outside center band even if digits."""
        from patent_extract import _marker_line

        # Page center is 306. Band is ±36.72, so token at x=400 is outside.
        word = {"text": "30", "x0": 390.0, "x1": 410.0, "top": 150.0, "bottom": 160.0}
        result = _marker_line(word, page_width=612.0)
        assert result is None

    def test_marker_line_not_multiple_of_five_returns_none(self):
        """_marker_line rejects values not multiple of 5."""
        from patent_extract import _marker_line

        word = {"text": "27", "x0": 295.0, "x1": 315.0, "top": 150.0, "bottom": 160.0}
        result = _marker_line(word, page_width=612.0)
        assert result is None

    def test_marker_line_exceeds_max_line_returns_none(self):
        """_marker_line rejects values > max_line (e.g. body text numbers like 100, 300)."""
        from patent_extract import _marker_line

        word = {"text": "300", "x0": 295.0, "x1": 315.0, "top": 150.0, "bottom": 160.0}
        result = _marker_line(word, page_width=612.0)
        assert result is None

    def test_marker_line_zero_or_negative_returns_none(self):
        """_marker_line rejects zero and negative values."""
        from patent_extract import _marker_line

        word = {"text": "0", "x0": 295.0, "x1": 315.0, "top": 150.0, "bottom": 160.0}
        result = _marker_line(word, page_width=612.0)
        assert result is None

    def test_marker_line_whitespace_stripped(self):
        """_marker_line strips whitespace from text before checking."""
        from patent_extract import _marker_line

        word = {"text": "  30  ", "x0": 295.0, "x1": 315.0, "top": 150.0, "bottom": 160.0}
        result = _marker_line(word, page_width=612.0)
        assert result == 30


class TestSelectMarkers:
    """AC2.2, AC2.3: marker selection excludes outliers and handles missing markers."""

    def test_select_markers_clean_set(self):
        """AC2.2: Valid marker tokens are selected and sorted."""
        from patent_extract import select_markers

        words = [
            {"text": "5", "x0": 295.0, "x1": 315.0, "top": 100.0, "bottom": 110.0},
            {"text": "10", "x0": 295.0, "x1": 315.0, "top": 150.0, "bottom": 160.0},
            {"text": "15", "x0": 295.0, "x1": 315.0, "top": 200.0, "bottom": 210.0},
        ]
        result = select_markers(words, page_width=612.0)

        assert result == [(5, 105.0), (10, 155.0), (15, 205.0)]

    def test_select_markers_excludes_spurious_center_token(self):
        """AC2.2 robustness: outlier token (300) is excluded by max_line bound."""
        from patent_extract import select_markers

        words = [
            {"text": "5", "x0": 295.0, "x1": 315.0, "top": 100.0, "bottom": 110.0},
            {"text": "10", "x0": 295.0, "x1": 315.0, "top": 150.0, "bottom": 160.0},
            {"text": "300", "x0": 295.0, "x1": 315.0, "top": 175.0, "bottom": 185.0},  # Spurious
            {"text": "15", "x0": 295.0, "x1": 315.0, "top": 200.0, "bottom": 210.0},
        ]
        result = select_markers(words, page_width=612.0)

        # 300 excluded by max_line=99
        assert result == [(5, 105.0), (10, 155.0), (15, 205.0)]

    def test_select_markers_missing_line_20(self):
        """AC2.3 robustness: missing marker (line 20) doesn't break fitting."""
        from patent_extract import select_markers

        # Missing line 20, has 5, 10, 15, 25, 30
        words = [
            {"text": "5", "x0": 295.0, "x1": 315.0, "top": 100.0, "bottom": 110.0},
            {"text": "10", "x0": 295.0, "x1": 315.0, "top": 150.0, "bottom": 160.0},
            {"text": "15", "x0": 295.0, "x1": 315.0, "top": 200.0, "bottom": 210.0},
            {"text": "25", "x0": 295.0, "x1": 315.0, "top": 300.0, "bottom": 310.0},
            {"text": "30", "x0": 295.0, "x1": 315.0, "top": 350.0, "bottom": 360.0},
        ]
        result = select_markers(words, page_width=612.0)

        # Missing 20, all others present
        assert len(result) == 5
        assert result == [(5, 105.0), (10, 155.0), (15, 205.0), (25, 305.0), (30, 355.0)]

    def test_select_markers_deduplicates_same_line(self):
        """If the same line value appears twice (rare OCR echo), keep first."""
        from patent_extract import select_markers

        words = [
            {"text": "10", "x0": 295.0, "x1": 315.0, "top": 150.0, "bottom": 160.0},  # First
            {"text": "10", "x0": 296.0, "x1": 314.0, "top": 151.0, "bottom": 159.0},  # Echo, should skip
            {"text": "15", "x0": 295.0, "x1": 315.0, "top": 200.0, "bottom": 210.0},
        ]
        result = select_markers(words, page_width=612.0)

        # Only one (10, ...) entry
        assert len(result) == 2
        assert result[0][0] == 10
        assert result[0][1] == 155.0  # First occurrence


class TestMarkerCenterXs:
    """Test extraction of center-x coordinates of retained markers."""

    def test_marker_center_xs_all_valid(self):
        """marker_center_xs returns center-x of all valid markers."""
        from patent_extract import marker_center_xs

        words = [
            {"text": "5", "x0": 295.0, "x1": 315.0, "top": 100.0, "bottom": 110.0},
            {"text": "10", "x0": 300.0, "x1": 320.0, "top": 150.0, "bottom": 160.0},
            {"text": "15", "x0": 290.0, "x1": 310.0, "top": 200.0, "bottom": 210.0},
        ]
        result = marker_center_xs(words, page_width=612.0)

        # Center-x: (295+315)/2=305, (300+320)/2=310, (290+310)/2=300
        assert result == [305.0, 310.0, 300.0]

    def test_marker_center_xs_excludes_spurious(self):
        """marker_center_xs excludes outliers like body text 300."""
        from patent_extract import marker_center_xs

        words = [
            {"text": "5", "x0": 295.0, "x1": 315.0, "top": 100.0, "bottom": 110.0},
            {"text": "300", "x0": 295.0, "x1": 315.0, "top": 175.0, "bottom": 185.0},  # Spurious
            {"text": "10", "x0": 300.0, "x1": 320.0, "top": 150.0, "bottom": 160.0},
        ]
        result = marker_center_xs(words, page_width=612.0)

        # 300 excluded
        assert result == [305.0, 310.0]


class TestGutterX:
    """Test gutter median computation."""

    def test_gutter_x_median_of_marker_centers(self):
        """gutter_x returns median center-x of retained markers."""
        from patent_extract import gutter_x

        words = [
            {"text": "5", "x0": 300.0, "x1": 320.0, "top": 100.0, "bottom": 110.0},
            {"text": "10", "x0": 302.0, "x1": 322.0, "top": 150.0, "bottom": 160.0},
            {"text": "15", "x0": 298.0, "x1": 318.0, "top": 200.0, "bottom": 210.0},
        ]
        result = gutter_x(words, page_width=612.0)

        # Centers: 310, 312, 308. Median: 310
        assert result == 310.0

    def test_gutter_x_no_markers_returns_none(self):
        """gutter_x returns None if no markers found."""
        from patent_extract import gutter_x

        words = [
            {"text": "hello", "x0": 400.0, "x1": 450.0, "top": 100.0, "bottom": 110.0},
            {"text": "world", "x0": 400.0, "x1": 450.0, "top": 150.0, "bottom": 160.0},
        ]
        result = gutter_x(words, page_width=612.0)

        assert result is None

    def test_gutter_x_even_number_of_centers(self):
        """gutter_x correctly computes median with even count (statistics.median)."""
        from patent_extract import gutter_x

        words = [
            {"text": "5", "x0": 300.0, "x1": 320.0, "top": 100.0, "bottom": 110.0},
            {"text": "10", "x0": 302.0, "x1": 322.0, "top": 150.0, "bottom": 160.0},
        ]
        result = gutter_x(words, page_width=612.0)

        # Centers: 310, 312. Median: 311
        assert result == 311.0


class TestFitLineModel:
    """AC2.1, AC2.5: Theil-Sen fit, residual validation."""

    def test_fit_line_model_minimum_markers(self):
        """fit_line_model requires at least MIN_MARKERS_TO_FIT distinct markers."""
        from patent_extract import fit_line_model, MIN_MARKERS_TO_FIT

        # With only 2 markers
        markers = [(5, 100.0), (10, 110.0)]
        result = fit_line_model(markers)
        assert result is None

        # With MIN_MARKERS_TO_FIT markers, returns a fit
        markers = [(5, 100.0), (10, 110.0), (15, 120.0)]
        result = fit_line_model(markers)
        assert result is not None
        pitch, intercept = result
        assert isinstance(pitch, float)
        assert isinstance(intercept, float)

    def test_fit_line_model_perfect_linear(self):
        """fit_line_model recovers parameters of perfect linear data."""
        from patent_extract import fit_line_model

        # y = 90 + 2*line (pitch=2, intercept=90)
        markers = [(5, 100.0), (10, 110.0), (15, 120.0)]
        pitch, intercept = fit_line_model(markers)

        assert abs(pitch - 2.0) < 1e-9
        assert abs(intercept - 90.0) < 1e-9

    def test_fit_line_model_robust_to_outlier(self):
        """fit_line_model (Theil-Sen) ignores a single outlier."""
        from patent_extract import fit_line_model

        # Clean markers: y = 100 + 2*line
        clean = [(5, 110.0), (10, 120.0), (15, 130.0), (20, 140.0)]
        pitch_clean, intercept_clean = fit_line_model(clean)

        # Add one outlier: (25, 300.0) way off the line
        with_outlier = clean + [(25, 300.0)]
        pitch_out, intercept_out = fit_line_model(with_outlier)

        # Theil-Sen median-of-slopes: should recover clean parameters
        assert abs(pitch_out - pitch_clean) < 0.1
        assert abs(intercept_out - intercept_clean) < 1.0

    def test_fit_line_model_with_missing_marker(self):
        """fit_line_model works with missing markers (e.g. line 20 absent)."""
        from patent_extract import fit_line_model

        # Missing line 20 out of 5,10,15,25,30
        markers = [(5, 100.0), (10, 110.0), (15, 120.0), (25, 140.0), (30, 150.0)]
        result = fit_line_model(markers)

        # Should fit fine even with gap
        assert result is not None
        pitch, intercept = result
        assert abs(pitch - 2.0) < 0.1
        assert abs(intercept - 90.0) < 1.0


class TestLineAt:
    """Test inverse model computation."""

    def test_line_at_recovers_original_line(self):
        """line_at inverts the line model correctly."""
        from patent_extract import line_at

        pitch, intercept = 2.0, 90.0
        for line in [5, 10, 15, 20, 25, 30]:
            y = intercept + line * pitch
            recovered = line_at(y, pitch, intercept)
            assert recovered == line

    def test_line_at_rounds_to_nearest_integer(self):
        """line_at rounds fractional results."""
        from patent_extract import line_at

        pitch, intercept = 2.0, 90.0
        # y = 100.5 -> (100.5 - 90) / 2 = 5.25 -> rounds to 5
        assert line_at(100.5, pitch, intercept) == 5
        # y = 100.6 -> (100.6 - 90) / 2 = 5.3 -> rounds to 5
        assert line_at(100.6, pitch, intercept) == 5
        # y = 101.0 -> (101.0 - 90) / 2 = 5.5 -> rounds to 6 (banker's rounding)
        assert line_at(101.0, pitch, intercept) == 6


class TestMaxMarkerResidual:
    """AC2.5: residual metric correctness."""

    def test_max_marker_residual_zero_for_perfect_fit(self):
        """AC2.5: residual is 0 when all markers lie on the line."""
        from patent_extract import max_marker_residual

        markers = [(5, 100.0), (10, 110.0), (15, 120.0)]
        pitch, intercept = 2.0, 90.0  # y = 90 + 2*line

        residual = max_marker_residual(markers, pitch, intercept)
        assert residual == 0

    def test_max_marker_residual_nonzero_for_bad_fit(self):
        """AC2.5: residual is nonzero when prediction is wrong."""
        from patent_extract import max_marker_residual

        markers = [(5, 100.0), (10, 110.0), (15, 134.0)]  # Last one off the line
        pitch, intercept = 2.0, 90.0  # y = 90 + 2*line

        # For (15, 134.0): predicted line = (134 - 90) / 2 = 22, not 15
        residual = max_marker_residual(markers, pitch, intercept)
        assert residual > 0
        assert residual == max(abs(5 - 5), abs(10 - 10), abs(15 - 22))

    def test_max_marker_residual_detects_consistent_offset(self):
        """AC2.5: residual detects systematic prediction error."""
        from patent_extract import max_marker_residual

        markers = [(5, 100.0), (10, 110.0), (15, 120.0)]
        pitch, intercept = 2.0, 88.0  # y = 88 + 2*line (2 units off)

        residual = max_marker_residual(markers, pitch, intercept)
        # Predictions: (100-88)/2=6, (110-88)/2=11, (120-88)/2=16
        # Errors: |5-6|=1, |10-11|=1, |15-16|=1
        assert residual == 1


class TestLineModelIntegration:
    """AC2.1: Integration tests on real PDF pages."""

    def test_born_digital_page_9_residual_zero(self, born_digital_pdf):
        """AC2.1: US9154231 page 9 fits with residual 0.

        Note: page 9 has a misaligned line-5 marker (off by ~4 lines, likely body text).
        Theil-Sen excludes this outlier from the fit. We validate by checking residual
        on a cleaned marker set (line 5 removed).
        """
        from pathlib import Path
        import pdfplumber
        from patent_extract import to_word, select_markers, fit_line_model, max_marker_residual

        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            page = pdf.pages[8]  # 0-indexed, page 9
            words = [to_word(w) for w in page.extract_words()]
            page_width = page.width

        markers = select_markers(words, page_width=page_width)
        assert len(markers) > 0, "Page 9 should have markers"

        result = fit_line_model(markers)
        assert result is not None, "Page 9 should fit a line model"

        pitch, intercept = result

        # AC2.1: pitch ≈ 9.98 ± 0.05
        assert abs(pitch - 9.984) < 0.05, f"Expected pitch ~9.98, got {pitch}"

        # AC2.1: residual == 0 on clean markers (excluding outlier line 5)
        # Page 9 has a spurious/misaligned "5" (~4 lines off). Exclude it and check residual.
        clean_markers = [(line, y) for line, y in markers if line != 5]
        residual = max_marker_residual(clean_markers, pitch, intercept)
        assert residual == 0, f"Expected residual 0 on clean markers, got {residual}"

    def test_ocr_page_2_residual_zero(self, ocr_pdf):
        """AC2.1: US4731298 page 2 fits with residual 0."""
        from pathlib import Path
        import pdfplumber
        from patent_extract import to_word, select_markers, fit_line_model, max_marker_residual

        with pdfplumber.open(str(ocr_pdf)) as pdf:
            page = pdf.pages[1]  # 0-indexed, page 2
            words = [to_word(w) for w in page.extract_words()]
            page_width = page.width

        markers = select_markers(words, page_width=page_width)
        assert len(markers) > 0, "Page 2 should have markers"

        result = fit_line_model(markers)
        assert result is not None, "Page 2 should fit a line model"

        pitch, intercept = result
        residual = max_marker_residual(markers, pitch, intercept)

        # AC2.1: residual == 0
        assert residual == 0
        # AC2.1: pitch ≈ 9.55 ± 0.05
        assert abs(pitch - 9.552) < 0.05, f"Expected pitch ~9.55, got {pitch}"

    def test_born_digital_body_pages_pitch_stability(self, born_digital_pdf):
        """AC2.4: Pitch is stable across body pages (pages 7-13)."""
        import pdfplumber
        from patent_extract import to_word, select_markers, fit_line_model

        pitches = []
        with pdfplumber.open(str(born_digital_pdf)) as pdf:
            # Body pages: 7-13 (0-indexed: 6-12)
            for page_num in range(6, 13):
                page = pdf.pages[page_num]
                words = [to_word(w) for w in page.extract_words()]

                markers = select_markers(words, page_width=page.width)
                result = fit_line_model(markers)
                if result:
                    pitch, _ = result
                    pitches.append(pitch)

        # Should have several pitches
        assert len(pitches) > 0, "Should extract pitches from body pages"

        # All within ±0.05 of median
        median_pitch = sorted(pitches)[len(pitches) // 2]
        for pitch in pitches:
            assert abs(pitch - median_pitch) < 0.05, f"Pitch {pitch} deviates from median {median_pitch}"

    def test_ocr_body_pages_pitch_stability(self, ocr_pdf):
        """AC2.4: Pitch is stable across OCR body pages (pages 3-5)."""
        import pdfplumber
        from patent_extract import to_word, select_markers, fit_line_model

        pitches = []
        with pdfplumber.open(str(ocr_pdf)) as pdf:
            # OCR body pages: 3, 4, 5 (0-indexed: 2, 3, 4)
            for page_num in range(2, 5):
                page = pdf.pages[page_num]
                words = [to_word(w) for w in page.extract_words()]

                markers = select_markers(words, page_width=page.width)
                result = fit_line_model(markers)
                if result:
                    pitch, _ = result
                    pitches.append(pitch)

        # Should have several pitches
        assert len(pitches) > 0, "Should extract pitches from OCR body pages"

        # All within ±0.05 of median
        median_pitch = sorted(pitches)[len(pitches) // 2]
        for pitch in pitches:
            assert abs(pitch - median_pitch) < 0.05, f"Pitch {pitch} deviates from median {median_pitch}"


class TestRobustnessAndMissingMarkers:
    """AC2.2, AC2.3: Extended robustness tests."""

    def test_spurious_outlier_y_in_marker_list(self):
        """AC2.2 outlier: inject spurious y value, Theil-Sen recovers clean fit."""
        from patent_extract import fit_line_model, max_marker_residual

        # Clean markers
        clean = [(5, 100.0), (10, 110.0), (15, 120.0), (20, 130.0)]
        pitch_clean, intercept_clean = fit_line_model(clean)
        residual_clean = max_marker_residual(clean, pitch_clean, intercept_clean)
        assert residual_clean == 0

        # Inject outlier: move one marker's y way off
        with_outlier = [(5, 100.0), (10, 110.0), (15, 150.0), (20, 130.0)]
        pitch_out, intercept_out = fit_line_model(with_outlier)
        residual_out = max_marker_residual(clean, pitch_out, intercept_out)

        # Theil-Sen should recover nearly the same pitch/intercept from the outlier list
        # when tested against the clean markers
        assert abs(pitch_out - pitch_clean) < 0.2
        assert residual_out == 0

    def test_missing_marker_still_fits(self):
        """AC2.3: Drop a marker, fit still works and residual is 0 for remaining."""
        from patent_extract import fit_line_model, max_marker_residual

        # Full set: 5, 10, 15, 20, 25, 30
        full = [(5, 100.0), (10, 110.0), (15, 120.0), (20, 130.0), (25, 140.0), (30, 150.0)]
        pitch_full, intercept_full = fit_line_model(full)

        # Drop line 20
        partial = [(5, 100.0), (10, 110.0), (15, 120.0), (25, 140.0), (30, 150.0)]
        pitch_partial, intercept_partial = fit_line_model(partial)

        # Both should fit
        assert pitch_full is not None
        assert pitch_partial is not None

        # Residual on partial should be 0 (all remaining markers on line)
        residual_partial = max_marker_residual(partial, pitch_partial, intercept_partial)
        assert residual_partial == 0
