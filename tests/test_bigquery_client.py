"""Tests for BigQuery client — all mock-based, no quota consumed."""

import pytest

from bigquery.client import BigQueryClient, BigQueryCostError, BigQueryError, PatentNotFoundError


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

        result = asyncio.run(client.get_family("US-1-A"))

        err = capsys.readouterr().err
        assert "[COST] get_family lookup: 5.000 GB scanned" in err
        assert result["publication_number"] == "US-1-A"


class TestHardCostCap:
    """v2.12: every real execution carries maximum_bytes_billed; dry-run must not."""

    def _client_with_job(self, rows=None, bytes_processed=0):
        from unittest.mock import MagicMock

        client = BigQueryClient(project_id="test-project")
        mock_bq = MagicMock()
        client._client = mock_bq
        job = MagicMock()
        job.result.return_value = rows if rows is not None else []
        job.total_bytes_processed = bytes_processed
        mock_bq.query.return_value = job
        return client, mock_bq

    def test_get_patent_claims_config_has_max_bytes_billed(self) -> None:
        import asyncio

        client, mock_bq = self._client_with_job(rows=[{"text": "claim 1"}])
        asyncio.run(client.get_patent_claims("US-1-A"))
        cfg = mock_bq.query.call_args.kwargs["job_config"]
        assert cfg.maximum_bytes_billed == 500 * 10**9

    def test_env_override_changes_cap(self, monkeypatch) -> None:
        import asyncio

        monkeypatch.setenv("PATENT_MCP_MAX_BYTES_BILLED_GB", "100")
        client, mock_bq = self._client_with_job(rows=[{"text": "claim 1"}])
        asyncio.run(client.get_patent_claims("US-1-A"))
        cfg = mock_bq.query.call_args.kwargs["job_config"]
        assert cfg.maximum_bytes_billed == 100 * 10**9

    def test_search_dry_run_has_no_cap_but_real_call_does(self) -> None:
        import asyncio

        client, mock_bq = self._client_with_job()
        asyncio.run(
            client.search_patents(query="agent", country="US")
        )
        configs = [c.kwargs["job_config"] for c in mock_bq.query.call_args_list]
        dry = [c for c in configs if getattr(c, "dry_run", False)]
        real = [c for c in configs if not getattr(c, "dry_run", False)]
        assert dry and real, "search must issue one dry-run + one real query"
        assert dry[0].maximum_bytes_billed is None
        assert all(c.maximum_bytes_billed == 500 * 10**9 for c in real)

    def test_env_change_after_client_init_takes_effect(self, monkeypatch) -> None:
        import asyncio

        client, mock_bq = self._client_with_job(rows=[{"text": "claim 1"}])
        asyncio.run(client.get_patent_claims("US-1-A"))
        cfg_before = mock_bq.query.call_args.kwargs["job_config"]
        assert cfg_before.maximum_bytes_billed == 500 * 10**9

        monkeypatch.setenv("PATENT_MCP_MAX_BYTES_BILLED_GB", "42")
        asyncio.run(client.get_patent_claims("US-2-B"))  # different patent → cache miss
        cfg_after = mock_bq.query.call_args.kwargs["job_config"]
        assert cfg_after.maximum_bytes_billed == 42 * 10**9

    def test_cap_is_read_lazily_at_query_time(self, monkeypatch) -> None:
        import asyncio

        client, mock_bq = self._client_with_job(rows=[{"text": "claim 1"}])
        asyncio.run(client.get_patent_claims("US-1-A"))
        first = mock_bq.query.call_args.kwargs["job_config"].maximum_bytes_billed
        monkeypatch.setenv("PATENT_MCP_MAX_BYTES_BILLED_GB", "7")
        client._query_cache.clear()  # bypass memoization; second call must hit query path
        asyncio.run(client.get_patent_claims("US-1-A"))
        second = mock_bq.query.call_args.kwargs["job_config"].maximum_bytes_billed
        assert first == 500 * 10**9
        assert second == 7 * 10**9



class TestCostErrorMapping:
    """v2.12: engine-side cost kills surface as BigQueryCostError, not raw API errors."""

    def _client_raising(self, exc):
        from unittest.mock import MagicMock

        client = BigQueryClient(project_id="test-project")
        mock_bq = MagicMock()
        client._client = mock_bq
        mock_bq.query.side_effect = exc
        return client

    def test_bytes_billed_limit_maps_to_cost_error(self) -> None:
        import asyncio

        from google.api_core.exceptions import BadRequest

        client = self._client_raising(
            BadRequest("Query exceeded limit for bytes billed: 500000000000")
        )
        with pytest.raises(BigQueryCostError):
            asyncio.run(client.get_patent("US-1-A"))

    def test_custom_quota_maps_to_cost_error(self) -> None:
        import asyncio

        from google.api_core.exceptions import Forbidden

        client = self._client_raising(
            Forbidden("quotaExceeded: Custom quota exceeded for query/usage per day")
        )
        with pytest.raises(BigQueryCostError):
            asyncio.run(client.get_patent_claims("US-1-A"))

    def test_unrelated_badrequest_passes_through(self) -> None:
        import asyncio

        from google.api_core.exceptions import BadRequest

        client = self._client_raising(BadRequest("Syntax error at [1:10]"))
        with pytest.raises(BadRequest):
            asyncio.run(client.get_patent("US-1-A"))
