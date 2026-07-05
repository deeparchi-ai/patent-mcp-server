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
from typing import TYPE_CHECKING, Any

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

# Firecrawl search API — alternative backend when SearXNG engines are captcha-blocked
FIRECRAWL_API_KEY = os.environ.get(
    "FIRECRAWL_API_KEY", "fc-c53557ee24874f9bbce97cc538be1f09"
)
FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v1/search"

# Proxy for Google Patents (direct access blocked by CAPTCHA 2026-06-24)
# Inherits HTTPS_PROXY from environment. On Cloud Run (GCP), direct access
# to Google services is preferred — no proxy needed.
PROXIES = (
    {"https": os.environ["HTTPS_PROXY"]}
    if os.environ.get("HTTPS_PROXY") and "7897" in os.environ.get("HTTPS_PROXY", "")
    else None
)

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


def _retry_request(url: str, max_retries: int = 3) -> requests.Response:
    """GET with retry + exponential backoff for transient 5xx errors."""
    import time as _time

    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, proxies=PROXIES)
            if resp.status_code < 500:
                return resp
            logger.warning(
                "Google Patents %d (attempt %d/%d)",
                resp.status_code,
                attempt + 1,
                max_retries,
            )
        except requests.RequestException as e:
            last_exc = e
            logger.warning(
                "Google Patents request failed (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                e,
            )
        if attempt < max_retries - 1:
            _time.sleep(2**attempt)
    if last_exc:
        raise last_exc
    return resp


def fetch_patent(publication_number: str) -> PatentDetail:
    """Fetch patent details from Google Patents web page (free, no BigQuery cost)."""

    # Normalize: CN-119384988-A → CN119384988A
    pub_clean = publication_number.replace("-", "")
    url = GOOGLE_PATENTS_URL.format(pub=pub_clean)

    logger.info("Fetching %s", url)
    resp = _retry_request(url)
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
        contributors[-1]
        if len(contributors) > 1
        else (contributors[0] if contributors else None)
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
            zh_resp = requests.get(
                zh_url, headers=HEADERS, timeout=TIMEOUT, proxies=PROXIES
            )
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


def fetch_cited_by(
    publication_number: str,
) -> dict[str, Any]:
    """Fetch cited-by count from Google Patents web page (free).

    Extracts the number of patents that cite this patent from the patent
    detail page HTML.

    Returns:
        dict with keys:
          - cited_by_count: number of citing patents (int)
          - cited_by_patents: list of dicts with publication_number, title, assignee
          - cited_by_url: URL to view full cited-by list on Google Patents
    """
    pub_clean = publication_number.replace("-", "")
    url = GOOGLE_PATENTS_URL.format(pub=pub_clean)

    logger.info("Fetching cited-by from %s", url)
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    html = resp.text

    # Extract count from <h2>Cited By (N)</h2>
    count_match = re.search(
        r"<h2[^>]*>Cited\s+By\s*\((\d+)\)</h2>",
        html,
        re.IGNORECASE,
    )
    cited_by_count = int(count_match.group(1)) if count_match else 0

    cited_by_url = f"https://patents.google.com/patent/{pub_clean}/en/citedby"

    # Try to extract cited-by patent list from citedby page (includes cited-by
    # patents in static HTML when ?citedby URL param is used)
    cited_by_patents: list[dict[str, str]] = []
    if cited_by_count > 0:
        try:
            citedby_page_url = (
                f"https://patents.google.com/patent/{pub_clean}/en"
                f"?citedby&num={min(cited_by_count, 50)}"
            )
            logger.info("Fetching cited-by list from %s", citedby_page_url)
            resp2 = requests.get(citedby_page_url, headers=HEADERS, timeout=TIMEOUT)
            resp2.raise_for_status()
            resp2.encoding = "utf-8"
            page_html = resp2.text

            # Extract patent links from cited-by section
            # Pattern: /patent/CN123456A/ or /patent/CN123456B/
            patent_links = re.findall(
                r"/patent/([A-Z]{2}\d{5,12}[A-Z]\d?)/",
                page_html,
            )
            # Deduplicate, remove self-reference
            pub_clean.replace("A", "").replace("B", "").rstrip("0123456789")
            seen: set[str] = set()
            for p in patent_links:
                if p == pub_clean:
                    continue
                if p in seen:
                    continue
                seen.add(p)
                cited_by_patents.append(
                    {
                        "publication_number": p,
                    }
                )
        except Exception as e:
            logger.warning(
                "Failed to extract cited-by list for %s: %s", publication_number, e
            )

    return {
        "cited_by_count": cited_by_count,
        "cited_by_patents": cited_by_patents[:50],
        "cited_by_url": cited_by_url,
    }


def fetch_cited_by_with_details(
    publication_number: str,
    max_enrich: int = 8,
) -> dict[str, Any]:
    """Fetch cited-by count + list with title/assignee for top citing patents.

    Returns same as fetch_cited_by but first max_enrich cited_by_patents
    include title and assignee fields populated via individual patent fetches.
    Default max_enrich=8 to keep response time under ~10 seconds.
    """
    result = fetch_cited_by(publication_number)
    enriched: list[dict[str, str]] = []

    for i, p in enumerate(result["cited_by_patents"]):
        pn = p["publication_number"]
        if i < max_enrich:
            try:
                detail = fetch_patent(_normalize_patent_number(pn))
                enriched.append(
                    {
                        "publication_number": pn,
                        "title": detail.title or "",
                        "assignee": detail.assignee or "",
                    }
                )
            except Exception:
                enriched.append(
                    {
                        "publication_number": pn,
                        "title": "",
                        "assignee": "",
                    }
                )
        else:
            enriched.append(
                {
                    "publication_number": pn,
                    "title": "",
                    "assignee": "",
                }
            )

    result["cited_by_patents"] = enriched
    result["_enriched"] = min(max_enrich, len(enriched))
    return result


def competitor_citation_matrix(
    publication_numbers: list[str],
    competitor_keywords: list[str],
) -> dict[str, Any]:
    """Build competitor citation matrix for a set of target patents.

    For each target patent, fetches cited-by list and checks if any citing
    patent's assignee matches competitor keywords (case-insensitive substring).

    Args:
        publication_numbers: list of patent numbers to check (e.g. ['CN110286864A'])
        competitor_keywords: list of assignee name substrings to match
            (e.g. ['百度', 'Baidu', '华为', 'Huawei', 'Apple'])

    Returns:
        dict with keys:
          - matrix: {patent: [{citing_patent, title, assignee, matched_keyword}]}
          - summary: {competitor: total_citation_count}
    """
    matrix: dict[str, list[dict[str, str]]] = {}
    summary: dict[str, int] = {}

    for pn in publication_numbers:
        result = fetch_cited_by_with_details(pn)
        matches: list[dict[str, str]] = []

        for citing in result["cited_by_patents"]:
            assignee = citing.get("assignee", "").lower()
            for kw in competitor_keywords:
                if kw.lower() in assignee:
                    matches.append(
                        {
                            "citing_patent": citing["publication_number"],
                            "title": citing.get("title", ""),
                            "assignee": citing.get("assignee", ""),
                            "matched_keyword": kw,
                        }
                    )
                    summary[kw] = summary.get(kw, 0) + 1
                    break

        if matches:
            matrix[pn] = matches

    return {
        "matrix": matrix,
        "summary": summary,
    }


def bidirectional_citation_graph(
    assignee_name: str,
    competitor_keywords: list[str] | None = None,
    limit: int = 10,
) -> dict[str, object]:
    """Build full bidirectional citation graph for a company's core patents.

    Steps:
    1. Search for company's patents
    2. Get forward citations for each
    3. Get backward citations for each
    4. Build matrix
    5. If competitor_keywords provided, run competitor_citation_matrix

    Args:
        assignee_name: company name for patent search
        competitor_keywords: optional list of competitor assignee substrings
        limit: max patents to analyze (default 10)

    Returns:
        dict with keys: patents, forward_graph, backward_graph,
        competitor_matrix (if keywords provided)
    """
    # Step 1: Search for company's patents
    search_url = f"https://patents.google.com/?assignee=%22{assignee_name}%22&num={limit}&country=CN"
    logger.info("Searching patents for %s", assignee_name)
    resp = requests.get(search_url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    html = resp.text

    patent_links = re.findall(r"/patent/(CN\d{5,12}[A-Z]\d?)/", html)
    seen_pn: set[str] = set()
    patents: list[str] = []
    for p in patent_links:
        if p not in seen_pn:
            seen_pn.add(p)
            patents.append(p)
            if len(patents) >= limit:
                break

    logger.info("Found %d core patents for %s", len(patents), assignee_name)

    # Step 2+3: Forward + backward citations
    forward_graph: dict[str, list[str]] = {}
    backward_graph: dict[str, dict[str, Any]] = {}

    for pn in patents:
        try:
            detail = fetch_patent(_normalize_patent_number(pn))
            forward_graph[pn] = [c.publication_number for c in detail.citations]
        except Exception:
            forward_graph[pn] = []

        try:
            cb = fetch_cited_by(pn)
            backward_graph[pn] = {
                "count": cb["cited_by_count"],
                "patents": cb["cited_by_patents"],
            }
        except Exception:
            backward_graph[pn] = {"count": 0, "patents": []}

    result: dict[str, object] = {
        "assignee": assignee_name,
        "patents": patents,
        "forward_graph": forward_graph,
        "backward_graph": backward_graph,
    }

    # Step 5: Competitor matrix
    if competitor_keywords:
        result["competitor_matrix"] = competitor_citation_matrix(
            patents, competitor_keywords
        )

    return result


def fetch_claims(publication_number: str) -> list[str]:
    """Fetch claims text from Google Patents web page (free, saves ~35 GB BigQuery join)."""

    pub_clean = publication_number.replace("-", "")
    url = GOOGLE_PATENTS_URL.format(pub=pub_clean)

    logger.info("Fetching claims from %s", url)
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, proxies=PROXIES)
    resp.raise_for_status()
    resp.encoding = "utf-8"

    parser = _ClaimParser()
    parser.feed(resp.text)
    return parser.claims


# Regex to extract CN patent links from Google Patents HTML (href="/patent/CN123456A/")
_RELATED_CN_PATENT_RE = re.compile(
    r'href="/patent/(CN\d{7,14}[A-Z]?[0-9]?)/', re.IGNORECASE
)


def _firecrawl_search(query: str, limit: int = 10) -> list[dict[str, str]]:
    """Search via Firecrawl API — bypasses SearXNG CAPTCHA blocks.

    Returns list of {url, title, description} dicts.
    Costs 2 Firecrawl credits per search.
    """
    try:
        resp = requests.post(
            FIRECRAWL_SEARCH_URL,
            json={"query": query, "limit": limit},
            headers={
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            logger.warning("Firecrawl search failed: %s", data.get("error", "unknown"))
            return []

        # API returns data as either a list or {web: [...]}
        raw = data.get("data", [])
        items = raw if isinstance(raw, list) else raw.get("web", [])

        results = []
        for item in items:
            results.append(
                {
                    "url": item.get("url", ""),
                    "title": item.get("title", ""),
                    "content": item.get("description", ""),
                }
            )
        logger.info("Firecrawl search %r: %d results", query[:60], len(results))
        return results
    except Exception as e:
        logger.warning("Firecrawl search failed for %r: %s", query[:60], e)
        return []


def _discover_related_patents(
    patent_number: str,
    country: str | None = None,
    limit: int = 20,
) -> list[str]:
    """Scrape a Google Patents page for related/cited patent links.

    Google Patents individual pages (server-rendered HTML) contain links to similar,
    cited, and citing patents. This extracts CN patent numbers from those links.

    Args:
        patent_number: A patent number known to be in the target CPC class.
        country: Optional country filter (e.g., 'CN').
        limit: Maximum related patent numbers to return.

    Returns:
        List of normalized CN patent numbers (DOCDB format).
    """
    try:
        # Convert DOCDB format (CN-1409778) to URL format (CN1409778A)
        # Try multiple kind codes: A (application), B (granted), U (utility model)
        for kind in ("A", "B", "U", ""):
            url_pn = patent_number.replace("-", "")
            if kind and not url_pn[-1].isalpha():
                url_pn += kind
            url = GOOGLE_PATENTS_URL.format(pub=url_pn)
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, proxies=PROXIES)
            if resp.status_code == 200:
                break
            logger.debug(
                "Google Patents %s returned %d, trying next kind code",
                url_pn,
                resp.status_code,
            )
        else:
            logger.warning("No valid Google Patents URL found for %s", patent_number)
            return []

        matches = _RELATED_CN_PATENT_RE.findall(resp.text)
        seen: set[str] = set()
        result: list[str] = []
        for raw in matches:
            pn = _normalize_patent_number(raw)
            if pn in seen:
                continue
            if country and not pn.upper().startswith(country.upper()):
                continue
            seen.add(pn)
            result.append(pn)
            if len(result) >= limit:
                break

        logger.debug(
            "Discovered %d related CN patents from %s (out of %d links)",
            len(result),
            patent_number,
            len(matches),
        )
        return result
    except Exception as e:
        logger.warning(
            "Failed to discover related patents from %s: %s", patent_number, e
        )
        return []


def web_search_patents(
    cpc: str | None = None,
    query: str | None = None,
    country: str | None = None,
    limit: int = 10,
) -> list[PatentBasic]:
    """Search patents via SearXNG web search, then enrich via Google Patents scraping.

    Used as fallback when BigQuery returns zero results (or is cost-blocked) for
    CN+CPC queries where BigQuery's CPC classification coverage is sparse.

    Two-phase discovery:
      1. SearXNG web search for initial patent numbers
      2. Google Patents "related patent" crawling for expansion (CN only)

    Runs 3–4 varied search queries across 2 pages each, deduplicates,
    discovers related patents from Google Patents pages, then enriches
    all results via Google Patents web scraping.

    Args:
        cpc: CPC classification code (e.g., 'H01L25/065')
        query: Additional keyword query
        country: Country code filter (e.g., 'CN')
        limit: Maximum results to return

    Returns:
        List of PatentBasic objects with details from Google Patents web scraping.
    """
    is_cn = (country or "").upper() == "CN"

    # Choose engine based on what's working (as of 2026-06-24: Baidu/Google/Startpage blocked)
    search_params = {"engines": "duckduckgo"} if is_cn else {"engines": "bing"}

    # Build multiple search queries
    cpc_stripped = cpc.replace("/", " ") if cpc else ""
    cpc_quoted = f'"{cpc}"' if cpc else ""
    base_queries: list[str] = []
    if cpc:
        if is_cn:
            # DuckDuckGo engine: use English patent queries with CN filter
            base_queries = [
                f"site:patents.google.com {cpc_quoted} CN",
                f"{cpc_quoted} CN patent semiconductor packaging",
                f"{cpc_quoted} 中国专利 芯片封装",
            ]
        else:
            cpc_quoted = f'"{cpc}"'
            base_queries = [
                f"{cpc_quoted} {country or ''} patent semiconductor".strip(),
                f"{cpc_quoted} {country or ''} 专利 封装 芯片".strip(),
                f"{cpc_quoted} {country or ''} 半导体 封装".strip(),
            ]
    else:
        base_queries = [f"{query or ''} {country or ''} patent".strip()]

    logger.info(
        "Web search fallback: cpc=%s country=%s queries=%d engine=%s",
        cpc,
        country,
        len(base_queries),
        search_params.get("engines", "all"),
    )

    # Collect all results across queries and pages
    all_results: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    # For CN queries, skip SearXNG (all engines captcha-blocked or return junk)
    # and go straight to Firecrawl which reliably finds CN patent pages.
    if is_cn:
        logger.info("CN query — skipping SearXNG, using Firecrawl directly")
        fc_queries = [
            f"{cpc_stripped} 芯片 封装 中国专利",
            f"site:patents.google.com/patent/CN {cpc_stripped}",
        ]
        for fc_query in fc_queries[:2]:  # 2 queries = 4 credits
            fc_results = _firecrawl_search(fc_query, limit=10)
            for r in fc_results:
                url = r.get("url", "")
                if url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(r)
            if len(all_results) >= 20:
                break
    else:
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
                        params=params,  # type: ignore[arg-type]
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
                    logger.debug(
                        "Query %r page %d: %d results",
                        search_query[:50],
                        page,
                        len(page_results),
                    )
                    if not page_results:  # No more pages
                        break
                except Exception as e:
                    logger.warning(
                        "SearXNG search failed for %r page %d: %s",
                        search_query[:50],
                        page,
                        e,
                    )

    logger.info("Total search results: %d", len(all_results))

    # Extract patent numbers from search results
    seen: set[str] = set()
    patent_numbers: list[str] = []

    # First pass: extract from patents.google.com URLs
    for r in all_results:
        url = r.get("url", "")
        m = PATENT_NUMBER_RE.search(url)
        if m:
            raw_match = m.group(1) or m.group(
                2
            )  # group(1)=URL pattern, group(2)=bare CN
            pn = _normalize_patent_number(raw_match)
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
                raw_match = m.group(1) or m.group(2)
                pn = _normalize_patent_number(raw_match)
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

    # Phase 2: Discover related patents from Google Patents pages
    # Scrapes "similar/cited/citing" patent links to expand coverage
    if is_cn and len(patent_numbers) < limit:
        expansion_seeds = list(patent_numbers)  # copy before modification
        for seed in expansion_seeds[:5]:  # limit to 5 seeds to avoid too many requests
            related = _discover_related_patents(seed, country=country, limit=limit)
            for pn in related:
                if pn not in seen:
                    seen.add(pn)
                    patent_numbers.append(pn)
            if len(patent_numbers) >= limit:
                break
        logger.info(
            "After related-patent expansion: %d total patent numbers",
            len(patent_numbers),
        )

    # Build lookup: patent number → search result metadata (for fallback)
    pn_meta: dict[str, dict[str, str]] = {}
    for r in all_results:
        url = r.get("url", "")
        m = PATENT_NUMBER_RE.search(url)
        if m:
            raw_match = m.group(1) or m.group(2)
            pn = _normalize_patent_number(raw_match)
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
