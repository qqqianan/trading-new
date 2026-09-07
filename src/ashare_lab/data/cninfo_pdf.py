"""PDF text extraction boundary for official CNInfo documents."""

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PdfExtractionError(Exception):
    """An official PDF cannot provide machine-readable text evidence."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a stable PDF extraction failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the PDF blocker."""
        return f"cninfo_pdf: {self.detail}"


def extract_pdf_text(content: bytes) -> str:
    """Extract text page by page while rejecting unreadable documents."""
    try:
        with BytesIO(content) as stream:
            reader = PdfReader(stream)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as error:
        detail = "invalid PDF structure"
        raise PdfExtractionError(detail) from error
    if text.strip() == "":
        detail = "PDF contains no extractable text"
        raise PdfExtractionError(detail)
    return text
