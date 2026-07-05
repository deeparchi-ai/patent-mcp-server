"""Tests for BigQuery client — all mock-based, no quota consumed."""

import pytest

from bigquery.client import BigQueryClient, BigQueryError, PatentNotFoundError


class TestBigQueryClientInit:
    def test_requires_project_id(self) -> None:
        with pytest.raises(ValueError, match="project_id"):
            BigQueryClient(project_id="")

    def test_accepts_valid_project_id(self) -> None:
        client = BigQueryClient(project_id="test-project")
        assert client.project_id == "test-project"


class TestSearchPatentsValidation:
    def test_rejects_bare_keyword_without_filters(self) -> None:
        """Keyword-only search now gets a default 'after' partition filter (v1.6.0).
        The validation only fires if no filter at all is provided — but 'after'
        is now always defaulted, so bare keyword is no longer rejected."""
        sql, params = BigQueryClient(project_id="test").search_patents_sql(
            "artificial intelligence"
        )
        # With default after="2005-01-01", query should succeed with partition pruning
        assert "filing_date" in sql
        assert "@after" in sql

    def test_accepts_keyword_with_country(self) -> None:
        sql, params = BigQueryClient(project_id="test").search_patents_sql(
            "neural network", country="CN"
        )
        assert "country_code" in sql
        assert "@country" in sql

    def test_accepts_keyword_with_cpc(self) -> None:
        sql, params = BigQueryClient(project_id="test").search_patents_sql(
            "semiconductor", cpc="H01L"
        )
        assert "cpc" in sql.lower()

    def test_accepts_assignee_only_without_query(self) -> None:
        """Assignee-only search for company-level patent landscape."""
        sql, params = BigQueryClient(project_id="test").search_patents_sql(assignee="BOE", limit=5)
        assert "@assignee" in sql
        assert "REGEXP_CONTAINS" in sql
        assert "assignee_harmonized" in sql
        assert "LIMIT" in sql
        # Find the assignee param by value (order may vary due to default 'after')
        assignee_params = [p for p in params if p.value == "(^| )boe( |$)"]
        assert len(assignee_params) == 1

    def test_assignee_no_longer_matches_substring(self) -> None:
        """Space-anchored regex: BOE should NOT match BOEING."""
        sql, params = BigQueryClient(project_id="test").search_patents_sql(
            assignee="BOE", country="US", limit=5
        )
        assert "REGEXP_CONTAINS" in sql
        assert params[0].value == "(^| )boe( |$)"

    def test_accepts_keyword_with_date(self) -> None:
        sql, params = BigQueryClient(project_id="test").search_patents_sql(
            "blockchain", after="2020-01-01"
        )
        assert "filing_date" in sql

    def test_accepts_country_only_without_query(self) -> None:
        """Country-only search should work (landscape browsing)."""
        sql, params = BigQueryClient(project_id="test").search_patents_sql(country="CN", limit=5)
        assert "country_code" in sql
        assert "LIMIT" in sql


class TestGetPatentSQL:
    def test_builds_lookup_query(self) -> None:
        sql, params = BigQueryClient(project_id="test").get_patent_sql("US-7650331-B1")
        assert "publication_number" in sql
        assert "@pub_number" in sql
        assert params[0].value == "US-7650331-B1"


class TestErrorClasses:
    def test_bigquery_error(self) -> None:
        with pytest.raises(BigQueryError):
            raise BigQueryError("connection failed")

    def test_patent_not_found(self) -> None:
        with pytest.raises(PatentNotFoundError):
            raise PatentNotFoundError("CN-0000000-A")
        # PatentNotFoundError is a subclass of BigQueryError
        assert issubclass(PatentNotFoundError, BigQueryError)


class TestCostLogging:
    """v2.12: every BigQuery execution path must log [COST] with bytes scanned."""

    def test_get_family_step1_lookup_logs_cost(self, capsys) -> None:
        import asyncio
        from unittest.mock import MagicMock

        client = BigQueryClient(project_id="test-project")
        mock_bq = MagicMock()
        client._client = mock_bq

        step1_job = MagicMock()
        step1_job.result.return_value = [
            {"publication_number": "US-1-A", "family_id": "F123", "country_code": "US"}
        ]
        step1_job.total_bytes_processed = int(5e9)

        step2_job = MagicMock()
        step2_job.result.return_value = []
        step2_job.total_bytes_processed = int(1e9)

        mock_bq.query.side_effect = [step1_job, step2_job]

        asyncio.new_event_loop().run_until_complete(client.get_family("US-1-A"))

        err = capsys.readouterr().err
        assert "[COST] get_family lookup: 5.000 GB scanned" in err
