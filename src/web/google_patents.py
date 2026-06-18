"""Google Patents web scraper — zero-cost alternative to BigQuery for single patent lookups.

Uses server-rendered HTML (no JS needed) with Dublin Core meta tags.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from html.parser import HTMLParser
from typing import TYPE_CHECKING

import requests

from models.patent import Citation, ClassificationCode, PatentDetail

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

GOOGLE_PATENTS_URL = "https://patents.google.com/patent/{pub}/en"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
TIMEOUT = 15


class _MetaParser(HTMLParser):
    """Extract Dublin Core + citation meta tags from <head>."""

    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        d = dict(attrs)
        name = d.get("name", "") or d.get("itemprop", "")
        content = d.get("content", "")
        if name and content:
            self.meta.setdefault(name, []).append(content)


class _ClaimParser(HTMLParser):
    """Extract claim text from <div class='claim'> elements."""

    def __init__(self) -> None:
        super().__init__()
        self.claims: list[str] = []
        self._in_claim = False
        self._depth = 0
        self._current: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        if tag == "div" and d.get("class", "") == "claim":
            self._in_claim = True
            self._depth = 1
            self._current = []
        elif self._in_claim:
            self._depth += 1

    def handle_data(self, data: str) -> None:
        if self._in_claim:
            text = data.strip()
            if text:
                self._current.append(text)

    def handle_endtag(self, tag: str) -> None:
        if self._in_claim:
            self._depth -= 1
            if self._depth == 0:
                self._in_claim = False
                if self._current:
                    self.claims.append(" ".join(self._current))


def fetch_patent(publication_number: str) -> PatentDetail:
    """Fetch patent details from Google Patents web page (free, no BigQuery cost)."""

    # Normalize: CN-119384988-A → CN119384988A
    pub_clean = publication_number.replace("-", "")
    url = GOOGLE_PATENTS_URL.format(pub=pub_clean)

    logger.info("Fetching %s", url)
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    html = resp.text

    # Parse meta tags
    meta_parser = _MetaParser()
    meta_parser.feed(html)
    meta = meta_parser.meta

    # Title: from DC.title (first entry)
    title = ""
    for t in meta.get("DC.title", []):
        cleaned = t.strip()
        if cleaned:
            title = cleaned
            break

    # Abstract: from DC.description or meta description
    abstract = ""
    for desc in meta.get("DC.description", []):
        cleaned = desc.strip()
        if cleaned:
            abstract = cleaned
            break

    # Inventors and Assignee: DC.contributor without scheme=inventor/assignee in meta.
    # Convention: last contributor is assignee, rest are inventors.
    contributors = meta.get("DC.contributor", [])
    inventors: list[str] = contributors[:-1] if len(contributors) > 1 else contributors
    assignee = (
        contributors[-1] if len(contributors) > 1 else (contributors[0] if contributors else None)
    )

    # CPC codes: extract from classification links in HTML
    cpc_codes: list[str] = []
    for m in re.finditer(r"/cpc/([A-Z][0-9]{2}[A-Z][0-9/]+)", html):
        cpc_codes.append(m.group(1))
    cpc_codes = list(dict.fromkeys(cpc_codes))  # dedupe preserve order
    classifications: list[ClassificationCode] = [
        ClassificationCode(code=c, scheme="CPC") for c in cpc_codes
    ]

    # Dates
    filing_date: date | None = None
    pub_date: date | None = None
    for d in meta.get("DC.date", []):
        try:
            parsed = date.fromisoformat(d)
            if filing_date is None:
                filing_date = parsed
            elif pub_date is None:
                pub_date = parsed
        except ValueError:
            pass

    # Citations
    citations: list[Citation] = []
    for ref in meta.get("DC.relation", []):
        # Format: "KR:20150130898:A" or "CN:106489600:A"
        citations.append(Citation(publication_number=ref.replace(":", "-")))

    # Country code from publication number
    country_code = pub_clean[:2]

    # Chinese title/abstract — fetch /zh page for CN patents
    zh_title: str | None = None
    zh_abstract: str | None = None
    if country_code == "CN":
        try:
            zh_url = f"https://patents.google.com/patent/{pub_clean}/zh"
            zh_resp = requests.get(zh_url, headers=HEADERS, timeout=TIMEOUT)
            zh_resp.encoding = "utf-8"
            zh_html = zh_resp.text

            # Parse DC.title from Chinese page
            zh_parser = _MetaParser()
            zh_parser.feed(zh_html)
            zh_meta = zh_parser.meta

            for t in zh_meta.get("DC.title", []):
                cleaned = t.strip()
                if cleaned:
                    zh_title = cleaned
                    break
            for desc in zh_meta.get("DC.description", []):
                cleaned = desc.strip()
                if cleaned:
                    zh_abstract = cleaned
                    break
        except Exception:
            logger.debug("Failed to fetch Chinese page for %s", publication_number)

    return PatentDetail(
        publication_number=publication_number,
        title=title or publication_number,
        abstract=abstract or "",
        country_code=country_code,
        zh_title=zh_title,
        zh_abstract=zh_abstract,
        filing_date=filing_date,
        grant_date=None,
        assignee=assignee,
        inventors=inventors,
        cpc_codes=cpc_codes,
        kind_code=None,
        application_number=None,
        family_id=None,
        priority_date=None,
        entity_status=None,
        art_unit=None,
        classifications=classifications,
        citations=citations,
    )


def fetch_claims(publication_number: str) -> list[str]:
    """Fetch claims text from Google Patents web page (free, saves ~35 GB BigQuery join)."""

    pub_clean = publication_number.replace("-", "")
    url = GOOGLE_PATENTS_URL.format(pub=pub_clean)

    logger.info("Fetching claims from %s", url)
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"

    parser = _ClaimParser()
    parser.feed(resp.text)
    return parser.claims
