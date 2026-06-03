"""Cross-fixture regression tests for patent line numbering.

Phase 4 Task 2: Comprehensive regression assertions over all three patent fixtures
(US9154231, US8131198, US4731298) verifying numbering invariants, contiguity,
kind correctness, query round-trip, and collision-free line numbering.

Key invariants tested:
1. Line numbers per column are strictly increasing (sorted, no duplicates)
2. Marker-bearing columns emit contiguous slots 1..max_line (no gaps)
3. Marker-less columns may have interior unknown/blank slots but remain contiguous
4. Every line's kind is in LINE_KINDS
5. text != "" iff kind == "text" (text content correlates with kind)
6. Column counter reaches expected max per fixture
7. No (page_index, column, line) collisions across the document
8. Query round-trip: text-slot cites resolve to non-empty text
9. Documented spurious/blank/ambiguous cases behave as specified
"""

import pytest
from collections import defaultdict
from pathlib import Path


@pytest.fixture(scope="module")
def all_fixtures() -> dict[str, dict]:
    """Build all three fixtures once per module to avoid rebuild cost (~30-60s each).

    Returns:
        {
            "US9154231": PatentDoc,
            "US8131198": PatentDoc,
            "US4731298": PatentDoc,
        }
    """
    from patent_extract import build_document, write_document, load_document
    import tempfile

    fixtures_dir = Path(__file__).resolve().parent.parent / "test_fixtures"
    fixtures = {}

    # US9154231 — born-digital; highest line-bearing column is 15 (the claims
    # tail page is allocated cols 15/16 but col 16 is empty — see test_max_column_us9)
    pdf_9154231 = fixtures_dir / "US9154231.pdf"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        artifact_path = tmp_path / "us9.json"
        doc = build_document(pdf_9154231)
        write_document(doc, artifact_path)
        fixtures["US9154231"] = load_document(artifact_path)

    # US8131198 — born-digital with marker-less claims tail, max column 34
    pdf_8131198 = fixtures_dir / "US8131198.pdf"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        artifact_path = tmp_path / "us8.json"
        doc = build_document(pdf_8131198)
        write_document(doc, artifact_path)
        fixtures["US8131198"] = load_document(artifact_path)

    # US4731298 — OCR scan, max column 8, all columns CLEAN and marker-bearing
    pdf_4731298 = fixtures_dir / "US4731298.pdf"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        artifact_path = tmp_path / "us4.json"
        doc = build_document(pdf_4731298)
        write_document(doc, artifact_path)
        fixtures["US4731298"] = load_document(artifact_path)

    return fixtures


class TestRegressionNumberingInvariants:
    """Verify numbering invariants across all three fixtures."""

    def test_monotonicity_and_no_duplicates_us9(self, all_fixtures: dict[str, dict]):
        """AC11.1: Line numbers per column are strictly increasing (sorted, no duplicates).

        For US9154231, every column's emitted lines must have line numbers in
        strictly ascending order with no repeats.
        """
        from patent_extract import LINE_KINDS

        doc = all_fixtures["US9154231"]

        # Group lines by column
        col_to_lines = defaultdict(list)
        for line in doc["lines"]:
            col_to_lines[line["column"]].append(line)

        # For each column, check monotonicity and no duplicates
        for col_num in sorted(col_to_lines.keys()):
            lines = col_to_lines[col_num]
            line_nums = [l["line"] for l in lines]

            # Check strictly increasing
            assert line_nums == sorted(line_nums), (
                f"Column {col_num}: line numbers not sorted: {line_nums[:20]}"
            )

            # Check no duplicates
            assert len(line_nums) == len(set(line_nums)), (
                f"Column {col_num}: duplicate line numbers found"
            )

    def test_monotonicity_and_no_duplicates_us8(self, all_fixtures: dict[str, dict]):
        """AC11.1: Line monotonicity and no duplicates on US8131198."""
        doc = all_fixtures["US8131198"]

        col_to_lines = defaultdict(list)
        for line in doc["lines"]:
            col_to_lines[line["column"]].append(line)

        for col_num in sorted(col_to_lines.keys()):
            lines = col_to_lines[col_num]
            line_nums = [l["line"] for l in lines]

            assert line_nums == sorted(line_nums), (
                f"US8131198 Column {col_num}: line numbers not sorted"
            )
            assert len(line_nums) == len(set(line_nums)), (
                f"US8131198 Column {col_num}: duplicate line numbers found"
            )

    def test_monotonicity_and_no_duplicates_us4(self, all_fixtures: dict[str, dict]):
        """AC11.1: Line monotonicity and no duplicates on US4731298."""
        doc = all_fixtures["US4731298"]

        col_to_lines = defaultdict(list)
        for line in doc["lines"]:
            col_to_lines[line["column"]].append(line)

        for col_num in sorted(col_to_lines.keys()):
            lines = col_to_lines[col_num]
            line_nums = [l["line"] for l in lines]

            assert line_nums == sorted(line_nums), (
                f"US4731298 Column {col_num}: line numbers not sorted"
            )
            assert len(line_nums) == len(set(line_nums)), (
                f"US4731298 Column {col_num}: duplicate line numbers found"
            )

    def test_contiguity_marker_bearing_us9(self, all_fixtures: dict[str, dict]):
        """AC11.1: Marker-bearing columns emit contiguous slots 1..max_line.

        US9154231 has all marker-bearing columns. Every column should have
        all line numbers from 1 to its max with no gaps (internal unknown/spurious
        slots are still present as rows with empty text, they just don't break
        contiguity).
        """
        doc = all_fixtures["US9154231"]

        col_to_lines = defaultdict(list)
        for line in doc["lines"]:
            col_to_lines[line["column"]].append(line)

        for col_num in sorted(col_to_lines.keys()):
            lines = col_to_lines[col_num]
            line_nums = sorted([l["line"] for l in lines])

            if line_nums:
                min_line, max_line = min(line_nums), max(line_nums)
                expected_range = set(range(min_line, max_line + 1))
                actual_set = set(line_nums)

                assert actual_set == expected_range, (
                    f"US9154231 Column {col_num}: gaps in line numbers. "
                    f"Expected {min_line}..{max_line} contiguous, "
                    f"got gaps {sorted(expected_range - actual_set)}"
                )

    def test_contiguity_marker_bearing_us8(self, all_fixtures: dict[str, dict]):
        """AC11.1: US8131198 marker-bearing columns (non-tail) are contiguous.

        US8131198 has marker-bearing columns 1-32 and marker-less tail cols 33/34
        on page 29. The marker-bearing columns should be fully contiguous.
        """
        doc = all_fixtures["US8131198"]

        col_to_lines = defaultdict(list)
        for line in doc["lines"]:
            col_to_lines[line["column"]].append(line)

        # Marker-bearing columns: 1-32 (columns 33/34 are marker-less)
        for col_num in range(1, 33):
            if col_num not in col_to_lines:
                continue  # Column may not appear in every fixture

            lines = col_to_lines[col_num]
            line_nums = sorted([l["line"] for l in lines])

            if line_nums:
                min_line, max_line = min(line_nums), max(line_nums)
                expected_range = set(range(min_line, max_line + 1))
                actual_set = set(line_nums)

                assert actual_set == expected_range, (
                    f"US8131198 Column {col_num} (marker-bearing): gaps in line numbers"
                )

    def test_contiguity_marker_less_us8(self, all_fixtures: dict[str, dict]):
        """AC11.1: US8131198 marker-less columns (33/34) are still contiguous slot-wise.

        Marker-less columns may have interior unknown slots, but the slot numbers
        themselves must be contiguous (the unknown rows are still present in the
        artifact filling the gaps).
        """
        doc = all_fixtures["US8131198"]

        col_to_lines = defaultdict(list)
        for line in doc["lines"]:
            col_to_lines[line["column"]].append(line)

        # Marker-less columns: 33/34 (page 29, claims tail)
        for col_num in [33, 34]:
            if col_num not in col_to_lines:
                continue

            lines = col_to_lines[col_num]
            line_nums = sorted([l["line"] for l in lines])

            if line_nums:
                min_line, max_line = min(line_nums), max(line_nums)
                expected_range = set(range(min_line, max_line + 1))
                actual_set = set(line_nums)

                assert actual_set == expected_range, (
                    f"US8131198 Column {col_num} (marker-less): "
                    f"gaps in line numbers even with unknown slots"
                )

    def test_contiguity_marker_bearing_us4(self, all_fixtures: dict[str, dict]):
        """AC11.1: US4731298 all columns are marker-bearing and CLEAN.

        All 8 columns are fully contiguous with no gaps.
        """
        doc = all_fixtures["US4731298"]

        col_to_lines = defaultdict(list)
        for line in doc["lines"]:
            col_to_lines[line["column"]].append(line)

        for col_num in sorted(col_to_lines.keys()):
            lines = col_to_lines[col_num]
            line_nums = sorted([l["line"] for l in lines])

            if line_nums:
                min_line, max_line = min(line_nums), max(line_nums)
                expected_range = set(range(min_line, max_line + 1))
                actual_set = set(line_nums)

                assert actual_set == expected_range, (
                    f"US4731298 Column {col_num}: gaps found (all columns should "
                    f"be marker-bearing and contiguous)"
                )

    def test_kind_validity_us9(self, all_fixtures: dict[str, dict]):
        """AC11.1: Every line's kind is in LINE_KINDS."""
        from patent_extract import LINE_KINDS

        doc = all_fixtures["US9154231"]
        valid_kinds = set(LINE_KINDS)

        for line in doc["lines"]:
            assert line["kind"] in valid_kinds, (
                f"US9154231 line (col {line['column']} line {line['line']}): "
                f"kind {line['kind']} not in {valid_kinds}"
            )

    def test_kind_validity_us8(self, all_fixtures: dict[str, dict]):
        """AC11.1: Every line's kind is in LINE_KINDS on US8131198."""
        from patent_extract import LINE_KINDS

        doc = all_fixtures["US8131198"]
        valid_kinds = set(LINE_KINDS)

        for line in doc["lines"]:
            assert line["kind"] in valid_kinds, (
                f"US8131198 line (col {line['column']} line {line['line']}): "
                f"kind {line['kind']} not in {valid_kinds}"
            )

    def test_kind_validity_us4(self, all_fixtures: dict[str, dict]):
        """AC11.1: Every line's kind is in LINE_KINDS on US4731298."""
        from patent_extract import LINE_KINDS

        doc = all_fixtures["US4731298"]
        valid_kinds = set(LINE_KINDS)

        for line in doc["lines"]:
            assert line["kind"] in valid_kinds, (
                f"US4731298 line (col {line['column']} line {line['line']}): "
                f"kind {line['kind']} not in {valid_kinds}"
            )

    def test_text_kind_invariant_us9(self, all_fixtures: dict[str, dict]):
        """AC11.1: text != "" iff kind == "text" (text content correlates with kind).

        This is a critical invariant: text rows have non-empty text; blank/spurious/unknown
        rows have empty text.
        """
        doc = all_fixtures["US9154231"]

        bad_lines = []
        for line in doc["lines"]:
            text_empty = line["text"] == ""
            is_text_kind = line["kind"] == "text"

            # Invariant: text_empty should be opposite of is_text_kind
            if text_empty == is_text_kind:  # Same value = broken
                bad_lines.append(line)

        assert len(bad_lines) == 0, (
            f"US9154231: {len(bad_lines)} lines violate text != '' iff kind == 'text'. "
            f"Examples: {bad_lines[:3]}"
        )

    def test_text_kind_invariant_us8(self, all_fixtures: dict[str, dict]):
        """AC11.1: text != "" iff kind == "text" on US8131198."""
        doc = all_fixtures["US8131198"]

        bad_lines = []
        for line in doc["lines"]:
            text_empty = line["text"] == ""
            is_text_kind = line["kind"] == "text"

            if text_empty == is_text_kind:
                bad_lines.append(line)

        assert len(bad_lines) == 0, (
            f"US8131198: {len(bad_lines)} lines violate invariant. "
            f"Examples: {bad_lines[:3]}"
        )

    def test_text_kind_invariant_us4(self, all_fixtures: dict[str, dict]):
        """AC11.1: text != "" iff kind == "text" on US4731298."""
        doc = all_fixtures["US4731298"]

        bad_lines = []
        for line in doc["lines"]:
            text_empty = line["text"] == ""
            is_text_kind = line["kind"] == "text"

            if text_empty == is_text_kind:
                bad_lines.append(line)

        assert len(bad_lines) == 0, (
            f"US4731298: {len(bad_lines)} lines violate invariant. "
            f"Examples: {bad_lines[:3]}"
        )

    def test_max_column_us9(self, all_fixtures: dict[str, dict]):
        """AC11.1: highest line-bearing column for US9154231 is 15.

        The patent's claims tail occupies a single-column page (page index 14)
        that the page classifier allocates as columns 15/16, but the claims text
        ends in column 15 — column 16 is allocated-but-empty and emits no lines
        (documented since Phase 2 in test_document.py). So the plan/memory figure
        of "16" is the allocated column count; the highest column that actually
        carries text — and thus the highest citable max here — is 15. A claims
        spill into col 16 would break this assertion, which is the regression we
        want to catch.
        """
        doc = all_fixtures["US9154231"]
        actual_max = max(line["column"] for line in doc["lines"])

        # Highest column that carries emitted lines (col 16 is allocated-but-empty).
        expected_max = 15
        assert actual_max == expected_max, (
            f"US9154231 max column: expected {expected_max}, got {actual_max}"
        )

    def test_max_column_us8(self, all_fixtures: dict[str, dict]):
        """AC11.1: Column counter reaches max 34 for US8131198."""
        doc = all_fixtures["US8131198"]
        actual_max = max(line["column"] for line in doc["lines"])

        expected_max = 34
        assert actual_max == expected_max, (
            f"US8131198 max column: expected {expected_max}, got {actual_max}"
        )

    def test_max_column_us4(self, all_fixtures: dict[str, dict]):
        """AC11.1: Column counter reaches max 8 for US4731298."""
        doc = all_fixtures["US4731298"]
        actual_max = max(line["column"] for line in doc["lines"])

        expected_max = 8
        assert actual_max == expected_max, (
            f"US4731298 max column: expected {expected_max}, got {actual_max}"
        )


class TestQueryRoundTrip:
    """AC11.2: Query round-trip — text-slot cites resolve to non-empty text."""

    def test_query_sample_text_slots_us9(self, all_fixtures: dict[str, dict]):
        """AC11.2: Sample text-slot cites from US9154231 resolve to non-empty text."""
        from patent_query import lookup_cite

        doc = all_fixtures["US9154231"]

        # Pick a few text slots from column 3 (known to have content)
        sample_cites = ["3:1", "3:49", "3:51", "3:67"]

        for cite in sample_cites:
            text = lookup_cite(doc, cite)
            assert text and text.strip(), (
                f"US9154231 cite '{cite}' should resolve to non-empty text, "
                f"got {text!r}"
            )

    def test_query_sample_text_slots_us8(self, all_fixtures: dict[str, dict]):
        """AC11.2: Sample text-slot cites from US8131198 resolve to non-empty text."""
        from patent_query import lookup_cite

        doc = all_fixtures["US8131198"]

        # Pick a few text slots from column 1
        sample_cites = ["1:1", "1:30", "1:67"]

        for cite in sample_cites:
            text = lookup_cite(doc, cite)
            assert text and text.strip(), (
                f"US8131198 cite '{cite}' should resolve to non-empty text, "
                f"got {text!r}"
            )

    def test_query_sample_text_slots_us4(self, all_fixtures: dict[str, dict]):
        """AC11.2: Sample text-slot cites from US4731298 resolve to non-empty text."""
        from patent_query import lookup_cite

        doc = all_fixtures["US4731298"]

        # Pick a few text slots from column 1
        sample_cites = ["1:2", "1:35", "1:67"]

        for cite in sample_cites:
            text = lookup_cite(doc, cite)
            assert text and text.strip(), (
                f"US4731298 cite '{cite}' should resolve to non-empty text, "
                f"got {text!r}"
            )

    def test_documented_spurious_ambiguous_us9(self, all_fixtures: dict[str, dict]):
        """AC11.2: Documented spurious/ambiguous cases on US9154231.

        Per the design doc:
        - 3:12-13: small span (width 2) touching spurious 13 → AmbiguousCiteError
        - 3:49-51: blank-slot cite (large span) → renders with blank at 50
        - 3:13: single cite to spurious slot → AmbiguousCiteError with neighbors
        """
        from patent_query import lookup_cite, AmbiguousCiteError

        doc = all_fixtures["US9154231"]

        # Test 3:12-13 (small span touching spurious)
        with pytest.raises(AmbiguousCiteError):
            lookup_cite(doc, "3:12-13")

        # Test 3:49-51 (large span with blank at 50)
        # This should render lines 49, 50 (blank), and 51
        text = lookup_cite(doc, "3:49-51")
        parts = text.split("\n")
        assert len(parts) == 3, (
            f"3:49-51 should render 3 lines (text, blank, text), got {len(parts)}"
        )
        # Line 50 is blank, so parts[1] should be empty
        assert parts[1] == "", (
            f"3:49-51: line 50 is blank, expected parts[1]='', got {parts[1]!r}"
        )

        # Test 3:13 (single cite to spurious)
        with pytest.raises(AmbiguousCiteError):
            lookup_cite(doc, "3:13")

    def test_marker_less_claims_tail_us8(self, all_fixtures: dict[str, dict]):
        """AC11.2: Marker-less claims tail (cols 33/34) on US8131198 page 29.

        The marker-less columns should emit text (not unknown in the query output).
        Lines should have kind text/unknown, and text cites should resolve.
        """
        from patent_query import lookup_cite

        doc = all_fixtures["US8131198"]

        # Test that marker-less columns have text
        try:
            text_33_1 = lookup_cite(doc, "33:1")
            assert text_33_1 and text_33_1.strip(), (
                "US8131198 marker-less column 33, line 1 should have text"
            )
        except Exception as e:
            pytest.fail(f"Marker-less column 33:1 query failed: {e}")

        try:
            text_34_1 = lookup_cite(doc, "34:1")
            assert text_34_1 and text_34_1.strip(), (
                "US8131198 marker-less column 34, line 1 should have text"
            )
        except Exception as e:
            pytest.fail(f"Marker-less column 34:1 query failed: {e}")


class TestCollisionRegression:
    """Guard test: NO column emits two rows with the same (page_index, column, line)."""

    def test_no_collisions_us9(self, all_fixtures: dict[str, dict]):
        """AC11.3: No collisions in (page_index, column, line) tuples on US9154231."""
        doc = all_fixtures["US9154231"]

        seen = set()
        collisions = []

        for line in doc["lines"]:
            key = (line["page_index"], line["column"], line["line"])
            if key in seen:
                collisions.append(key)
            else:
                seen.add(key)

        assert len(collisions) == 0, (
            f"US9154231: {len(collisions)} collision(s) in (page_index, column, line). "
            f"Examples: {collisions[:5]}"
        )

    def test_no_collisions_us8(self, all_fixtures: dict[str, dict]):
        """AC11.3: No collisions in (page_index, column, line) tuples on US8131198."""
        doc = all_fixtures["US8131198"]

        seen = set()
        collisions = []

        for line in doc["lines"]:
            key = (line["page_index"], line["column"], line["line"])
            if key in seen:
                collisions.append(key)
            else:
                seen.add(key)

        assert len(collisions) == 0, (
            f"US8131198: {len(collisions)} collision(s) in (page_index, column, line)"
        )

    def test_no_collisions_us4(self, all_fixtures: dict[str, dict]):
        """AC11.3: No collisions in (page_index, column, line) tuples on US4731298."""
        doc = all_fixtures["US4731298"]

        seen = set()
        collisions = []

        for line in doc["lines"]:
            key = (line["page_index"], line["column"], line["line"])
            if key in seen:
                collisions.append(key)
            else:
                seen.add(key)

        assert len(collisions) == 0, (
            f"US4731298: {len(collisions)} collision(s) in (page_index, column, line)"
        )
