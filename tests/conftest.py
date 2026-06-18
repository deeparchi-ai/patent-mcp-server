"""Pytest fixtures for patent-mcp-server."""

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_bq_client() -> AsyncMock:
    """Mock BigQueryClient for unit tests that don't need real BigQuery."""
    client = AsyncMock()
    client.search_patents.return_value = []
    client.get_patent.return_value = None
    client.get_patent_claims.return_value = []
    client.get_citation_graph.return_value = None
    client.get_patent_family.return_value = None
    client.search_by_cpc.return_value = []
    client.search_by_assignee.return_value = []
    client.close = AsyncMock()
    return client
