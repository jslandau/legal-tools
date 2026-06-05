"""Offline fixture tests for patent_fetch.py."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest


class TestGoogleId:
    """Unit tests for google_id helper (AC2.3)."""

    def test_grant_simple_number(self):
        """Utility grant: "US" + number, no kind code."""
        from patent_fetch import google_id

        assert google_id("grant", "8453642") == "US8453642"

    def test_grant_with_design_prefix(self):
        """Design patent: canonical_number includes the D prefix."""
        from patent_fetch import google_id

        assert google_id("grant", "D645062") == "USD645062"

    def test_plant_prefix(self):
        """Plant patent: canonical_number includes PP."""
        from patent_fetch import google_id

        assert google_id("grant", "PP12345") == "USPP12345"

    def test_reissue_prefix(self):
        """Reissue: canonical_number includes RE."""
        from patent_fetch import google_id

        assert google_id("grant", "RE38161") == "USRE38161"

    def test_apppub_number(self):
        """Application publication: "US" + publication number."""
        from patent_fetch import google_id

        assert google_id("apppub", "20090151718") == "US20090151718"


class TestExtractCitationPdfUrl:
    """Unit tests for extract_citation_pdf_url helper."""

    def test_extract_from_real_google_patent_page(self):
        """Against a real Google Patents page, extract the citation_pdf_url."""
        from patent_fetch import extract_citation_pdf_url

        fixtures_dir = Path(__file__).resolve().parent.parent / "test_fixtures"
        html_file = fixtures_dir / "google_patent_page.html"
        assert html_file.exists(), f"Fixture not found: {html_file}"

        html = html_file.read_text(encoding="utf-8", errors="replace")
        pdf_url = extract_citation_pdf_url(html)

        assert pdf_url is not None, "citation_pdf_url not found in fixture"
        assert pdf_url.startswith("https://patentimages.storage.googleapis.com")
        assert pdf_url.endswith(".pdf")

    def test_no_meta_tag_returns_none(self):
        """HTML with no citation_pdf_url meta tag returns None."""
        from patent_fetch import extract_citation_pdf_url

        html = "<html><body>No meta tags here</body></html>"
        assert extract_citation_pdf_url(html) is None

    def test_name_before_content_attribute_order(self):
        """Extract URL when name attribute comes before content."""
        from patent_fetch import extract_citation_pdf_url

        html = '<meta name="citation_pdf_url" content="https://example.com/patent.pdf">'
        url = extract_citation_pdf_url(html)
        assert url == "https://example.com/patent.pdf"

    def test_content_before_name_attribute_order(self):
        """Extract URL when content attribute comes before name."""
        from patent_fetch import extract_citation_pdf_url

        html = '<meta content="https://example.com/patent.pdf" name="citation_pdf_url">'
        url = extract_citation_pdf_url(html)
        assert url == "https://example.com/patent.pdf"

    def test_case_insensitive_match(self):
        """Regex is case-insensitive (handles mixed-case meta tags)."""
        from patent_fetch import extract_citation_pdf_url

        html = '<Meta Name="citation_pdf_url" Content="https://example.com/test.pdf">'
        url = extract_citation_pdf_url(html)
        assert url == "https://example.com/test.pdf"

    def test_decoys_ignored(self):
        """Correct URL extracted even with decoy meta tags present."""
        from patent_fetch import extract_citation_pdf_url

        html = (
            '<meta name="something_else" content="http://decoy1.com">'
            '<meta content="http://decoy2.com" name="other_field">'
            '<meta name="citation_pdf_url" content="https://correct.com/paper.pdf">'
        )
        url = extract_citation_pdf_url(html)
        assert url == "https://correct.com/paper.pdf"


class TestDecideStatus:
    """Unit tests for decide_status pure decision."""

    def test_located_false_not_located(self):
        """Not located: located=False."""
        from patent_fetch import decide_status

        assert decide_status(located=False, usable=False) == "not_located"
        assert decide_status(located=False, usable=True) == "not_located"

    def test_located_true_not_usable_image_only(self):
        """Image-only: located=True, usable=False."""
        from patent_fetch import decide_status

        assert decide_status(located=True, usable=False) == "image_only"

    def test_located_true_usable_ok(self):
        """OK: located=True, usable=True."""
        from patent_fetch import decide_status

        assert decide_status(located=True, usable=True) == "ok"


class TestCachePath:
    """Unit tests for cache_path helper."""

    def test_cache_path_construction(self, tmp_path):
        """cache_path returns cache_dir / f'{google_id}.pdf'."""
        from patent_fetch import cache_path

        cache_dir = tmp_path / "patent_cache"
        path = cache_path(cache_dir, "US8453642")
        assert path == cache_dir / "US8453642.pdf"


class TestFetchOneReGuard:
    """Test fetch_one re-guard (AC2.2 defense-in-depth)."""

    def test_reject_provisional_no_network(self, tmp_path):
        """kind='provisional' → status='rejected', no network call."""
        from patent_fetch import fetch_one

        # Monkeypatch to detect unwanted network calls
        with patch("patent_fetch.discover_pdf_url") as mock_discover:
            mock_discover.side_effect = RuntimeError("Network call not allowed!")

            result = fetch_one(
                {
                    "id": "test1",
                    "kind": "provisional",
                    "canonical_number": "123456",
                },
                tmp_path,
            )

            assert result["status"] == "rejected"
            assert result["kind"] == "provisional"
            assert result["pdf_path"] is None
            assert result["source_url"] is None
            assert result["text_words"] is None
            assert "non-fetchable kind" in result["reason"]
            mock_discover.assert_not_called()

    def test_reject_unsupported_no_network(self, tmp_path):
        """kind='unsupported' → status='rejected', no network call."""
        from patent_fetch import fetch_one

        with patch("patent_fetch.discover_pdf_url") as mock_discover:
            mock_discover.side_effect = RuntimeError("Network call not allowed!")

            result = fetch_one(
                {
                    "id": "test2",
                    "kind": "unsupported",
                    "canonical_number": "999999",
                },
                tmp_path,
            )

            assert result["status"] == "rejected"
            mock_discover.assert_not_called()


class TestFetchOneImageOnly:
    """Test fetch_one with image-only PDF (AC3.1)."""

    def test_image_only_pdf_detected(self, tmp_path, no_text_layer_pdf):
        """Cached image-only PDF → status='image_only', text_words=0."""
        from patent_fetch import fetch_one

        # Pre-populate cache with no_text_layer.pdf
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cached_pdf = cache_dir / "US9999999.pdf"
        cached_pdf.write_bytes(no_text_layer_pdf.read_bytes())

        result = fetch_one(
            {
                "id": "img1",
                "kind": "grant",
                "canonical_number": "9999999",
            },
            cache_dir,
        )

        assert result["status"] == "image_only"
        assert result["text_words"] == 0
        assert result["pdf_path"] == str(cached_pdf)


class TestFetchOneOk:
    """Test fetch_one success path (born-digital PDF)."""

    def test_ok_with_text_layer(self, tmp_path, born_digital_pdf):
        """Cached born-digital PDF → status='ok', text_words > 0."""
        from patent_fetch import fetch_one

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cached_pdf = cache_dir / "US8453642.pdf"
        cached_pdf.write_bytes(born_digital_pdf.read_bytes())

        result = fetch_one(
            {
                "id": "ok1",
                "kind": "grant",
                "canonical_number": "8453642",
            },
            cache_dir,
        )

        assert result["status"] == "ok"
        assert result["text_words"] > 0
        assert result["pdf_path"] == str(cached_pdf)
        assert result["source_url"] is None  # Cached; no source URL


class TestFetchOneNotLocated:
    """Test fetch_one discovery failure (AC3.2)."""

    def test_not_located_discovery_fails(self, tmp_path):
        """discover_pdf_url returns (None, error) → status='not_located'."""
        from patent_fetch import fetch_one

        with patch("patent_fetch.discover_pdf_url") as mock_discover:
            mock_discover.return_value = (None, "page 404")

            result = fetch_one(
                {
                    "id": "missing1",
                    "kind": "grant",
                    "canonical_number": "0000000",
                },
                tmp_path,
            )

            assert result["status"] == "not_located"
            assert result["pdf_path"] is None
            assert result["source_url"] is None
            assert result["text_words"] is None
            assert "page 404" in result["reason"]


class TestProcessAndMain:
    """Test process() batch handling and main() CLI (AC3.3)."""

    def test_process_mixed_batch_same_order(self, tmp_path, no_text_layer_pdf):
        """Mixed batch: grant(ok via fixture), unsupported(rejected), app-pub(rejected)."""
        from patent_fetch import process

        # Prepare cache with one PDF
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cached_ok = cache_dir / "US8453642.pdf"
        cached_ok.write_bytes(no_text_layer_pdf.read_bytes())

        # Note: using image-only fixture for simplicity; what matters is the batch order
        # and status values for the mixed kinds
        with patch("patent_fetch.discover_pdf_url") as mock_discover:
            # Should not be called for rejected or cached entries
            mock_discover.side_effect = RuntimeError("Unexpected network call")

            entries = [
                {
                    "id": "g1",
                    "kind": "grant",
                    "canonical_number": "8453642",
                },  # Cache hit
                {
                    "id": "u1",
                    "kind": "unsupported",
                    "canonical_number": "123456",
                },  # Rejected
                {
                    "id": "p1",
                    "kind": "provisional",
                    "canonical_number": "999999",
                },  # Rejected
            ]

            results = process(entries, cache_dir)

            assert len(results) == 3
            assert results[0]["id"] == "g1"
            assert results[0]["status"] == "image_only"  # Cache hit on image-only
            assert results[1]["id"] == "u1"
            assert results[1]["status"] == "rejected"
            assert results[2]["id"] == "p1"
            assert results[2]["status"] == "rejected"

    def test_main_help_exits_zero(self):
        """main(['--help']) exits with 0."""
        from patent_fetch import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        # argparse exits with 0 on --help
        assert exc_info.value.code == 0

    def test_main_invalid_json_returns_2(self):
        """main() with invalid JSON returns 2."""
        from patent_fetch import main
        from unittest.mock import patch
        from io import StringIO

        with patch("sys.stdin", StringIO("not valid json")):
            result = main([])
            assert result == 2

    def test_main_non_array_json_returns_2(self):
        """main() with non-array JSON returns 2."""
        from patent_fetch import main
        from unittest.mock import patch
        from io import StringIO

        with patch("sys.stdin", StringIO('{"not": "an array"}')):
            result = main([])
            assert result == 2

    def test_main_valid_json_returns_0(self, tmp_path, capsys):
        """main() with valid JSON array returns 0 and outputs JSON."""
        from patent_fetch import main
        from unittest.mock import patch
        from io import StringIO

        entries = [
            {"id": "p1", "kind": "provisional", "canonical_number": "123456"}
        ]
        input_json = json.dumps(entries)

        with patch("sys.stdin", StringIO(input_json)):
            result = main(["--cache-dir", str(tmp_path)])
            assert result == 0

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert isinstance(output, list)
        assert len(output) == 1
        assert output[0]["id"] == "p1"
        assert output[0]["status"] == "rejected"


@pytest.mark.network
class TestLiveSmoke:
    """Optional live smoke tests (network-gated, deselected by default)."""

    def test_fetch_real_grant(self, tmp_path):
        """Fetch a real grant (US11000000) from Google Patents."""
        from patent_fetch import process

        entries = [
            {
                "id": "g",
                "kind": "grant",
                "canonical_number": "11000000",
            }
        ]

        results = process(entries, tmp_path)
        assert len(results) == 1
        result = results[0]

        assert result["id"] == "g"
        assert result["status"] == "ok"
        assert result["text_words"] > 0
        assert result["pdf_path"] is not None
        assert result["source_url"] is not None
        assert result["source_url"].startswith(
            "https://patentimages.storage.googleapis.com"
        )

    def test_fetch_real_apppub(self, tmp_path):
        """Fetch a real app-pub (US20090151718) from Google Patents."""
        from patent_fetch import process

        entries = [
            {
                "id": "a",
                "kind": "apppub",
                "canonical_number": "20090151718",
            }
        ]

        results = process(entries, tmp_path)
        assert len(results) == 1
        result = results[0]

        assert result["id"] == "a"
        assert result["status"] == "ok"
        assert result["text_words"] > 0
        assert result["pdf_path"] is not None
        assert result["source_url"] is not None
        assert result["source_url"].startswith(
            "https://patentimages.storage.googleapis.com"
        )
