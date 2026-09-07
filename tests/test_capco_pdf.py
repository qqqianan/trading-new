from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from ashare_lab.data.capco_pdf import CapcoPdfExtractionError, extract_capco_layout_pages


def test_capco_pdf_extractor_preserves_one_page_boundary() -> None:
    # Given: one valid in-memory PDF page.
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    page[NameObject("/Contents")] = DecodedStreamObject()
    stream = BytesIO()
    writer.write(stream)

    # When: the attachment crosses the layout extraction boundary.
    pages = extract_capco_layout_pages(stream.getvalue())

    # Then: the physical page remains represented even when it has no text.
    assert pages == ("",)


def test_capco_pdf_extractor_rejects_page_without_content_stream() -> None:
    # Given: a PDF page whose content-stream boundary is absent.
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)

    # When / Then: low-level missing keys become the typed extraction failure.
    with pytest.raises(CapcoPdfExtractionError):
        extract_capco_layout_pages(stream.getvalue())


def test_capco_pdf_extractor_rejects_document_without_pages() -> None:
    # Given: a syntactically valid PDF with no physical pages.
    writer = PdfWriter()
    stream = BytesIO()
    writer.write(stream)

    # When / Then: absence of page evidence fails closed.
    with pytest.raises(CapcoPdfExtractionError):
        extract_capco_layout_pages(stream.getvalue())


def test_capco_pdf_extractor_rejects_malformed_bytes() -> None:
    # Given: bytes that cannot form an official PDF document.
    # When / Then: parser-library failures become the typed boundary error.
    with pytest.raises(CapcoPdfExtractionError):
        extract_capco_layout_pages(b"not-a-pdf")
