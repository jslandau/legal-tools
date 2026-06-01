"""Shared pytest fixtures for citation-toolkit tests."""
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "test_fixtures"


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
