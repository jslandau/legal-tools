"""Tests for the body-page voting rule, column-header gutter detection, and the
tiny single-column claims tail (added 2026-06-01 after US8131198 evidence).

These cover the bootstrapping problem: a short claims page can have ZERO multiple-of-5
gutter line-markers, so the gutter (derived from those markers) is undetectable. The
column-number HEADERS provide an independent geometric anchor (their midpoint == the
gutter), which both rescues classification and supplies the crop gutter.
"""
import pdfplumber

from patent_extract import (
    to_word,
    select_markers,
    fit_line_model,
    gutter_x,
    header_midpoint_gutter,
    column_labels,
    resolve_gutter,
    is_body_page,
    classify_page,
    build_document,
    GUTTER_CROSSCHECK_TOL,
)


# ---------------------------------------------------------------------------
# is_body_page: pure scalar voting decision (no PDF needed)
# ---------------------------------------------------------------------------

class TestIsBodyPageVoting:
    def test_clean_fit_alone_is_body(self):
        # No labels, only 3 markers, few words — but a clean fit (residual 0) admits it.
        assert is_body_page(word_count=0, marker_count=3, label_count=0, fit=(10.0, 0.0), residual=0) is True

    def test_dirty_fit_not_enough_alone(self):
        # A "fit" with high residual does NOT count as clean; with no other votes -> not body.
        assert is_body_page(word_count=0, marker_count=3, label_count=0, fit=(10.0, 0.0), residual=5) is False

    def test_both_headers_alone_is_body(self):
        # Tiny claims tail: zero markers, no fit, few words, but BOTH column headers present.
        assert is_body_page(word_count=63, marker_count=0, label_count=2, fit=None, residual=-1) is True

    def test_one_header_plus_words_is_body(self):
        # One header + enough words = 2 votes.
        assert is_body_page(word_count=150, marker_count=0, label_count=1, fit=None, residual=-1) is True

    def test_one_header_plus_markers_is_body(self):
        assert is_body_page(word_count=10, marker_count=2, label_count=1, fit=None, residual=-1) is True

    def test_dense_front_matter_rejected(self):
        # The crucial false-positive guard: many words but NO markers, NO headers.
        # (US9154231 idx0 "References Cited": 417 words.) One vote only -> not body.
        assert is_body_page(word_count=417, marker_count=1, label_count=0, fit=None, residual=-1) is False

    def test_drawing_page_rejected(self):
        assert is_body_page(word_count=12, marker_count=0, label_count=0, fit=None, residual=-1) is False

    def test_one_header_alone_insufficient(self):
        # A single header with nothing else is one vote — not enough.
        assert is_body_page(word_count=10, marker_count=0, label_count=1, fit=None, residual=-1) is False


# ---------------------------------------------------------------------------
# header_midpoint_gutter + column_labels on the real tiny claims page
# ---------------------------------------------------------------------------

class TestHeaderGutterOnClaimsTail:
    def test_idx29_has_no_line_markers(self, claims_tail_pdf):
        """The premise: the tiny claims tail has zero gutter line-markers, so the
        line-marker gutter is None — the page would be invisible without headers."""
        with pdfplumber.open(str(claims_tail_pdf)) as pdf:
            page = pdf.pages[29]
            words = [to_word(w) for w in page.extract_words()]
            assert select_markers(words, page.width) == []
            assert gutter_x(words, page.width) is None

    def test_idx29_header_midpoint_recovers_gutter(self, claims_tail_pdf):
        """Column headers 33/34 straddle the gutter; their midpoint recovers it
        (~302.9, matching the ~303 gutter on the full body pages)."""
        with pdfplumber.open(str(claims_tail_pdf)) as pdf:
            page = pdf.pages[29]
            words = [to_word(w) for w in page.extract_words()]
            g = header_midpoint_gutter(words, page.width)
            assert g is not None
            assert abs(g - 303.0) < 3.0, f"header-midpoint gutter {g} not near 303"

    def test_idx29_column_labels_counts_both(self, claims_tail_pdf):
        with pdfplumber.open(str(claims_tail_pdf)) as pdf:
            page = pdf.pages[29]
            words = [to_word(w) for w in page.extract_words()]
            g = header_midpoint_gutter(words, page.width)
            assert column_labels(words, page.width, g) == 2

    def test_column_labels_zero_without_gutter(self, claims_tail_pdf):
        """column_labels cannot anchor without a gutter -> 0 (not a crash)."""
        with pdfplumber.open(str(claims_tail_pdf)) as pdf:
            page = pdf.pages[29]
            words = [to_word(w) for w in page.extract_words()]
            assert column_labels(words, page.width, None) == 0

    def test_resolve_gutter_falls_back_to_header(self, claims_tail_pdf):
        with pdfplumber.open(str(claims_tail_pdf)) as pdf:
            page = pdf.pages[29]
            words = [to_word(w) for w in page.extract_words()]
            g, disagree = resolve_gutter(words, page.width)
            assert g is not None and abs(g - 303.0) < 3.0
            assert disagree is False  # only one estimate available


# ---------------------------------------------------------------------------
# resolve_gutter cross-check on full body pages (born-digital and OCR)
# ---------------------------------------------------------------------------

class TestGutterCrossCheck:
    def test_born_digital_estimates_agree(self, claims_tail_pdf):
        """On a normal two-column body page both gutter estimates exist and agree
        well within tolerance (born-digital: < 0.5pt)."""
        with pdfplumber.open(str(claims_tail_pdf)) as pdf:
            page = pdf.pages[14]  # a full two-column body page (cols 3/4)
            words = [to_word(w) for w in page.extract_words()]
            g_line = gutter_x(words, page.width)
            g_hdr = header_midpoint_gutter(words, page.width)
            assert g_line is not None and g_hdr is not None
            assert abs(g_line - g_hdr) <= GUTTER_CROSSCHECK_TOL
            _, disagree = resolve_gutter(words, page.width)
            assert disagree is False

    def test_ocr_estimates_agree_within_tolerance(self, ocr_pdf):
        """OCR scans drift more (~2pt) but still within the 5pt cross-check tolerance,
        so they must NOT be falsely flagged as disagreeing."""
        with pdfplumber.open(str(ocr_pdf)) as pdf:
            for idx in (3, 4):  # OCR body pages with the largest observed drift
                page = pdf.pages[idx]
                words = [to_word(w) for w in page.extract_words()]
                _, disagree = resolve_gutter(words, page.width)
                assert disagree is False, f"OCR page {idx} falsely flagged as gutter-disagreement"

    def test_resolve_prefers_line_marker_when_both_exist(self, claims_tail_pdf):
        """When both estimates exist, the (more precise) line-marker gutter is returned."""
        with pdfplumber.open(str(claims_tail_pdf)) as pdf:
            page = pdf.pages[14]
            words = [to_word(w) for w in page.extract_words()]
            g, _ = resolve_gutter(words, page.width)
            assert g == gutter_x(words, page.width)


# ---------------------------------------------------------------------------
# Whole-document: US8131198 admits the tiny claims tail as cols 33/34
# ---------------------------------------------------------------------------

class TestClaimsTailDocument:
    def test_body_partition_reaches_col_34(self, claims_tail_pdf):
        """Body pages are indices 13-29 (cols 1..34). The tiny claims tail idx29 is body."""
        doc = build_document(claims_tail_pdf)
        body_idx = {pf["page_index"] for pf in doc["page_fits"] if pf["is_body"]}
        assert body_idx == set(range(13, 30)), f"unexpected body partition: {sorted(body_idx)}"

    def test_idx29_is_body_cols_33_34(self, claims_tail_pdf):
        doc = build_document(claims_tail_pdf)
        pf = doc["page_fits"][29]
        assert pf["is_body"] is True
        assert (pf["left_column"], pf["right_column"]) == (33, 34)

    def test_non_body_pages_zeroed(self, claims_tail_pdf):
        doc = build_document(claims_tail_pdf)
        for pf in doc["page_fits"]:
            if not pf["is_body"]:
                assert (pf["left_column"], pf["right_column"]) == (0, 0)

    def test_idx29_lines_with_borrowed_pitch(self, claims_tail_pdf):
        """idx29 is body and consumes cols 33/34 with no line-model (no markers),
        but now uses borrowed pitch from neighboring body pages for numbering.
        It emits Line rows in cols 33/34 with text/unknown kinds only (no blanks,
        no spurious). First text line under each header is line 1."""
        doc = build_document(claims_tail_pdf)
        idx29_lines = [ln for ln in doc["lines"] if ln["page_index"] == 29]

        # Should now have text lines in both columns 33 and 34
        assert len(idx29_lines) > 0, "idx29 should now emit Line rows"

        # Check that max column reaches 34 (cols 33/34 now populated)
        max_col = max(ln["column"] for ln in doc["lines"])
        assert max_col == 34, f"max column should be 34, got {max_col}"

        # Verify kinds are text/unknown only (no blank, no spurious)
        kinds_present = {ln["kind"] for ln in idx29_lines}
        assert kinds_present <= {"text", "unknown"}, \
            f"idx29 marker-less page should only have text/unknown kinds, got {kinds_present}"

        # Verify first text line in each column is line 1 and has correct content (anti-tautology)
        col33_lines = [ln for ln in idx29_lines if ln["column"] == 33 and ln["kind"] == "text"]
        if col33_lines:
            first_line_33 = min(col33_lines, key=lambda ln: ln["line"])
            assert first_line_33["line"] == 1, \
                f"First text line in col 33 should be line 1, got {first_line_33['line']}"
            assert first_line_33["text"].startswith("the shape regardless"), \
                f"Col 33 line 1 should start with 'the shape regardless', got {first_line_33['text'][:50]!r}"
            # Verify header strings are NOT present anywhere in col 33
            forbidden = {"US 8, 13", ",198 B2", "33"}  # Running header, column-number header
            for ln in col33_lines:
                for forbidden_text in forbidden:
                    assert forbidden_text not in ln["text"], \
                        f"Col 33 line {ln['line']} contains forbidden header text {forbidden_text!r}: {ln['text']!r}"

        col34_lines = [ln for ln in idx29_lines if ln["column"] == 34 and ln["kind"] == "text"]
        if col34_lines:
            first_line_34 = min(col34_lines, key=lambda ln: ln["line"])
            assert first_line_34["line"] == 1, \
                f"First text line in col 34 should be line 1, got {first_line_34['line']}"
            # Verify no header strings in col 34 either
            forbidden = {"US 8, 13", ",198 B2", "34"}
            for ln in col34_lines:
                for forbidden_text in forbidden:
                    assert forbidden_text not in ln["text"], \
                        f"Col 34 line {ln['line']} contains forbidden header text {forbidden_text!r}: {ln['text']!r}"
