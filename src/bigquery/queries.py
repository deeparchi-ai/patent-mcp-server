"""Parameterized BigQuery SQL queries for patent-mcp-server."""

import re

from google.cloud.bigquery import ScalarQueryParameter


def _param_type(value: str) -> str:
    """Map Python type to BigQuery parameter type string."""
    return "STRING"


def search_patents_query(
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
    """Build parameterized search query.

    At least one of assignee/country/cpc/after must be provided to control scan cost.
    """
    params: list[ScalarQueryParameter] = []
    conditions: list[str] = []
    table = "`patents-public-data.patents.publications`"

    # Keyword search on English abstract
    if query:
        conditions.append(
            "LOWER((SELECT text FROM UNNEST(abstract_localized) "
            "WHERE language='en' LIMIT 1)) LIKE LOWER(@query)"
        )
        params.append(ScalarQueryParameter("query", "STRING", f"%{query}%"))

    # Assignee filter — word-boundary match on harmonized assignee names.
    # RE2 (BigQuery's regex engine) does NOT support \b word boundaries.
    # Instead use (^| )keyword( |$) which matches:
    #   - "BOE" in "BOE TECHNOLOGY"  ✓
    #   - "BOE" in "BEIJING BOE OPTO" ✓
    #   - "BOE" at end of name       ✓
    #   - "BOEING" (no space after)  ✗ (correctly excluded)
    if assignee:
        escaped = re.escape(assignee.lower()).replace(r"\ ", " ")
        conditions.append(
            "EXISTS (SELECT 1 FROM UNNEST(assignee_harmonized) "
            "WHERE REGEXP_CONTAINS(LOWER(name), @assignee))"
        )
        params.append(ScalarQueryParameter("assignee", "STRING", f"(^| ){escaped}( |$)"))

    # Country filter
    if country:
        conditions.append("country_code = @country")
        params.append(ScalarQueryParameter("country", "STRING", country))

    # CPC filter — match prefix
    if cpc:
        conditions.append("EXISTS (SELECT 1 FROM UNNEST(cpc) WHERE code LIKE @cpc)")
        params.append(ScalarQueryParameter("cpc", "STRING", f"{cpc}%"))

    # Date range
    if after:
        conditions.append("filing_date >= @after")
        params.append(ScalarQueryParameter("after", "INT64", int(after.replace("-", ""))))
    if before:
        conditions.append("filing_date <= @before")
        params.append(ScalarQueryParameter("before", "INT64", int(before.replace("-", ""))))

    # Status filter
    if status:
        if status == "grant":
            conditions.append("grant_date > 0")
        elif status == "application":
            conditions.append("grant_date = 0")

    where = " AND ".join(conditions) if conditions else "TRUE"

    sql = f"""
        SELECT
            publication_number,
            (SELECT text FROM UNNEST(title_localized)
             WHERE language='en' LIMIT 1) AS title_en,
            (SELECT text FROM UNNEST(title_localized)
             WHERE language='zh' LIMIT 1) AS title_zh,
            (SELECT text FROM UNNEST(abstract_localized)
             WHERE language='en' LIMIT 1) AS abstract_en,
            (SELECT text FROM UNNEST(abstract_localized)
             WHERE language='zh' LIMIT 1) AS abstract_zh,
            filing_date,
            grant_date,
            inventor_harmonized,
            assignee_harmonized,
            country_code
        FROM {table}
        WHERE {where}
        LIMIT {limit}
    """
    return sql, params


def get_patent_query(publication_number: str) -> tuple[str, list[ScalarQueryParameter]]:
    """Build query for single patent lookup."""
    params: list[ScalarQueryParameter] = [
        ScalarQueryParameter("pub_number", "STRING", publication_number),
    ]
    table = "`patents-public-data.patents.publications`"

    sql = f"""
        SELECT
            publication_number,
            (SELECT text FROM UNNEST(title_localized)
             WHERE language='en' LIMIT 1) AS title_en,
            (SELECT text FROM UNNEST(title_localized)
             WHERE language='zh' LIMIT 1) AS title_zh,
            (SELECT text FROM UNNEST(abstract_localized)
             WHERE language='en' LIMIT 1) AS abstract_en,
            (SELECT text FROM UNNEST(abstract_localized)
             WHERE language='zh' LIMIT 1) AS abstract_zh,
            country_code,
            kind_code,
            application_number,
            family_id,
            filing_date,
            grant_date,
            priority_date,
            entity_status,
            art_unit,
            inventor_harmonized,
            assignee_harmonized,
            cpc,
            ipc,
            citation
        FROM {table}
        WHERE publication_number = @pub_number
        LIMIT 1
    """
    return sql, params


def get_patent_claims_query(publication_number: str) -> tuple[str, list[ScalarQueryParameter]]:
    """Build query for US patent claims via patentsview."""
    parts = publication_number.split("-")
    if len(parts) < 2:
        raise ValueError(f"Invalid publication number format: {publication_number}")
    patent_number = parts[1]

    params: list[ScalarQueryParameter] = [
        ScalarQueryParameter("patent_number", "STRING", patent_number),
    ]

    sql = """
        SELECT c.text
        FROM `patents-public-data.patentsview.claim` AS c
        JOIN `patents-public-data.patentsview.patent` AS p
          ON c.patent_id = p.id
        WHERE p.number = @patent_number
        ORDER BY CAST(c.sequence AS INT64)
    """
    return sql, params
