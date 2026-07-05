"""Tests for MCP Server: tool registration, schema, handler behavior."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import CallToolRequest, ListToolsRequest


def _make_call_req(name: str, args: dict | None = None) -> CallToolRequest:
    return CallToolRequest(
        method="tools/call",
        params={"name": name, "arguments": args or {}},
    )


class TestToolRegistration:
    def test_registers_list_tools_handler(self) -> None:
        with (
            patch("server.BigQueryClient") as mock_cls,
            patch("bigquery.client.bigquery.Client", MagicMock()),
        ):
            mock_cls.return_value = AsyncMock()
            from server import create_server

            server = create_server("test-project")
            assert ListToolsRequest in server.request_handlers

    def test_registers_call_tool_handler(self) -> None:
        with (
            patch("server.BigQueryClient") as mock_cls,
            patch("bigquery.client.bigquery.Client", MagicMock()),
        ):
            mock_cls.return_value = AsyncMock()
            from server import create_server

            server = create_server("test-project")
            assert CallToolRequest in server.request_handlers

    def test_list_tools_returns_three_names(self) -> None:
        with (
            patch("server.BigQueryClient") as mock_cls,
            patch("bigquery.client.bigquery.Client", MagicMock()),
        ):
            mock_cls.return_value = AsyncMock()
            from server import create_server

            server = create_server("test-project")
            fn = server.request_handlers[ListToolsRequest]
            result = asyncio.run(fn(ListToolsRequest(method="tools/list", params=None)))
            names = [t.name for t in result.root.tools]
            assert "search_patents" in names
            assert "get_patent" in names
            assert "get_patent_claims" in names


class TestSearchPatentsHandler:
    def test_rejects_missing_filters(self) -> None:
        with (
            patch("server.BigQueryClient") as mock_cls,
            patch("bigquery.client.bigquery.Client", MagicMock()),
        ):
            mock_client = AsyncMock()
            mock_client.search_patents.side_effect = ValueError("at least one filter")
            mock_cls.return_value = mock_client
            from server import create_server

            server = create_server("test-project")

            fn = server.request_handlers[CallToolRequest]
            result = asyncio.run(fn(_make_call_req("search_patents", {"query": "AI"})))
            assert "invalid_input" in result.root.content[0].text

    def test_accepts_country_filter(self) -> None:
        with (
            patch("server.BigQueryClient") as mock_cls,
            patch("bigquery.client.bigquery.Client", MagicMock()),
        ):
            mock_client = AsyncMock()
            mock_client.search_patents.return_value = []
            mock_cls.return_value = mock_client
            from server import create_server

            server = create_server("test-project")

            fn = server.request_handlers[CallToolRequest]
            result = asyncio.run(
                fn(
                    _make_call_req(
                        "search_patents",
                        {
                            "query": "neural network",
                            "country": "CN",
                        },
                    )
                )
            )
            assert result.root.content[0].type == "text"


class TestGetPatentHandler:
    def test_handles_not_found(self) -> None:
        with (
            patch("server.BigQueryClient") as mock_cls,
            patch("bigquery.client.bigquery.Client", MagicMock()),
        ):
            mock_client = AsyncMock()
            from bigquery.client import PatentNotFoundError

            mock_client.get_patent.side_effect = PatentNotFoundError("CN-0000000-A")
            mock_cls.return_value = mock_client
            from server import create_server

            server = create_server("test-project")

            fn = server.request_handlers[CallToolRequest]
            result = asyncio.run(
                fn(_make_call_req("get_patent", {"publication_number": "CN-0000000-A"}))
            )
            assert "not_found" in result.root.content[0].text

    def test_unknown_tool(self) -> None:
        with (
            patch("server.BigQueryClient") as mock_cls,
            patch("bigquery.client.bigquery.Client", MagicMock()),
        ):
            mock_cls.return_value = AsyncMock()
            from server import create_server

            server = create_server("test-project")

            fn = server.request_handlers[CallToolRequest]
            result = asyncio.run(fn(_make_call_req("nonexistent_tool", {})))
            assert "Unknown tool" in result.root.content[0].text


class TestServerErrorHandling:
    def test_missing_gcp_project_id(self) -> None:
        with (
            pytest.raises(ValueError),
            patch("bigquery.client.bigquery.Client", MagicMock()),
        ):
            from server import create_server

            create_server("")


class TestCostLimitSemantics:
    """v2.12: budget exhaustion must surface as explicit cost_limit — never a silent []."""

    def _run_search(self, mock_client, args, web_results=None):
        with (
            patch("server.BigQueryClient") as mock_cls,
            patch("bigquery.client.bigquery.Client", MagicMock()),
            patch("server.web_search_patents", MagicMock(return_value=web_results or [])),
        ):
            mock_cls.return_value = mock_client
            from server import create_server

            server = create_server("test-project")
            fn = server.request_handlers[CallToolRequest]
            return asyncio.run(fn(_make_call_req("search_patents", args)))

    def test_search_cost_blocked_no_fallback_returns_cost_limit(self) -> None:
        from bigquery.client import BigQueryCostError

        mock_client = AsyncMock()
        mock_client.search_patents.side_effect = BigQueryCostError(
            "Session budget exhausted: 513.3 GB used"
        )
        result = self._run_search(mock_client, {"query": "neural network", "country": "US"})
        text = result.root.content[0].text
        assert "cost_limit" in text
        assert "Session budget exhausted" in text

    def test_search_cost_blocked_empty_fallback_returns_cost_limit(self) -> None:
        from bigquery.client import BigQueryCostError

        mock_client = AsyncMock()
        mock_client.search_patents.side_effect = BigQueryCostError(
            "Session budget exhausted: 513.3 GB used"
        )
        result = self._run_search(
            mock_client,
            {"query": "chip", "cpc": "H01L", "country": "CN"},
            web_results=[],
        )
        text = result.root.content[0].text
        assert "cost_limit" in text

    def test_search_cost_blocked_fallback_success_returns_results(self) -> None:
        from bigquery.client import BigQueryCostError

        mock_client = AsyncMock()
        mock_client.search_patents.side_effect = BigQueryCostError("budget gone")
        web_hit = MagicMock()
        web_hit.model_dump.return_value = {"publication_number": "CN-118888888-A"}
        result = self._run_search(
            mock_client,
            {"query": "chip", "cpc": "H01L", "country": "CN"},
            web_results=[web_hit],
        )
        text = result.root.content[0].text
        assert "cost_limit" not in text
        assert "CN-118888888-A" in text

    def test_batch_get_patents_cost_blocked_item_tagged_cost_limit(self) -> None:
        from bigquery.client import BigQueryCostError

        mock_client = AsyncMock()
        mock_client.get_patent.side_effect = BigQueryCostError("Session budget exhausted")
        with (
            patch("server.BigQueryClient") as mock_cls,
            patch("bigquery.client.bigquery.Client", MagicMock()),
            patch("server.web_fetch_patent", MagicMock(side_effect=Exception("web down"))),
        ):
            mock_cls.return_value = mock_client
            from server import create_server

            server = create_server("test-project")
            fn = server.request_handlers[CallToolRequest]
            result = asyncio.run(
                fn(_make_call_req("batch_get_patents", {"publication_numbers": ["US-1-A"]}))
            )
        text = result.root.content[0].text
        assert "cost_limit" in text
