"""Patent MCP Server — AI Agent 入口。

Registers: search_patents, get_patent, get_patent_claims.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    ListToolsRequest,
    TextContent,
    Tool,
)

from bigquery.client import BigQueryClient, BigQueryError, PatentNotFoundError

logger = logging.getLogger("patent-mcp-server")

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")


def create_server(project_id: str) -> Server:
    """Create and configure the MCP Server with all tools registered."""
    server = Server("patent-mcp-server")
    client = BigQueryClient(project_id=project_id)

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_tools(request: ListToolsRequest) -> list[Tool]:
        return [
            Tool(
                name="search_patents",
                description=(
                    "Search global patents by keyword, country, CPC classification, or date range. "
                    "At least one of country, cpc, or after must be provided to control query cost."
                    " Returns patent summaries with titles, abstracts, inventors, assignees,"
                    " and CPC codes. CN patents include Chinese titles and abstracts."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Optional keyword/technology area/inventor name to search"
                            ),
                        },
                        "country": {
                            "type": "string",
                            "description": "Country code filter, e.g. 'CN', 'US', 'EP'",
                        },
                        "cpc": {
                            "type": "string",
                            "description": "CPC classification code prefix, e.g. 'G06F40', 'H01L'",
                        },
                        "after": {
                            "type": "string",
                            "description": "Earliest filing date, format YYYY-MM-DD",
                        },
                        "before": {
                            "type": "string",
                            "description": "Latest filing date, format YYYY-MM-DD",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["grant", "application"],
                            "description": "Patent status filter",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum results (default 10, max 50)",
                            "default": 10,
                        },
                    },
                },
            ),
            Tool(
                name="get_patent",
                description=(
                    "Get full patent details by publication number (DOCDB format). "
                    "Returns classifications, citations,"
                    " family ID, dates, inventors, assignees."
                    " Citations include X/Y/A/D markers for prior art analysis."
                    " X=relevant if taken alone, Y=relevant if combined."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "publication_number": {
                            "type": "string",
                            "description": (
                                "Patent publication number, e.g. 'US-7650331-B1', 'CN-103257828-A'"
                            ),
                        },
                    },
                    "required": ["publication_number"],
                },
            ),
            Tool(
                name="get_patent_claims",
                description=(
                    "Get US patent claims text by publication number. "
                    "Claims define the legal scope of patent protection. "
                    "Note: Claims are only available for US patents. CN patents will return empty."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "publication_number": {
                            "type": "string",
                            "description": "US patent publication number, e.g. 'US-7650331-B1'",
                        },
                    },
                    "required": ["publication_number"],
                },
            ),
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            if name == "search_patents":
                result = await client.search_patents(
                    query=arguments.get("query"),
                    country=arguments.get("country"),
                    cpc=arguments.get("cpc"),
                    after=arguments.get("after"),
                    before=arguments.get("before"),
                    status=arguments.get("status"),
                    limit=min(int(arguments.get("limit", 10)), 50),
                )
                data = [r.model_dump(mode="json") for r in result]
                return [
                    TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))
                ]

            elif name == "get_patent":
                pub = str(arguments["publication_number"])
                result = await client.get_patent(pub)
                return [
                    TextContent(
                        type="text",
                        text=result.model_dump_json(indent=2),
                    )
                ]

            elif name == "get_patent_claims":
                pub = str(arguments["publication_number"])
                claims = await client.get_patent_claims(pub)
                if not claims:
                    note = " (Note: claims data may only be available for US patents)"
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {"publication_number": pub, "claims": [], "note": note.strip()}
                            ),
                        )
                    ]
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"publication_number": pub, "claims": claims}),
                    )
                ]

            else:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"error": f"Unknown tool: {name}"}),
                    )
                ]

        except PatentNotFoundError as e:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": "not_found", "message": str(e)}),
                )
            ]
        except BigQueryError as e:
            logger.error("BigQuery error: %s", e)
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": "bigquery_error", "message": str(e)}),
                )
            ]
        except ValueError as e:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": "invalid_input", "message": str(e)}),
                )
            ]

    return server


async def main() -> None:
    """Entry point: start MCP server on stdio transport."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    if not GCP_PROJECT_ID:
        logger.error("GCP_PROJECT_ID environment variable is required")
        sys.exit(1)

    logger.info("Starting patent-mcp-server (project=%s)", GCP_PROJECT_ID)
    server = create_server(GCP_PROJECT_ID)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
