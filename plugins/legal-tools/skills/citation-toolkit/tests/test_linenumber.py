"""Tests for patent line numbering: gap measurement and slot classification.

AC1.1, AC1.2: line_gaps_in_pitch
AC2.1, AC2.2: slots_spanned
"""
import pytest


class TestLineGapsInPitch:
    """AC1.1, AC1.2: per-column gap measurement in units of gutter pitch."""

    def test_line_gaps_in_pitch_basic(self):
        """AC1.1: gaps computed as (y[i+1] - y[i]) / pitch, in order."""
        from patent_extract import line_gaps_in_pitch

        # y_centers: 100.0, 110.0, 130.0; pitch=10.0
        # gaps: (110-100)/10=1.0, (130-110)/10=2.0
        result = line_gaps_in_pitch([100.0, 110.0, 130.0], 10.0)
        assert result == [1.0, 2.0]

    def test_line_gaps_in_pitch_empty(self):
        """AC1.2: empty y_centers list returns empty gaps."""
        from patent_extract import line_gaps_in_pitch

        result = line_gaps_in_pitch([], 10.0)
        assert result == []

    def test_line_gaps_in_pitch_single_line(self):
        """AC1.2: single y_center (no gaps) returns empty list."""
        from patent_extract import line_gaps_in_pitch

        result = line_gaps_in_pitch([100.0], 10.0)
        assert result == []

    def test_line_gaps_in_pitch_nonpositive_pitch_raises_error(self):
        """AC1.2: non-positive pitch is a caller bug, raises ValueError."""
        from patent_extract import line_gaps_in_pitch

        with pytest.raises(ValueError):
            line_gaps_in_pitch([100.0, 110.0], 0.0)

        with pytest.raises(ValueError):
            line_gaps_in_pitch([100.0, 110.0], -5.0)

    def test_line_gaps_in_pitch_fractional_pitch(self):
        """Gaps scale proportionally with pitch (pure ratio)."""
        from patent_extract import line_gaps_in_pitch

        # Same y_centers, half the pitch => doubled gap ratios
        result = line_gaps_in_pitch([100.0, 105.0], 5.0)
        assert result == [1.0]

        result = line_gaps_in_pitch([100.0, 105.0], 2.5)
        assert result == [2.0]


class TestSlotsSpanned:
    """AC2.1, AC2.2: map a gap ratio to line slots it spans."""

    def test_slots_spanned_consecutive_1_0(self):
        """AC2.1: gap ratio ~1.0 = 1 line (consecutive)."""
        from patent_extract import slots_spanned

        assert slots_spanned(1.0) == 1

    def test_slots_spanned_one_blank_2_0(self):
        """AC2.1: gap ratio ~2.0 = 2 lines (one blank between)."""
        from patent_extract import slots_spanned

        assert slots_spanned(2.0) == 2

    def test_slots_spanned_tight_0_8(self):
        """AC2.1: tight gap (0.8) rounds to 1 (consecutive)."""
        from patent_extract import slots_spanned

        assert slots_spanned(0.8) == 1

    def test_slots_spanned_sub_one_floored_at_1(self):
        """AC2.1: any gap < 1 is floored at 1 (two lines can't collapse to one slot)."""
        from patent_extract import slots_spanned

        assert slots_spanned(0.4) == 1
        assert slots_spanned(0.1) == 1

    def test_slots_spanned_valley_guard_1_40_is_1(self):
        """AC2.2 valley guard (non-vacuous): gap 1.40 (max consecutive) rounds to 1."""
        from patent_extract import slots_spanned

        # Measured cluster extremes: consecutive 0.76..1.40, one-blank 1.68..2.16.
        # Valley at 1.5 ensures clean separation. If this test breaks, the valley moved.
        assert slots_spanned(1.40) == 1

    def test_slots_spanned_valley_guard_1_68_is_2(self):
        """AC2.2 valley guard (non-vacuous): gap 1.68 (min one-blank) rounds to 2.

        These are the measured cluster extremes, so a future edit that moves the
        valley (e.g., by changing rounding logic) will break this test.
        """
        from patent_extract import slots_spanned

        assert slots_spanned(1.68) == 2

    def test_slots_spanned_rounding_2_4_to_2(self):
        """Rounding is standard: 2.4 < 2.5, rounds to 2."""
        from patent_extract import slots_spanned

        assert slots_spanned(2.4) == 2

    def test_slots_spanned_rounding_2_5_to_2(self):
        """Python's round(2.5) = 2 (banker's rounding)."""
        from patent_extract import slots_spanned

        assert slots_spanned(2.5) == 2

    def test_slots_spanned_rounding_2_6_to_3(self):
        """Rounding: 2.6 > 2.5, rounds to 3."""
        from patent_extract import slots_spanned

        assert slots_spanned(2.6) == 3
