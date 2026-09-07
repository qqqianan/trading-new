"""Narrow HTML parsers for official historical industry archive pages."""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Final
from urllib.parse import urljoin

_QUARTER_PATTERN: Final = re.compile(
    r"(?P<year>20\d{2})年(?P<quarter>[1-4一二三四])季度?上市公司行业分类结果"
)
_DATE_PATTERN: Final = re.compile(r"(?P<date>20\d{2}-\d{2}-\d{2})")
_QUARTERS: Final = {"1": 1, "2": 2, "3": 3, "4": 4, "一": 1, "二": 2, "三": 3, "四": 4}


@dataclass(frozen=True, slots=True)
class ArchiveListEntry:
    """One quarterly content-page link discovered in the official list."""

    year: int
    quarter: int
    title: str
    page_url: str


@dataclass(frozen=True, slots=True)
class ArchivePageMetadata:
    """Publication metadata and PDF link parsed from one content page."""

    title: str | None
    publication_date_text: str | None
    attachment_url: str | None


class _AnchorParser(HTMLParser):
    """Mutable parser state is required by the incremental HTMLParser protocol."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        self._href = dict(attrs).get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        self.links.append((self._href, "".join(self._text).strip()))
        self._href = None
        self._text = []


class _ContentParser(HTMLParser):
    """Mutable parser state extracts only official metadata and PDF links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.description: str | None = None
        self.pdf_hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        match tag.lower():
            case "meta":
                name = (attributes.get("name") or "").lower()
                content = attributes.get("content")
                if name == "articletitle" and content:
                    self.title = content
                elif name == "description" and content and self.description is None:
                    self.description = content
            case "a":
                href = attributes.get("href")
                if href is not None and href.lower().split("?", maxsplit=1)[0].endswith(".pdf"):
                    self.pdf_hrefs.append(href)
            case _:
                return


def parse_archive_list(html: bytes, base_url: str) -> tuple[ArchiveListEntry, ...]:
    """Parse quarterly archive links from the official list page."""
    parser = _AnchorParser()
    parser.feed(html.decode("utf-8"))
    entries: list[ArchiveListEntry] = []
    for href, title in parser.links:
        match = _QUARTER_PATTERN.search(title)
        if match is None:
            continue
        entries.append(
            ArchiveListEntry(
                year=int(match.group("year")),
                quarter=_QUARTERS[match.group("quarter")],
                title=title,
                page_url=urljoin(base_url, href),
            )
        )
    return tuple(entries)


def parse_archive_page(html: bytes, page_url: str) -> ArchivePageMetadata:
    """Parse publication date and the first PDF attachment from a content page."""
    parser = _ContentParser()
    parser.feed(html.decode("utf-8"))
    date_match = _DATE_PATTERN.search(parser.description or "")
    publication_date = date_match.group("date") if date_match is not None else None
    attachment_url = urljoin(page_url, parser.pdf_hrefs[0]) if parser.pdf_hrefs else None
    return ArchivePageMetadata(
        title=parser.title,
        publication_date_text=publication_date,
        attachment_url=attachment_url,
    )
