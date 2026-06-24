"""Patent MCP Server — AI Agent 入口。

Registers: search_patents, get_patent, get_patent_claims.
Transport: stdio (default) or HTTP/SSE (--transport http --port 8090).
"""

from __future__ import annotations

import argparse
import asyncio
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

from bigquery.client import BigQueryClient, BigQueryCostError, BigQueryError, PatentNotFoundError
from web.google_patents import fetch_claims as web_fetch_claims
from web.google_patents import fetch_patent as web_fetch_patent
from web.google_patents import web_search_patents

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
                        "assignee": {
                            "type": "string",
                            "description": (
                                "Optional assignee/organization name filter"
                                " (fuzzy match on harmonized names)."
                                " Use for company-level or city-level"
                                " analysis, e.g. 'HEFEI', 'BOE', 'HUAWEI'."
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
                    "Get patent claims text by publication number. "
                    "Claims define the legal scope of patent protection. "
                    "Supports US, CN, and most other countries via Google Patents."
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
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            if name == "search_patents":
                result = await client.search_patents(
                    query=arguments.get("query"),
                    assignee=arguments.get("assignee"),
                    country=arguments.get("country"),
                    cpc=arguments.get("cpc"),
                    after=arguments.get("after"),
                    before=arguments.get("before"),
                    status=arguments.get("status"),
                    limit=min(int(arguments.get("limit", 10)), 50),
                )

                # Web search fallback: if BigQuery returns 0 results and CPC is set,
                # try SearXNG web search + Google Patents enrichment.
                # This fills the gap for CN CPC queries where BigQuery's CPC
                # classification coverage is sparse (e.g., H01L25/065 + CN).
                if not result and arguments.get("cpc"):
                    country_val = str(arguments.get("country", ""))
                    if country_val == "CN" or not country_val:
                        logger.info(
                            "BigQuery returned 0 for cpc=%s country=%s — web fallback",
                            arguments["cpc"],
                            country_val,
                        )
                        web_results = await asyncio.to_thread(
                            web_search_patents,
                            cpc=str(arguments["cpc"]),
                            query=arguments.get("query"),
                            country=arguments.get("country"),
                            limit=min(int(arguments.get("limit", 10)), 50),
                        )
                        if web_results:
                            result = web_results
                            logger.info(
                                "Web fallback returned %d results", len(result)
                            )

                data = [r.model_dump(mode="json") for r in result]
                return [
                    TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))
                ]

            elif name == "get_patent":
                pub = str(arguments["publication_number"])
                # Try web first (free), fallback to BigQuery for CPC codes + full metadata
                try:
                    result = await asyncio.to_thread(web_fetch_patent, pub)
                    source = "web"
                except Exception as web_err:
                    logger.info(
                        "Web fetch failed for %s: %s — falling back to BigQuery",
                        pub,
                        web_err,
                    )
                    try:
                        result = await client.get_patent(pub)
                        source = "bigquery"
                    except PatentNotFoundError:
                        return [
                            TextContent(
                                type="text",
                                text=json.dumps(
                                    {"error": "not_found", "message": f"Patent not found: {pub}"}
                                ),
                            )
                        ]

                data = result.model_dump(mode="json")
                data["_source"] = source
                return [
                    TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))
                ]

            elif name == "get_patent_claims":
                pub = str(arguments["publication_number"])
                # Try web first (free, saves ~35 GB BigQuery join)
                try:
                    claims = await asyncio.to_thread(web_fetch_claims, pub)
                    source = "web"
                except Exception as web_err:
                    logger.info(
                        "Web claims fetch failed for %s: %s — falling back to BigQuery",
                        pub,
                        web_err,
                    )
                    claims = await client.get_patent_claims(pub)
                    source = "bigquery"

                if not claims:
                    note = " (Note: claims text not found for this patent)"
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
                        text=json.dumps(
                            {"publication_number": pub, "claims": claims, "_source": source}
                        ),
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
        except BigQueryCostError as e:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": "cost_limit", "message": str(e)}),
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


async def main_stdio() -> None:
    """Start MCP server on stdio transport (for Hermes native MCP client)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    if not GCP_PROJECT_ID:
        logger.error("GCP_PROJECT_ID environment variable is required")
        sys.exit(1)

    logger.info("Starting patent-mcp-server on stdio (project=%s)", GCP_PROJECT_ID)
    server = create_server(GCP_PROJECT_ID)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def main_http(port: int, host: str = "0.0.0.0") -> None:
    """Start MCP server on HTTP/SSE transport (for remote MCP clients)."""
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Mount, Route

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    if not GCP_PROJECT_ID:
        logger.error("GCP_PROJECT_ID environment variable is required")
        sys.exit(1)

    server = create_server(GCP_PROJECT_ID)
    sse = SseServerTransport("/messages/")

    async def sse_app(scope: Any, receive: Any, send: Any) -> None:
        async with sse.connect_sse(scope, receive, send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    async def handle_health(request: Any) -> Response:
        return Response(
            '{"status":"ok","server":"patent-mcp-server"}',
            media_type="application/json",
        )

    app = Starlette(
        debug=False,
        routes=[
            Mount("/sse", app=sse_app),
            Mount("/messages/", app=sse.handle_post_message),
            Route("/health", endpoint=handle_health),
        ],
    )

    import uvicorn

    logger.info(
        "Starting patent-mcp-server on HTTP/SSE (host=%s, port=%d, project=%s)",
        host,
        port,
        GCP_PROJECT_ID,
    )
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server_uv = uvicorn.Server(config)
    await server_uv.serve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Patent MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8090,
        help="HTTP port (default: 8090, only used with --transport http)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="HTTP bind host (default: 0.0.0.0)",
    )
    return parser.parse_args()


async def main() -> None:
    """Entry point: dispatch to stdio or HTTP transport based on CLI args."""
    args = parse_args()

    if args.transport == "http":
        await main_http(port=args.port, host=args.host)
    else:
        await main_stdio()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
