"""Fail-closed selection and parsing of official IPO industry disclosures."""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from typing import Final

from pydantic import TypeAdapter

from ashare_lab.data.cninfo_models import CninfoAnnouncement, CninfoAnnouncementResponse

_REJECTED_TITLE_MARKERS: Final = ("已取消", "更正公告", "提示性公告")
_REJECTED_PROSPECTUS_MARKERS: Final = (
    "已取消",
    "更正",
    "摘要",
    "申报稿",
    "预披露",
    "提示性公告",
)
_MARKER_PATTERN: Final = re.compile(r"上市公司行业分类|所属行业|公司属于|公司所处行业为|行业分类")
_CODE_PATTERN: Final = re.compile(r"[A-Z]\d{2}(?!\d)")
_NAME_AFTER_PATTERN: Final = re.compile(r"[\"'“”]*(?P<name>[\u4e00-\u9fff、]{1,40}?业)")
_NAME_BEFORE_PATTERN: Final = re.compile(
    r"(?:(?:为|属于)[\"“”\u2018\u2019]?|所属行业(?::|为|属于)?[\"“”\u2018\u2019]?)"
    r"(?P<name>[\u4e00-\u9fff、]{1,40}业)[\"“”\u2018\u2019]?\($"
)
_NAME_BEFORE_CODE_LABEL_PATTERN: Final = re.compile(
    r"(?:(?:为|属于)|所属行业:?)"
    r"(?P<name>[\u4e00-\u9fff、]{1,40}业)\((?:行业)?代码(?:为|:)$"
)
_CSRC_2012_PATTERN: Final = re.compile(r"上市公司行业分类指引》?\(2012年修订\)")
_ORDERED_TAXONOMY_CODES_PATTERN: Final = re.compile(
    r"上市公司行业分类指引》?\(2012年修订\).{0,120}?"
    r"国民经济行业分类》?\(GB/T4754-2011\).{0,160}?"
    r"公司所属行业为.{0,80}?中的[“\"](?P<name>[\u4e00-\u9fff、]{1,40}业)[”\"]"
    r"(?:,|\uff0c)?行业代码分别为(?P<csrc>[A-Z]\d{2})和(?P<national>[A-Z]\d{4})(?!\d)"
)
_CSRC_COMPANY_SCOPE_PATTERN: Final = re.compile(
    r"根据中国证监会.{0,20}?上市公司行业分类指引》?\(2012年修订\)"
    r"(?:,|\uff0c)?公司所处行业为(?P<name>[\u4e00-\u9fff、]{1,40}业)"
    r"\(分类代码:(?P<code>[A-Z]\d{2})\)"
)
_RESPONSE_ADAPTER: Final = TypeAdapter(CninfoAnnouncementResponse)


class AnnouncementSelectionError(Exception):
    """No unique authoritative listing announcement can be selected."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a stable announcement selection failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the official announcement blocker."""
        return f"cninfo_announcement: {self.detail}"


class IndustryDisclosureFailure(StrEnum):
    """Closed reason set for fail-closed disclosure parsing."""

    MISSING = "missing"
    CONFLICTING = "conflicting"


class IndustryDisclosureError(Exception):
    """An industry disclosure is missing or semantically ambiguous."""

    __slots__ = ("reason",)

    def __init__(self, reason: IndustryDisclosureFailure) -> None:
        """Create a stable disclosure parsing failure."""
        super().__init__()
        self.reason = reason

    def __str__(self) -> str:
        """Return the disclosure blocker."""
        return f"cninfo_industry_disclosure: {self.reason.value} explicit industry declaration"


@dataclass(frozen=True, slots=True)
class SelectedAnnouncement:
    """The final complete listing announcement selected from provider rows."""

    announcement_id: str
    title: str
    announcement_time_ms: int
    adjunct_url: str


@dataclass(frozen=True, slots=True)
class IndustryDisclosure:
    """One explicit industry code/name pair and its taxonomy evidence."""

    industry_code: str
    industry_name: str
    taxonomy: str
    matched_text: str


class _TitleParser(HTMLParser):
    """Mutable parser state strips provider highlighting tags safely."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def select_listing_announcement(payload: bytes) -> SelectedAnnouncement:
    """Select the latest final PDF while rejecting non-authoritative variants."""
    response = _RESPONSE_ADAPTER.validate_json(payload)
    candidates: list[tuple[CninfoAnnouncement, str]] = []
    for announcement in response.announcements or ():
        title = _plain_title(announcement.title_html)
        accepted = (
            "上市公告书" in title
            and announcement.adjunct_type.upper() == "PDF"
            and not any(marker in title for marker in _REJECTED_TITLE_MARKERS)
        )
        if accepted:
            candidates.append((announcement, title))
    if not candidates:
        detail = "no final complete listing announcement"
        raise AnnouncementSelectionError(detail)
    announcement, title = max(
        candidates,
        key=lambda item: (item[0].announcement_time_ms, item[0].announcement_id),
    )
    return SelectedAnnouncement(
        announcement_id=announcement.announcement_id,
        title=title,
        announcement_time_ms=announcement.announcement_time_ms,
        adjunct_url=announcement.adjunct_url,
    )


def select_prospectus(payload: bytes) -> SelectedAnnouncement:
    """Select the latest complete prospectus while rejecting drafts and summaries."""
    response = _RESPONSE_ADAPTER.validate_json(payload)
    candidates: list[tuple[CninfoAnnouncement, str]] = []
    for announcement in response.announcements or ():
        title = _plain_title(announcement.title_html)
        accepted = (
            "招股说明书" in title
            and announcement.adjunct_type.upper() == "PDF"
            and not any(marker in title for marker in _REJECTED_PROSPECTUS_MARKERS)
        )
        if accepted:
            candidates.append((announcement, title))
    if not candidates:
        detail = "no final complete prospectus"
        raise AnnouncementSelectionError(detail)
    announcement, title = max(
        candidates,
        key=lambda item: (item[0].announcement_time_ms, item[0].announcement_id),
    )
    return SelectedAnnouncement(
        announcement_id=announcement.announcement_id,
        title=title,
        announcement_time_ms=announcement.announcement_time_ms,
        adjunct_url=announcement.adjunct_url,
    )


def parse_industry_disclosure(text: str) -> IndustryDisclosure:
    """Extract one explicit industry declaration without business-text inference."""
    normalized = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
    matches: dict[tuple[str, str], str] = {}
    for company_scope in _CSRC_COMPANY_SCOPE_PATTERN.finditer(normalized):
        matches[(company_scope.group("code"), company_scope.group("name"))] = company_scope.group()
    for ordered in _ORDERED_TAXONOMY_CODES_PATTERN.finditer(normalized):
        matches[(ordered.group("csrc"), ordered.group("name"))] = ordered.group()
    for marker in _MARKER_PATTERN.finditer(normalized):
        window = normalized[marker.start() : marker.start() + 240]
        for code_match in _CODE_PATTERN.finditer(window):
            code = code_match.group()
            name = _industry_name(window, code_match.start(), code_match.end())
            if name is not None:
                matches[(code, name)] = window
    if not matches:
        raise IndustryDisclosureError(IndustryDisclosureFailure.MISSING)
    if len(matches) != 1:
        raise IndustryDisclosureError(IndustryDisclosureFailure.CONFLICTING)
    (code, name), matched_text = next(iter(matches.items()))
    return IndustryDisclosure(
        industry_code=code,
        industry_name=name,
        taxonomy=_taxonomy(normalized),
        matched_text=matched_text,
    )


def _plain_title(title_html: str) -> str:
    parser = _TitleParser()
    parser.feed(title_html)
    return "".join(parser.parts).strip()


def _industry_name(window: str, code_start: int, code_end: int) -> str | None:
    after = _NAME_AFTER_PATTERN.match(window[code_end : code_end + 45])
    if after is not None:
        return after.group("name")
    prefix = window[max(0, code_start - 80) : code_start]
    labeled = _NAME_BEFORE_CODE_LABEL_PATTERN.search(prefix)
    if labeled is not None:
        return labeled.group("name")
    before = _NAME_BEFORE_PATTERN.search(prefix)
    return before.group("name") if before is not None else None


def _taxonomy(normalized: str) -> str:
    if _CSRC_2012_PATTERN.search(normalized) is not None:
        return "CSRC_2012"
    if "中国上市公司协会上市公司行业统计分类指引" in normalized:
        return "CAPCO_2023"
    return "CSRC_UNVERSIONED"
