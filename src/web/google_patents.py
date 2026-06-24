"""Google Patents web scraper — zero-cost alternative to BigQuery for single patent lookups.
Also includes web search fallback via SearXNG for CN CPC queries where BigQuery coverage is sparse.

Uses server-rendered HTML (no JS needed) with Dublin Core meta tags.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date
from html.parser import HTMLParser
from typing import TYPE_CHECKING

import requests

from models.patent import Citation, ClassificationCode, PatentBasic, PatentDetail

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

GOOGLE_PATENTS_URL = "https://patents.google.com/patent/{pub}/en"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
TIMEOUT = 15

# SearXNG endpoint for web search fallback (used when BigQuery CN CPC coverage is sparse)
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8888")

# Regex to extract patent numbers from URLs and text.
# Covers Google Patents (patent/CN123456789A), wanfang (patent/CN202310083015.8),
# tianyancha (/da672e95...), and plain CN number patterns.
PATENT_NUMBER_RE = re.compile(
    r"(?:patent/|patent=)([A-Z]{2,4}[\-\s]?[0-9]{5,14}[A-Z]?[0-9]?)"
    r"|[^/\w](CN[\-\s]?[0-9]{7,13}[A-Z]?[0-9]?)",
    re.IGNORECASE,
)

# Normalize patent number to DOCDB format: US7650331B2 → US-7650331-B2
_PATENT_PARTS_RE = re.compile(r"^([A-Z]{2,4})([0-9]{5,12})([A-Z][0-9]?)?$")


def _normalize_patent_number(raw: str) -> str:
    """Normalize a patent number string to DOCDB format (US-7650331-B2)."""
    clean = raw.replace(" ", "").replace("-", "").upper()
    m = _PATENT_PARTS_RE.match(clean)
    if not m:
        return raw
    country, number, kind = m.groups()
    if kind:
        return f"{country}-{number}-{kind}"
    return f"{country}-{number}"


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


def web_search_patents(
    cpc: str | None = None,
    query: str | None = None,
    country: str | None = None,
    limit: int = 10,
) -> list[PatentBasic]:
    """Search patents via SearXNG web search, then enrich via Google Patents scraping.

    Used as fallback when BigQuery returns zero results (or is cost-blocked) for
    CN+CPC queries where BigQuery's CPC classification coverage is sparse.

    For CN queries: uses Baidu engine via SearXNG (Google/DuckDuckGo often CAPTCHA-blocked).
    For non-CN: uses all available SearXNG engines.

    Runs 3 varied search queries across 2 pages each, then deduplicates and enriches.

    Args:
        cpc: CPC classification code (e.g., 'H01L25/065')
        query: Additional keyword query
        country: Country code filter (e.g., 'CN')
        limit: Maximum results to return

    Returns:
        List of PatentBasic objects with details from Google Patents web scraping.
    """
    is_cn = (country or "").upper() == "CN"

    # Build multiple search queries — Chinese for CN, English otherwise
    cpc_stripped = cpc.replace("/", " ") if cpc else ""
    base_queries: list[str] = []
    if cpc:
        if is_cn:
            base_queries = [
                f'{cpc} CN 专利 半导体 封装',
                f'{cpc} CN 专利 patents.google.com',
                f'{cpc} CN 专利 wanfangdata patent',
            ]
        else:
            cpc_quoted = f'"{cpc}"'
            base_queries = [
                f'{cpc_quoted} {country or ""} patent semiconductor'.strip(),
                f'{cpc_quoted} {country or ""} 专利 封装 芯片'.strip(),
                f'{cpc_quoted} {country or ""} 半导体 封装'.strip(),
            ]
    else:
        base_queries = [f'{query or ""} {country or ""} patent'.strip()]

    # Choose engine + extra params based on country
    if is_cn:
        search_params = {
            "engines": "baidu",
            "language": "zh-CN",
        }
    else:
        search_params = {}

    logger.info(
        "Web search fallback: cpc=%s country=%s queries=%d engine=%s",
        cpc, country, len(base_queries),
        search_params.get("engines", "all"),
    )

    # Collect all results across queries and pages
    all_results: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for search_query in base_queries:
        for page in [1, 2]:
            try:
                params = {
                    "q": search_query,
                    "format": "json",
                    "categories": "general",
                    "pageno": page,
                    **search_params,
                }
                resp = requests.get(
                    f"{SEARXNG_URL}/search",
                    params=params,
                    headers=HEADERS,
                    timeout=20,
                )
                resp.raise_for_status()
                data = resp.json()
                page_results = data.get("results", [])
                for r in page_results:
                    url = r.get("url", "")
                    if url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append(r)
                logger.debug("Query %r page %d: %d results", search_query[:50], page, len(page_results))
                if not page_results:  # No more pages
                    break
            except Exception as e:
                logger.warning("SearXNG search failed for %r page %d: %s", search_query[:50], page, e)

    logger.info("SearXNG returned %d unique results across all queries", len(all_results))

    # Extract patent numbers from search results
    seen: set[str] = set()
    patent_numbers: list[str] = []

    # First pass: extract from patents.google.com URLs
    for r in all_results:
        url = r.get("url", "")
        m = PATENT_NUMBER_RE.search(url)
        if m:
            pn = _normalize_patent_number(m.group(1))
            if pn not in seen:
                if country and not pn.upper().startswith(country.upper()):
                    continue
                seen.add(pn)
                patent_numbers.append(pn)

    # Second pass: extract from any text if we need more
    if len(patent_numbers) < limit:
        for r in all_results:
            text = r.get("title", "") + " " + r.get("content", "")
            for m in PATENT_NUMBER_RE.finditer(text):
                pn = _normalize_patent_number(m.group(1))
                if pn not in seen:
                    if country and not pn.upper().startswith(country.upper()):
                        continue
                    seen.add(pn)
                    patent_numbers.append(pn)
                    if len(patent_numbers) >= limit:
                        break
            if len(patent_numbers) >= limit:
                break

    logger.info(
        "Extracted %d patent numbers (filtered to %s): %s",
        len(patent_numbers),
        country or "any",
        patent_numbers[:5],
    )

    # Build lookup: patent number → search result metadata (for fallback)
    pn_meta: dict[str, dict[str, str]] = {}
    for r in all_results:
        url = r.get("url", "")
        m = PATENT_NUMBER_RE.search(url)
        if m:
            pn = _normalize_patent_number(m.group(1))
            if pn not in pn_meta:
                pn_meta[pn] = {
                    "title": r.get("title", ""),
                    "snippet": r.get("content", "")[:500],
                    "url": url,
                }

    # Enrich each patent via web scraping
    # Falls back to SearXNG metadata when Google Patents fetch fails
    enriched: list[PatentBasic] = []
    for pn in patent_numbers[:limit]:
        try:
            detail = fetch_patent(pn)
            enriched.append(
                PatentBasic(
                    publication_number=detail.publication_number,
                    title=detail.title,
                    abstract=detail.abstract,
                    country_code=detail.country_code,
                    zh_title=detail.zh_title,
                    zh_abstract=detail.zh_abstract,
                    filing_date=detail.filing_date,
                    grant_date=detail.grant_date,
                    assignee=detail.assignee,
                    inventors=detail.inventors,
                    cpc_codes=detail.cpc_codes,
                )
            )
        except Exception as e:
            logger.warning(
                "Failed to fetch details for %s: %s — using search metadata", pn, e
            )
            meta = pn_meta.get(pn, {})
            enriched.append(
                PatentBasic(
                    publication_number=pn,
                    title=meta.get("title", pn),
                    abstract=meta.get("snippet", ""),
                    country_code=pn[:2],
                )
            )

    logger.info("Web search enriched %d patents", len(enriched))
    return enriched
