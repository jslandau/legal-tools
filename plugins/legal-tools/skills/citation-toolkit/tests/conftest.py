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
