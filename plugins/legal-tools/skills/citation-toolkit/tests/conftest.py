"""Shared pytest fixtures for citation-toolkit tests."""
import sys
from pathlib import Path

import pytest

# Add the parent directory to sys.path so imports work
PARENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PARENT_DIR))

FIXTURES = PARENT_DIR / "test_fixtures"


@pytest.fixture
def born_digital_pdf() -> Path:
    """US9154231 — 2015 born-digital patent (15 pages)."""
    return FIXTURES / "US9154231.pdf"


@pytest.fixture
def ocr_pdf() -> Path:
    """US4731298 — 1988 scanned/OCR-layer patent (5 pages)."""
    return FIXTURES / "US4731298.pdf"


@pytest.fixture
def no_text_layer_pdf() -> Path:
    """Raster-only PDF: extract_words() returns []."""
    return FIXTURES / "no_text_layer.pdf"


@pytest.fixture
def claims_tail_pdf() -> Path:
    """US8131198 — 2012 born-digital patent (30 pages) ending in a TINY single-column
    claims tail (index 29, cols 33/34, ~63 words, ZERO gutter line-markers). Exercises
    the header-midpoint gutter fallback and the body-page voting rule on a page that
    no single hard gate would admit."""
    return FIXTURES / "US8131198.pdf"


@pytest.fixture
def us9_artifact(tmp_path: Path) -> dict:
    """Build and load the US9154231 artifact once for all tests."""
    from patent_extract import build_document, write_document, load_document

    pdf = FIXTURES / "US9154231.pdf"
    artifact_path = tmp_path / "us9.json"

    doc = build_document(pdf)
    write_document(doc, artifact_path)
    return load_document(artifact_path)
