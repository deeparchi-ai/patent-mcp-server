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
        with patch("server.BigQueryClient") as mock_cls:
            with patch("bigquery.client.bigquery.Client", MagicMock()):
                mock_cls.return_value = AsyncMock()
                from server import create_server
                server = create_server("test-project")
                assert ListToolsRequest in server.request_handlers

    def test_registers_call_tool_handler(self) -> None:
        with patch("server.BigQueryClient") as mock_cls:
            with patch("bigquery.client.bigquery.Client", MagicMock()):
                mock_cls.return_value = AsyncMock()
                from server import create_server
                server = create_server("test-project")
                assert CallToolRequest in server.request_handlers

    def test_list_tools_returns_three_names(self) -> None:
        with patch("server.BigQueryClient") as mock_cls:
            with patch("bigquery.client.bigquery.Client", MagicMock()):
                mock_cls.return_value = AsyncMock()
                from server import create_server
                server = create_server("test-project")
                fn = server.request_handlers[ListToolsRequest]
                result = asyncio.new_event_loop().run_until_complete(
                    fn(ListToolsRequest(method="tools/list", params=None))
                )
                names = [t.name for t in result.root.tools]
                assert "search_patents" in names
                assert "get_patent" in names
                assert "get_patent_claims" in names


class TestSearchPatentsHandler:
    def test_rejects_missing_filters(self) -> None:
        with patch("server.BigQueryClient") as mock_cls:
            with patch("bigquery.client.bigquery.Client", MagicMock()):
                mock_client = AsyncMock()
                mock_client.search_patents.side_effect = ValueError(
                    "at least one filter"
                )
                mock_cls.return_value = mock_client
                from server import create_server
                server = create_server("test-project")

                fn = server.request_handlers[CallToolRequest]
                result = asyncio.new_event_loop().run_until_complete(
                    fn(_make_call_req("search_patents", {"query": "AI"}))
                )
                assert "invalid_input" in result.root.content[0].text

    def test_accepts_country_filter(self) -> None:
        with patch("server.BigQueryClient") as mock_cls:
            with patch("bigquery.client.bigquery.Client", MagicMock()):
                mock_client = AsyncMock()
                mock_client.search_patents.return_value = []
                mock_cls.return_value = mock_client
                from server import create_server
                server = create_server("test-project")

                fn = server.request_handlers[CallToolRequest]
                result = asyncio.new_event_loop().run_until_complete(
                    fn(_make_call_req("search_patents", {
                        "query": "neural network",
                        "country": "CN",
                    }))
                )
                assert result.root.content[0].type == "text"


class TestGetPatentHandler:
    def test_handles_not_found(self) -> None:
        with patch("server.BigQueryClient") as mock_cls:
            with patch("bigquery.client.bigquery.Client", MagicMock()):
                mock_client = AsyncMock()
                from bigquery.client import PatentNotFoundError
                mock_client.get_patent.side_effect = PatentNotFoundError(
                    "CN-0000000-A"
                )
                mock_cls.return_value = mock_client
                from server import create_server
                server = create_server("test-project")

                fn = server.request_handlers[CallToolRequest]
                result = asyncio.new_event_loop().run_until_complete(
                    fn(_make_call_req("get_patent", {"publication_number": "CN-0000000-A"}))
                )
                assert "not_found" in result.root.content[0].text

    def test_unknown_tool(self) -> None:
        with patch("server.BigQueryClient") as mock_cls:
            with patch("bigquery.client.bigquery.Client", MagicMock()):
                mock_cls.return_value = AsyncMock()
                from server import create_server
                server = create_server("test-project")

                fn = server.request_handlers[CallToolRequest]
                result = asyncio.new_event_loop().run_until_complete(
                    fn(_make_call_req("nonexistent_tool", {}))
                )
                assert "Unknown tool" in result.root.content[0].text


class TestServerErrorHandling:
    def test_missing_gcp_project_id(self) -> None:
        with pytest.raises(ValueError):
            with patch("bigquery.client.bigquery.Client", MagicMock()):
                from server import create_server
                create_server("")
