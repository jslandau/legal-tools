"""Comprehensive unit tests for patent_ref.py classification and parsing."""
import json

import pytest


class TestUtilityGrants:
    """Tests for utility patent grant parsing (7–10 digits)."""

    def test_seven_digit_utility_grant(self):
        """7-digit utility grant should classify as grant."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("7123456")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "7123456"
        assert result["fetchable"] is True
        assert result["reason"] is None
        assert "7,123,456" in result["display"]

    def test_eight_digit_utility_grant_with_noise(self):
        """8-digit utility with noise tokens and kind code should strip noise and code."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("US 8,453,642 B2")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "8453642"
        assert result["fetchable"] is True
        assert result["reason"] is None

    def test_ten_digit_utility_grant(self):
        """10-digit utility grant at the boundary."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("US 10,000,000 B2")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "10000000"
        assert result["fetchable"] is True

    def test_utility_with_b1_kind_code(self):
        """Utility grant with B1 kind code should be stripped."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("8453642 B1")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "8453642"

    def test_utility_plain_no_noise(self):
        """Utility grant with no noise tokens."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("8,453,642")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "8453642"

    def test_utility_no_commas(self):
        """Utility grant without commas."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("8453642")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "8453642"

    def test_utility_with_patent_label(self):
        """Utility grant with 'U.S. Patent No.' label."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("U.S. Patent No. 8453642")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "8453642"

    def test_utility_with_a1_kind_code(self):
        """Utility grant with A1 kind code (should still strip)."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("8453642 A1")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "8453642"


class TestDesignGrants:
    """Tests for design patent grants (D + digits)."""

    def test_design_grant_basic(self):
        """Design grant D followed by digits."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("D645062")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "D645062"
        assert result["fetchable"] is True
        assert "D645,062" in result["display"]

    def test_design_grant_with_commas(self):
        """Design grant with commas in input."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("D645,062")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "D645062"

    def test_design_grant_with_label(self):
        """Design grant with noise tokens."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("U.S. Patent No. D645062")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "D645062"

    def test_design_grant_letter_prefix_preserved(self):
        """Design grant D prefix should be preserved in canonical form."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("D123456")

        # The D prefix should be in the canonical number
        assert result["canonical_number"].startswith("D")
        assert result["canonical_number"] == "D123456"


class TestPlantGrants:
    """Tests for plant patent grants (PP + digits)."""

    def test_plant_grant_basic(self):
        """Plant grant PP followed by digits."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("PP12345")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "PP12345"
        assert result["fetchable"] is True
        assert "Plant Patent" in result["display"]

    def test_plant_grant_with_commas(self):
        """Plant grant with commas in input."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("PP12,345")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "PP12345"

    def test_plant_grant_with_label(self):
        """Plant grant with noise tokens."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("U.S. Plant Patent No. PP12345")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "PP12345"


class TestReissueGrants:
    """Tests for reissue patent grants (RE + digits)."""

    def test_reissue_grant_basic(self):
        """Reissue grant RE followed by digits."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("RE38161")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "RE38161"
        assert result["fetchable"] is True
        assert "Reissue Patent" in result["display"]

    def test_reissue_grant_with_commas(self):
        """Reissue grant with commas in input."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("RE38,161")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "RE38161"

    def test_reissue_grant_with_label(self):
        """Reissue grant with noise tokens."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("U.S. Reissue Patent No. RE38161")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "RE38161"


class TestApplicationPublications:
    """Tests for application publications (YYYY/NNNNNNN or YYYYNNNNNNN)."""

    def test_apppub_slash_form_basic(self):
        """Application publication in slash form YYYY/NNNNNNN."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("2009/0151718")

        assert result["kind"] == "apppub"
        assert result["canonical_number"] == "20090151718"
        assert result["fetchable"] is True
        assert result["reason"] is None
        assert "2009/0151718" in result["display"]

    def test_apppub_slash_form_with_kind_code(self):
        """Application publication slash form with A1 kind code."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("2009/0151718 A1")

        assert result["kind"] == "apppub"
        assert result["canonical_number"] == "20090151718"
        assert result["fetchable"] is True

    def test_apppub_concatenated_form(self):
        """Application publication in concatenated 11-digit form."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("20090151718")

        assert result["kind"] == "apppub"
        assert result["canonical_number"] == "20090151718"
        assert result["fetchable"] is True
        # Display should reformat back to slash form
        assert "2009/0151718" in result["display"]

    def test_apppub_with_label_and_slash(self):
        """Application publication with full label."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("U.S. Patent Application Pub. No. 2009/0151718 A1")

        assert result["kind"] == "apppub"
        assert result["canonical_number"] == "20090151718"

    def test_apppub_1900s_year(self):
        """Application publication with 1900s year prefix."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("1995/1234567")

        assert result["kind"] == "apppub"
        assert result["canonical_number"] == "19951234567"

    def test_apppub_slash_and_concatenated_produce_same_canonical(self):
        """Slash and concatenated forms should produce identical canonical number."""
        from patent_ref import parse_patent_ref

        slash_form = parse_patent_ref("2009/0151718")
        concat_form = parse_patent_ref("20090151718")

        assert slash_form["canonical_number"] == concat_form["canonical_number"]
        assert slash_form["canonical_number"] == "20090151718"

    def test_apppub_slash_and_concatenated_display_formats_correctly(self):
        """Both forms should display in slash format."""
        from patent_ref import parse_patent_ref

        slash_form = parse_patent_ref("2009/0151718")
        concat_form = parse_patent_ref("20090151718")

        assert "2009/0151718" in slash_form["display"]
        assert "2009/0151718" in concat_form["display"]


class TestProvisionalApplications:
    """Tests for provisional application numbers (60/NN, 61/NN, 62/NN)."""

    def test_provisional_60_series(self):
        """Provisional application 60/NNNNNN."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("60/123456")

        assert result["kind"] == "provisional"
        assert result["fetchable"] is False
        assert result["reason"] == "provisional applications are not publicly retrievable"
        assert result["canonical_number"] == "123456"

    def test_provisional_61_series(self):
        """Provisional application 61/NNNNNN."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("61/000111")

        assert result["kind"] == "provisional"
        assert result["fetchable"] is False
        assert result["canonical_number"] == "000111"

    def test_provisional_62_series(self):
        """Provisional application 62/NNNNNN."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("62/123456")

        assert result["kind"] == "provisional"
        assert result["fetchable"] is False

    def test_provisional_with_commas(self):
        """Provisional with commas in input."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("60/123,456")

        assert result["kind"] == "provisional"
        assert result["canonical_number"] == "123456"

    def test_provisional_with_label(self):
        """Provisional with noise tokens."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("U.S. Provisional Application No. 60/123456")

        assert result["kind"] == "provisional"
        assert result["fetchable"] is False


class TestUnsupported:
    """Tests for unrecognized/unsupported patent formats."""

    def test_unsupported_banana(self):
        """Pure garbage text."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("banana")

        assert result["kind"] == "unsupported"
        assert result["fetchable"] is False
        assert result["reason"] == "unrecognized patent number format"
        assert result["canonical_number"] == ""
        assert result["display"] == "banana"

    def test_unsupported_empty_string(self):
        """Empty string."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("")

        assert result["kind"] == "unsupported"
        assert result["fetchable"] is False

    def test_unsupported_see_figure_3(self):
        """Non-numeric reference."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("see figure 3")

        assert result["kind"] == "unsupported"
        assert result["fetchable"] is False

    def test_unsupported_11_digit_non_year_prefix(self):
        """11-digit number not starting with 19 or 20 (boundary rule)."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("99999999999")

        assert result["kind"] == "unsupported"
        assert result["fetchable"] is False

    def test_unsupported_prefill_digits_garbled(self):
        """Unsupported format should preserve best-effort digits for Phase-A prefill."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("app no. 13/995,123 garbled")

        assert result["kind"] == "unsupported"
        assert result["fetchable"] is False
        # Should extract isolated digits
        assert result["canonical_number"] == "13995123"

    def test_unsupported_no_digits(self):
        """Unsupported format with no digits should have empty canonical_number."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("banana")

        assert result["kind"] == "unsupported"
        assert result["canonical_number"] == ""


class TestBoundaryRules:
    """Tests for boundary conditions between similar formats."""

    def test_11_digit_boundary_apppub_not_grant(self):
        """11-digit number starting with 19/20 is app-pub, not utility grant."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("20090151718")

        assert result["kind"] == "apppub", "11-digit with year prefix should be apppub"
        assert result["fetchable"] is True

    def test_7_digit_grant(self):
        """7-digit number is a utility grant (not app-pub)."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("7123456")

        assert result["kind"] == "grant"
        assert result["fetchable"] is True

    def test_10_digit_grant(self):
        """10-digit number is a utility grant (boundary)."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("10000000")

        assert result["kind"] == "grant"
        assert result["fetchable"] is True

    def test_6_digit_unsupported(self):
        """6-digit number is unsupported (below utility grant minimum)."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("123456")

        assert result["kind"] == "unsupported"
        assert result["fetchable"] is False

    def test_11_digit_no_year_prefix_unsupported(self):
        """11-digit number without year prefix is unsupported."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("99999999999")

        assert result["kind"] == "unsupported"


class TestNoiseStripping:
    """Tests for noise token and punctuation stripping."""

    def test_us_prefix_stripped(self):
        """US prefix should be stripped."""
        from patent_ref import parse_patent_ref

        result1 = parse_patent_ref("US 8453642")
        result2 = parse_patent_ref("8453642")

        assert result1["canonical_number"] == result2["canonical_number"]

    def test_u_s_prefix_stripped(self):
        """U.S. prefix should be stripped."""
        from patent_ref import parse_patent_ref

        result1 = parse_patent_ref("U.S. 8453642")
        result2 = parse_patent_ref("8453642")

        assert result1["canonical_number"] == result2["canonical_number"]

    def test_patent_label_stripped(self):
        """PATENT label should be stripped."""
        from patent_ref import parse_patent_ref

        result1 = parse_patent_ref("PATENT 8453642")
        result2 = parse_patent_ref("8453642")

        assert result1["canonical_number"] == result2["canonical_number"]

    def test_patent_no_label_stripped(self):
        """PATENT NO. label should be stripped."""
        from patent_ref import parse_patent_ref

        result1 = parse_patent_ref("PATENT NO. 8453642")
        result2 = parse_patent_ref("8453642")

        assert result1["canonical_number"] == result2["canonical_number"]

    def test_kind_code_stripped_b1(self):
        """B1 kind code should be stripped."""
        from patent_ref import parse_patent_ref

        result1 = parse_patent_ref("8453642 B1")
        result2 = parse_patent_ref("8453642")

        assert result1["canonical_number"] == result2["canonical_number"]

    def test_kind_code_stripped_b2(self):
        """B2 kind code should be stripped."""
        from patent_ref import parse_patent_ref

        result1 = parse_patent_ref("8453642 B2")
        result2 = parse_patent_ref("8453642")

        assert result1["canonical_number"] == result2["canonical_number"]

    def test_kind_code_stripped_a1(self):
        """A1 kind code should be stripped."""
        from patent_ref import parse_patent_ref

        result1 = parse_patent_ref("8453642 A1")
        result2 = parse_patent_ref("8453642")

        assert result1["canonical_number"] == result2["canonical_number"]

    def test_commas_stripped(self):
        """Commas should be stripped."""
        from patent_ref import parse_patent_ref

        result1 = parse_patent_ref("8,453,642")
        result2 = parse_patent_ref("8453642")

        assert result1["canonical_number"] == result2["canonical_number"]

    def test_multiple_spaces_collapsed(self):
        """Multiple spaces should be collapsed."""
        from patent_ref import parse_patent_ref

        result1 = parse_patent_ref("8453642    B2")
        result2 = parse_patent_ref("8453642 B2")

        assert result1["canonical_number"] == result2["canonical_number"]

    def test_letter_prefix_not_stripped_as_noise(self):
        """Letter prefixes D, PP, RE should not be stripped as noise."""
        from patent_ref import parse_patent_ref

        result_d = parse_patent_ref("D645062")
        result_pp = parse_patent_ref("PP12345")
        result_re = parse_patent_ref("RE38161")

        assert result_d["canonical_number"].startswith("D")
        assert result_pp["canonical_number"].startswith("PP")
        assert result_re["canonical_number"].startswith("RE")


class TestDisplayFormatting:
    """Tests for human-readable display formatting."""

    def test_display_utility_grant(self):
        """Utility grant display should include commas."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("8453642")

        assert result["display"] == "U.S. Patent No. 8,453,642"

    def test_display_design_grant(self):
        """Design grant display should include D and commas."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("D645062")

        assert result["display"] == "U.S. Patent No. D645,062"

    def test_display_plant_grant(self):
        """Plant grant display should include Plant Patent and commas."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("PP12345")

        assert "Plant Patent" in result["display"]
        assert "PP12,345" in result["display"]

    def test_display_reissue_grant(self):
        """Reissue grant display should include Reissue and commas."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("RE38161")

        assert "Reissue Patent" in result["display"]
        assert "RE38,161" in result["display"]

    def test_display_apppub(self):
        """Application publication display should include slash form."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("20090151718")

        assert "Application Pub" in result["display"]
        assert "2009/0151718" in result["display"]

    def test_display_provisional(self):
        """Provisional display should include series and number."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("60/123456")

        assert "Provisional" in result["display"]
        assert "60/123456" in result["display"]


class TestBatchProcessing:
    """Tests for the batch process() function."""

    def test_process_preserves_order(self):
        """process() should return results in same order as input."""
        from patent_ref import process

        entries = [
            {"id": "p1", "raw": "8453642"},
            {"id": "p2", "raw": "D645062"},
            {"id": "p3", "raw": "60/123456"},
        ]

        results = process(entries)

        assert len(results) == 3
        assert results[0]["id"] == "p1"
        assert results[1]["id"] == "p2"
        assert results[2]["id"] == "p3"

    def test_process_echoes_id(self):
        """process() should echo the id field from input."""
        from patent_ref import process

        entries = [
            {"id": "custom-id", "raw": "8453642"},
        ]

        results = process(entries)

        assert results[0]["id"] == "custom-id"

    def test_process_includes_all_fields(self):
        """process() should include all PatentRef fields."""
        from patent_ref import process

        entries = [{"id": "p1", "raw": "8453642"}]
        results = process(entries)

        expected_keys = {"id", "kind", "canonical_number", "display", "fetchable", "reason"}
        assert set(results[0].keys()) == expected_keys

    def test_process_batch(self):
        """process() with multiple entries."""
        from patent_ref import process

        entries = [
            {"id": "p1", "raw": "8453642"},
            {"id": "p2", "raw": "60/123456"},
            {"id": "p3", "raw": "banana"},
        ]

        results = process(entries)

        assert results[0]["kind"] == "grant"
        assert results[1]["kind"] == "provisional"
        assert results[2]["kind"] == "unsupported"


class TestBatchProcessingErrorHandling:
    """Tests for error handling in process() and main()."""

    def test_process_non_dict_element_raises_error(self):
        """process() should raise ValueError if an array element is not a dict."""
        from patent_ref import process
        import pytest

        entries = [
            {"id": "p1", "raw": "8453642"},
            "not a dict",  # Non-dict element
        ]

        with pytest.raises(ValueError, match="index 1.*not a dict"):
            process(entries)

    def test_process_non_dict_element_names_index(self):
        """Error message should clearly identify the bad index."""
        from patent_ref import process
        import pytest

        entries = [
            {"id": "p1", "raw": "8453642"},
            {"id": "p2", "raw": "D645062"},
            ["list", "not", "dict"],  # Non-dict at index 2
        ]

        with pytest.raises(ValueError, match="index 2"):
            process(entries)

    def test_main_non_dict_element_exits_2(self, capsys):
        """main() should exit 2 when array contains non-dict element."""
        from patent_ref import main
        import sys
        import io
        import json as json_module

        input_data = json_module.dumps([{"id": "p1", "raw": "8453642"}, "not a dict"])
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(input_data)

        result = main([])

        sys.stdin = old_stdin
        captured = capsys.readouterr()

        assert result == 2
        assert "ERROR" in captured.err
        assert "invalid array element" in captured.err


class TestMainCLI:
    """Tests for the main() CLI function."""

    def test_main_stdin_input(self, capsys):
        """main() should read from stdin and write JSON to stdout."""
        from patent_ref import main
        import json as json_module

        input_data = json_module.dumps([{"id": "p1", "raw": "8453642"}])
        import sys
        import io
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(input_data)

        result = main([])

        sys.stdin = old_stdin
        captured = capsys.readouterr()
        output = json_module.loads(captured.out)

        assert result == 0
        assert len(output) == 1
        assert output[0]["id"] == "p1"
        assert output[0]["kind"] == "grant"

    def test_main_help_flag(self):
        """main() with --help should exit 0."""
        from patent_ref import main
        import sys
        import io

        # Redirect stdout to capture help text
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

        try:
            result = main(["--help"])
        except SystemExit as e:
            result = e.code
        finally:
            sys.stdout = old_stdout

        # --help exits with 0
        assert result == 0

    def test_main_invalid_json_error(self, capsys):
        """main() should exit 2 on invalid JSON input."""
        from patent_ref import main
        import sys
        import io

        old_stdin = sys.stdin
        sys.stdin = io.StringIO("not valid json")

        result = main([])

        sys.stdin = old_stdin
        captured = capsys.readouterr()

        assert result == 2
        assert "ERROR" in captured.err
        assert "valid JSON" in captured.err

    def test_main_non_array_json_error(self, capsys):
        """main() should exit 2 if JSON is not an array."""
        from patent_ref import main
        import sys
        import io
        import json as json_module

        input_data = json_module.dumps({"id": "p1", "raw": "8453642"})
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(input_data)

        result = main([])

        sys.stdin = old_stdin
        captured = capsys.readouterr()

        assert result == 2
        assert "ERROR" in captured.err
        assert "array" in captured.err

    def test_main_output_format(self, capsys):
        """main() should output properly formatted JSON with indentation."""
        from patent_ref import main
        import sys
        import io
        import json as json_module

        input_data = json_module.dumps([{"id": "p1", "raw": "8453642"}])
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(input_data)

        result = main([])

        sys.stdin = old_stdin
        captured = capsys.readouterr()

        # Should have proper indentation
        assert "  " in captured.out
        # Should end with newline
        assert captured.out.endswith("\n")


class TestEpDocuments:
    """Tests for European Patent (EP) document parsing — new kind 'ep'."""

    def test_ep_compact_seven_digits(self):
        """EP1234567 parses as kind=ep, canonical EP1234567, not fetchable."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("EP1234567")

        assert result["kind"] == "ep"
        assert result["canonical_number"] == "EP1234567"
        assert result["display"] == "European Patent No. EP 1 234 567"
        assert result["fetchable"] is False
        assert result["reason"] == "non-US lookup not yet supported"

    def test_ep_spaced_form(self):
        """'EP 1 234 567' (EPO display spacing) parses identically to compact."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("EP 1 234 567")

        assert result["kind"] == "ep"
        assert result["canonical_number"] == "EP1234567"

    def test_ep_with_kind_code(self):
        """'EP 1234567 B1' strips the kind code as noise."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("EP 1234567 B1")

        assert result["kind"] == "ep"
        assert result["canonical_number"] == "EP1234567"

    def test_ep_lowercase_input(self):
        """Lowercase 'ep 1234567' still parses (normalization uppercases)."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("ep 1234567")

        assert result["kind"] == "ep"
        assert result["canonical_number"] == "EP1234567"


class TestWoDocuments:
    """Tests for WIPO (WO) publication parsing — new kind 'wo'."""

    def test_wo_slash_form(self):
        """'WO 2009/151718' parses as kind=wo with year/serial canonical."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("WO 2009/151718")

        assert result["kind"] == "wo"
        assert result["canonical_number"] == "WO2009151718"
        assert result["display"] == "PCT Pub. No. WO 2009/151718"
        assert result["fetchable"] is False
        assert result["reason"] == "non-US lookup not yet supported"

    def test_wo_compact_form(self):
        """'WO2009151718' (no slash) parses identically to slash form."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("WO2009151718")

        assert result["kind"] == "wo"
        assert result["canonical_number"] == "WO2009151718"
        assert result["display"] == "PCT Pub. No. WO 2009/151718"

    def test_wo_with_kind_code(self):
        """'WO 2009/151718 A1' strips the kind code as noise."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("WO 2009/151718 A1")

        assert result["kind"] == "wo"
        assert result["canonical_number"] == "WO2009151718"


class TestPctApplications:
    """Tests for PCT application number parsing — new kind 'pct_app'."""

    def test_pct_app_four_digit_year(self):
        """'PCT/US2009/046667' parses as kind=pct_app."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("PCT/US2009/046667")

        assert result["kind"] == "pct_app"
        assert result["canonical_number"] == "PCT/US2009/046667"
        assert result["display"] == "PCT Application No. PCT/US2009/046667"
        assert result["fetchable"] is False
        assert result["reason"] == "non-US lookup not yet supported"

    def test_pct_app_two_digit_year(self):
        """'PCT/US99/12345' (pre-2004 two-digit year, 5-digit serial) parses."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("PCT/US99/12345")

        assert result["kind"] == "pct_app"
        assert result["canonical_number"] == "PCT/US99/12345"

    def test_pct_app_other_receiving_office(self):
        """'PCT/EP2010/051234' (non-US receiving office) parses."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("PCT/EP2010/051234")

        assert result["kind"] == "pct_app"
        assert result["canonical_number"] == "PCT/EP2010/051234"


class TestInternationalDoesNotBreakExisting:
    """Regression guards: existing kinds keep winning over the new branches."""

    def test_utility_grant_still_parses(self):
        """Plain 8453642 is still a utility grant, not ep/wo."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("US 8,453,642 B2")

        assert result["kind"] == "grant"
        assert result["canonical_number"] == "8453642"

    def test_apppub_still_parses(self):
        """2009/0151718 is still an apppub, not wo."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("2009/0151718 A1")

        assert result["kind"] == "apppub"
        assert result["canonical_number"] == "20090151718"

    def test_garbage_still_unsupported(self):
        """'EPIC FAIL' must not match the EP branch."""
        from patent_ref import parse_patent_ref

        result = parse_patent_ref("EPIC FAIL")

        assert result["kind"] == "unsupported"
