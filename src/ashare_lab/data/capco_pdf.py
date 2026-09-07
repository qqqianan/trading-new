"""Layout-preserving extraction for official CAPCO classification PDFs."""

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class CapcoPdfExtractionError(Exception):
    """The official attachment cannot be converted to layout page text."""


def extract_capco_layout_pages(content: bytes) -> tuple[str, ...]:
    """Extract each PDF page while preserving table-aligned text positions."""
    try:
        with BytesIO(content) as stream:
            reader = PdfReader(stream)
            pages = tuple(
                page.extract_text(extraction_mode="layout") or "" for page in reader.pages
            )
    except (KeyError, PdfReadError, OSError, ValueError) as error:
        raise CapcoPdfExtractionError from error
    if not pages:
        raise CapcoPdfExtractionError
    return pages
