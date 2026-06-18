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
        """Must require at least one of country/cpc/after."""
        client = BigQueryClient(project_id="test")
        with pytest.raises(ValueError, match="at least one filter"):
            client.search_patents_sql("artificial intelligence")

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
