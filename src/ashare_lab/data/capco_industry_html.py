"""HTML parsing for China Association for Public Companies archives."""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Final
from urllib.parse import urljoin

_HALF_PATTERN: Final = re.compile(r"(?P<year>20\d{2})年(?P<half>[上下])半年上市公司行业分类结果")
_DATE_PATTERN: Final = re.compile(r"发布时间\uff1a\s*(?P<date>20\d{2}-\d{2}-\d{2})")
_HALVES: Final = {"上": 1, "下": 2}


@dataclass(frozen=True, slots=True)
class CapcoListEntry:
    """One half-year official result page discovered in the list."""

    year: int
    half: int
    title: str
    page_url: str


@dataclass(frozen=True, slots=True)
class CapcoPageMetadata:
    """Publication date and code-sorted PDF selected from a result page."""

    publication_date_text: str | None
    code_sorted_attachment_url: str | None


class _AnchorParser(HTMLParser):
    """Mutable state is required by the incremental HTMLParser contract."""

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
        self.links.append((self._href.strip(), "".join(self._text).strip()))
        self._href = None
        self._text = []


def parse_capco_archive_list(html: bytes, base_url: str) -> tuple[CapcoListEntry, ...]:
    """Parse half-year classification result links from the official list."""
    parser = _AnchorParser()
    parser.feed(html.decode("utf-8"))
    entries: list[CapcoListEntry] = []
    for href, title in parser.links:
        match = _HALF_PATTERN.search(title)
        if match is None:
            continue
        entries.append(
            CapcoListEntry(
                year=int(match.group("year")),
                half=_HALVES[match.group("half")],
                title=title,
                page_url=urljoin(base_url, href),
            )
        )
    return tuple(entries)


def parse_capco_archive_page(html: bytes, page_url: str) -> CapcoPageMetadata:
    """Select the stock-code-sorted PDF and page publication date."""
    decoded = html.decode("utf-8")
    parser = _AnchorParser()
    parser.feed(decoded)
    date_match = _DATE_PATTERN.search(decoded)
    publication_date = date_match.group("date") if date_match is not None else None
    attachment_url: str | None = None
    for href, text in parser.links:
        if "按股票代码排序" in text and href.lower().split("?", maxsplit=1)[0].endswith(".pdf"):
            attachment_url = urljoin(page_url, href)
            break
    return CapcoPageMetadata(
        publication_date_text=publication_date,
        code_sorted_attachment_url=attachment_url,
    )
