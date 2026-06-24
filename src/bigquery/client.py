"""BigQuery client for patent-mcp-server — single connection, parameterized queries.

v1.6.0: Added default partition filter (after="2005-01-01") + dry-run budget checks.
       search_patents now defaults to last ~21 years instead of full-table scan.
       Queries that would scan > 10 GB are rejected; > 50 GB are rejected with warning.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from google.cloud import bigquery
from google.cloud.bigquery import ScalarQueryParameter

from bigquery.queries import (
    get_patent_claims_query,
    get_patent_query,
    search_patents_query,
)
from models.patent import (
    Citation,
    ClassificationCode,
    PatentBasic,
    PatentDetail,
)

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)

# ── Cost control thresholds ─────────────────────────────────────────
SCAN_WARNING_GB = 10   # warn if query scans > 10 GB
SCAN_REJECT_GB = 50    # reject if query would scan > 50 GB
SEARCH_DEFAULT_AFTER = "2005-01-01"  # partition filter: last ~21 years


class BigQueryError(Exception):
    """Base error for BigQuery operations."""


class PatentNotFoundError(BigQueryError):
    """Patent number not found in dataset."""


class BigQueryCostError(BigQueryError):
    """Query would scan too much data — rejected by budget guard."""


def _int_to_date(value: int | None) -> date | None:
    """Convert BigQuery int date (YYYYMMDD) to Python date."""
    if value is None or value == 0:
        return None
    s = str(value)
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _build_patent_basic(
    row: Any, *, url_base: str = "https://patents.google.com/patent"
) -> PatentBasic:
    """Build PatentBasic from a BigQuery row dict."""
    pub = str(row["publication_number"])

    title_en = row.get("title_en", "") or ""
    abstract_en = row.get("abstract_en", "") or ""
    title_zh = row.get("title_zh") or None
    abstract_zh = row.get("abstract_zh") or None

    assignees = row.get("assignee_harmonized") or []
    assignee = assignees[0]["name"] if assignees else None

    inventors_raw = row.get("inventor_harmonized") or []
    inventors = [inv["name"] for inv in inventors_raw if inv.get("name")]

    cpc_raw = row.get("cpc") or []
    cpc_codes = [c["code"] for c in cpc_raw if c.get("code")]

    return PatentBasic(
        publication_number=pub,
        title=title_en or pub,
        abstract=abstract_en or "",
        country_code=str(row.get("country_code", "")),
        zh_title=title_zh,
        zh_abstract=abstract_zh,
        filing_date=_int_to_date(row.get("filing_date")),
        grant_date=_int_to_date(row.get("grant_date")),
        assignee=assignee,
        inventors=inventors,
        cpc_codes=cpc_codes,
    )


def _build_patent_detail(row: Any) -> PatentDetail:
    """Build PatentDetail from a BigQuery row dict."""
    basic = _build_patent_basic(row)

    classifications: list[ClassificationCode] = []
    for scheme, key in [("CPC", "cpc"), ("IPC", "ipc")]:
        items = row.get(key) or []
        for item in items:
            if item.get("code"):
                classifications.append(
                    ClassificationCode(
                        code=item["code"],
                        scheme=scheme,
                        is_primary=item.get("first", False),
                    )
                )

    citations: list[Citation] = []
    for cit in row.get("citation") or []:
        citations.append(
            Citation(
                publication_number=cit.get("publication_number"),
                category=cit.get("category"),
                type=cit.get("type"),
                npl_text=cit.get("npl_text"),
            )
        )

    return PatentDetail(
        publication_number=basic.publication_number,
        title=basic.title,
        abstract=basic.abstract,
        country_code=basic.country_code,
        zh_title=basic.zh_title,
        zh_abstract=basic.zh_abstract,
        filing_date=basic.filing_date,
        grant_date=basic.grant_date,
        assignee=basic.assignee,
        inventors=basic.inventors,
        cpc_codes=basic.cpc_codes,
        kind_code=row.get("kind_code"),
        application_number=row.get("application_number"),
        family_id=row.get("family_id"),
        priority_date=_int_to_date(row.get("priority_date")),
        entity_status=row.get("entity_status"),
        art_unit=row.get("art_unit"),
        classifications=classifications,
        citations=citations,
    )


class BigQueryClient:
    """Singleton BigQuery client with parameterized queries.

    v1.6.0: search_patents defaults to after="2005-01-01" for partition pruning.
    All queries are dry-run checked: > 50 GB → rejected, > 10 GB → warning.
    """

    def __init__(self, project_id: str) -> None:
        if not project_id:
            raise ValueError("project_id is required")
        self.project_id = project_id
        self._client: bigquery.Client | None = None

    @property
    def client(self) -> bigquery.Client:
        if self._client is None:
            self._client = bigquery.Client(project=self.project_id)
        return self._client

    # ── Budget guard ────────────────────────────────────────────────

    def _check_budget(self, sql: str, params: list[ScalarQueryParameter]) -> None:
        """Run dry-run to estimate bytes scanned; reject if over threshold."""
        job_config = bigquery.QueryJobConfig(
            dry_run=True,
            query_parameters=params,
        )
        try:
            job = self.client.query(sql, job_config=job_config)
            gb = job.total_bytes_processed / 1e9 if job.total_bytes_processed else 0
        except Exception:
            logger.warning("Dry-run budget check failed — allowing query to proceed")
            return

        if gb > SCAN_REJECT_GB:
            raise BigQueryCostError(
                f"Query rejected: would scan {gb:.1f} GB "
                f"(max {SCAN_REJECT_GB} GB). Add filters (after/country/cpc)."
            )
        if gb > SCAN_WARNING_GB:
            logger.warning("Query will scan %.1f GB — add date filter to reduce cost", gb)

    # ── SQL builders (public for testing) ────────────────────────────

    @staticmethod
    def search_patents_sql(
        query: str | None = None,
        *,
        assignee: str | None = None,
        country: str | None = None,
        cpc: str | None = None,
        after: str | None = None,
        before: str | None = None,
        status: str | None = None,
        limit: int = 10,
    ) -> tuple[str, list[ScalarQueryParameter]]:
        # ── v1.6.0: default partition filter ──────────────────────────
        if after is None:
            after = SEARCH_DEFAULT_AFTER

        if not any([country, cpc, after, assignee]) and query:
            raise ValueError(
                "search_patents requires at least one filter "
                "(country, cpc, after, or assignee) to control scan cost"
            )
        return search_patents_query(  # type: ignore[no-any-return]
            query=query,
            assignee=assignee,
            country=country,
            cpc=cpc,
            after=after,
            before=before,
            status=status,
            limit=limit,
        )

    @staticmethod
    def get_patent_sql(publication_number: str) -> tuple[str, list[ScalarQueryParameter]]:
        return get_patent_query(publication_number)  # type: ignore[no-any-return]

    @staticmethod
    def get_patent_claims_sql(
        publication_number: str,
    ) -> tuple[str, list[ScalarQueryParameter]]:
        return get_patent_claims_query(publication_number)  # type: ignore[no-any-return]

    # ── Query execution ──────────────────────────────────────────────

    async def search_patents(
        self,
        query: str | None = None,
        *,
        assignee: str | None = None,
        country: str | None = None,
        cpc: str | None = None,
        after: str | None = None,
        before: str | None = None,
        status: str | None = None,
        limit: int = 10,
    ) -> list[PatentBasic]:
        # ── v1.6.0: enforce default partition filter ──────────────────
        if after is None:
            after = SEARCH_DEFAULT_AFTER

        sql, params = self.search_patents_sql(
            query=query,
            assignee=assignee,
            country=country,
            cpc=cpc,
            after=after,
            before=before,
            status=status,
            limit=limit,
        )
        self._check_budget(sql, params)
        job = self.client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
        results: list[PatentBasic] = []
        for row in job.result():
            results.append(_build_patent_basic(dict(row)))
        gb = (job.total_bytes_processed or 0) / 1e9
        logger.info("search_patents scanned %.3f GB, returned %d results", gb, len(results))
        import sys
        print(f"[COST] search_patents: {gb:.3f} GB scanned, {len(results)} results", file=sys.stderr, flush=True)
        return results

    async def get_patent(self, publication_number: str) -> PatentDetail:
        sql, params = self.get_patent_sql(publication_number)
        self._check_budget(sql, params)
        job = self.client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
        rows = list(job.result())
        gb = (job.total_bytes_processed or 0) / 1e9
        import sys
        print(f"[COST] get_patent: {gb:.3f} GB scanned", file=sys.stderr, flush=True)
        if not rows:
            raise PatentNotFoundError(f"Patent not found: {publication_number}")
        return _build_patent_detail(dict(rows[0]))

    async def get_patent_claims(self, publication_number: str) -> list[str]:
        sql, params = self.get_patent_claims_sql(publication_number)
        self._check_budget(sql, params)
        job = self.client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
        claims = [str(row["text"]) for row in job.result()]
        gb = (job.total_bytes_processed or 0) / 1e9
        import sys
        print(f"[COST] get_patent_claims: {gb:.3f} GB scanned", file=sys.stderr, flush=True)
        return claims
    async def close(self) -> None:
        if self._client is not None:
            self._client.close()  # type: ignore[no-untyped-call]
            self._client = None
