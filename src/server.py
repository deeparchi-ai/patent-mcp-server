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

from bigquery.client import (
    BigQueryClient,
    BigQueryCostError,
    BigQueryError,
    PatentNotFoundError,
)
from web.google_patents import bidirectional_citation_graph as web_bidirectional_graph
from web.google_patents import competitor_citation_matrix as web_competitor_matrix
from web.google_patents import (
    fetch_cited_by_with_details as web_fetch_cited_by_with_details,
)
from web.google_patents import fetch_claims as web_fetch_claims
from web.google_patents import fetch_patent as web_fetch_patent
from web.google_patents import web_search_patents
from web.legal_status import get_legal_status as web_get_legal_status

# ── Agent Card — machine-readable MCP server description ──────────────────────
# Used by AI agents to auto-discover, evaluate, and configure this server.
# Served at /.well-known/agent-card.json
_AGENT_CARD_JSON = json.dumps(
    {
        "name": "Patent MCP Server",
        "description": (
            "Search and analyze 140M+ global patents via Google Patents BigQuery. "
            "For patent landscape analysis, competitor portfolio tracking, prior art "
            "search, and IP due diligence. 10 tools: search, detail lookup, claims, "
            "legal status, family, citations, competitor matrix, citation graph."
        ),
        "use_cases": [
            "Competitor patent portfolio analysis and tracking",
            "Technology landscape mapping and trend analysis",
            "Prior art search for patent applications",
            "Patent family and citation network analysis",
            "IP due diligence for M&A, investment, or licensing",
        ],
        # ── Agent auto-discovery signals ──────────────────────────────────
        # Triggers: keywords and intents an AI agent uses to match this server
        # to user tasks without requiring a human to configure it.
        "triggers": {
            "keywords": [
                "patent",
                "专利",
                "IP",
                "intellectual property",
                "知识产权",
                "prior art",
                "现有技术",
                "FTO",
                "freedom to operate",
                "patent landscape",
                "专利布局",
                "patent portfolio",
                "patent citation",
                "专利引用",
                "patent family",
                "同族专利",
                "legal status",
                "法律状态",
                "claims",
                "权利要求",
                "competitor patent",
                "竞争专利",
                "patent analysis",
            ],
            "intents": [
                "patent_search",
                "patent_analysis",
                "competitor_intelligence",
                "ip_due_diligence",
                "technology_landscape",
            ],
            "user_roles": [
                "patent_attorney",
                "ip_manager",
                "legal_counsel",
                "r_and_d_engineer",
                "investment_analyst",
                "m_and_a_advisor",
            ],
        },
        # Capabilities: structured snapshot of what this server can do.
        # Agents use this to decide whether it fits the current task.
        "capabilities": {
            "search": {
                "scope": "global",
                "coverage": "140M+ patents",
                "jurisdictions": ["CN", "US", "EP", "JP", "KR", "WO"],
                "modes": ["keyword", "assignee", "CPC", "date_range"],
            },
            "detail": [
                "title",
                "abstract",
                "claims",
                "classifications",
                "citations",
                "inventors",
                "assignees",
                "family_id",
                "filing_date",
                "grant_date",
                "priority_date",
            ],
            "analysis": [
                "citation_graph",
                "competitor_matrix",
                "family_analysis",
                "legal_status_tracking",
            ],
        },
        # Performance: helps an agent set user expectations before calling.
        "performance": {
            "typical_latency_ms": 2000,
            "worst_latency_ms": 15000,
            "concurrent_limit": 10,
            "monthly_quota": "1 TB BigQuery sandbox",
        },
        # Interop: MCP protocol compatibility signals.
        "interop": {
            "mcp_version": "2024-11-05",
            "transport": ["sse"],
            "requires": [],
            "conflicts_with": [],
        },
        # ── Standard fields (existing) ────────────────────────────────────
        "mcp_config": {
            "transport": "sse",
            "url": "https://patent-mcp-494814528402.us-central1.run.app/sse/",
        },
        "auth": "none",
        "pricing": "free",
        "data_sources": [
            "Google Patents Public Datasets (BigQuery) — full-text search",
            "Google Patents web pages — real-time legal status",
        ],
        "maintainer": {
            "name": "DeepArchi",
            "github": "https://github.com/deeparchi-ai/patent-mcp-server",
        },
        "tools": 10,
        "limitations": [
            "BigQuery sandbox: 1 TB/month free, then throttled",
            "Hosted in us-central1, ~200ms latency from Asia-Pacific",
            "Google Patents web scraping subject to rate limits (retry with backoff)",
            "No authentication required — public data only",
        ],
        "protocol": "MCP (Model Context Protocol) over SSE",
        "version": "1.9.0",
    }
)

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
            Tool(
                name="get_legal_status",
                description=(
                    "Get legal status of a patent from Google Patents page."
                    " Extracts status (granted/application/utility_model),"
                    " kind_code (A/B/U), filing_date, grant_date,"
                    " priority_date, assignee, and legal events timeline."
                    " Works for CN, US, EP, and most other jurisdictions."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "publication_number": {
                            "type": "string",
                            "description": (
                                "Patent publication number, e.g. 'US-7650331-B1', 'CN-110286864-A'"
                            ),
                        },
                    },
                    "required": ["publication_number"],
                },
            ),
            Tool(
                name="get_patent_family",
                description=(
                    "Get patent family members for a patent. Finds family_id"
                    " from BigQuery, then returns ALL patents sharing that"
                    " family_id (same invention filed in different countries)."
                    " Returns family_id, member_count, and members list with"
                    " publication_number, country_code, kind_code, filing_date,"
                    " grant_date, title for each."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "publication_number": {
                            "type": "string",
                            "description": (
                                "Patent publication number, e.g. 'US-7650331-B1', 'CN-110286864-A'"
                            ),
                        },
                    },
                    "required": ["publication_number"],
                },
            ),
            Tool(
                name="batch_get_patents",
                description=(
                    "Get full details for multiple patents in a single call."
                    " Much faster than calling get_patent N times separately."
                    " Returns list of PatentDetail objects."
                    " Max 20 patents per call."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "publication_numbers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Patent publication numbers (e.g. CN110286864A)",
                        },
                    },
                    "required": ["publication_numbers"],
                },
            ),
            Tool(
                name="batch_get_cited_by",
                description=(
                    "Get cited-by counts and lists for multiple patents in a"
                    " single call. Returns list of {publication_number,"
                    " cited_by_count, cited_by_patents, cited_by_url}."
                    " Max 10 patents per call."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "publication_numbers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Patent publication numbers (e.g. CN110286864A)",
                        },
                    },
                    "required": ["publication_numbers"],
                },
            ),
            Tool(
                name="get_cited_by",
                description=(
                    "Get backward citations (who cites this patent)."
                    " Returns cited_by_count (int) and cited_by_patents"
                    " (list of {publication_number, title, assignee})."
                    " Extracted from Google Patents HTML."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "publication_number": {
                            "type": "string",
                            "description": (
                                "Patent publication number, e.g. 'US-7650331-B1', 'CN-110286864-A'"
                            ),
                        },
                    },
                    "required": ["publication_number"],
                },
            ),
            Tool(
                name="competitor_citation_matrix",
                description=(
                    "Check if a set of target patents are cited by competitors."
                    " Searches each patent's cited-by list and matches citing"
                    " assignees against competitor keywords (case-insensitive"
                    " substring). Returns matrix: {patent: [{citing_patent,"
                    " title, assignee, matched_keyword}]} and summary counts."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "publication_numbers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Patent numbers to check (e.g. CN110286864A)",
                        },
                        "competitor_keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Competitor assignee substrings, e.g. 百度, Baidu, 华为",
                        },
                    },
                    "required": ["publication_numbers", "competitor_keywords"],
                },
            ),
            Tool(
                name="bidirectional_citation_graph",
                description=(
                    "Build full bidirectional citation graph for a company's"
                    " core patents. Searches for company's patents on Google"
                    " Patents, then fetches forward and backward citations for"
                    " each. If competitor_keywords provided, also runs"
                    " competitor citation matrix. Returns: patents list,"
                    " forward_graph, backward_graph, competitor_matrix."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "assignee_name": {
                            "type": "string",
                            "description": "Company name for patent search, e.g. 'Wuhan Carbit'",
                        },
                        "competitor_keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional competitor substrings, e.g. 百度, 华为",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max patents to analyze (default 10)",
                            "default": 10,
                        },
                    },
                    "required": ["assignee_name"],
                },
            ),
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            if name == "search_patents":
                cost_blocked: BigQueryCostError | None = None
                try:
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
                except BigQueryCostError as cost_err:
                    logger.info(
                        "BigQuery cost blocked: %s — falling to web search",
                        cost_err,
                    )
                    result = []
                    cost_blocked = cost_err

                # Web search fallback: if BigQuery returns 0 results (or is cost-blocked)
                # and CPC is set, try SearXNG web search + Google Patents enrichment.
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
                            logger.info("Web fallback returned %d results", len(result))

                # v2.12: budget exhaustion must be explicit — a silent [] reads
                # as "no results" to the calling agent, which is misleading.
                if not result and cost_blocked is not None:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps({"error": "cost_limit", "message": str(cost_blocked)}),
                        )
                    ]

                data = [r.model_dump(mode="json") for r in result]
                return [
                    TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))
                ]

            elif name == "batch_get_patents":
                pubs = list(arguments["publication_numbers"])[:20]
                results = []
                for pub in pubs:
                    try:
                        pub_clean = str(pub)
                        # Try web first
                        try:
                            r = await asyncio.to_thread(web_fetch_patent, pub_clean)
                            results.append(r.model_dump(mode="json"))
                        except Exception:
                            try:
                                r = await client.get_patent(pub_clean)
                                results.append(r.model_dump(mode="json"))
                            except PatentNotFoundError:
                                results.append(
                                    {
                                        "publication_number": pub_clean,
                                        "error": "not_found",
                                    }
                                )
                    except BigQueryCostError as e:
                        results.append(
                            {
                                "publication_number": str(pub),
                                "error": "cost_limit",
                                "message": str(e),
                            }
                        )
                    except Exception as e:
                        results.append({"publication_number": str(pub), "error": str(e)})
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(results, ensure_ascii=False, indent=2),
                    )
                ]

            elif name == "batch_get_cited_by":
                pubs = list(arguments["publication_numbers"])[:10]
                results = []
                for pub in pubs:
                    try:
                        r = await asyncio.to_thread(web_fetch_cited_by_with_details, str(pub))
                        results.append(r)
                    except Exception as e:
                        results.append({"publication_number": str(pub), "error": str(e)})
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(results, ensure_ascii=False, indent=2),
                    )
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
                                    {
                                        "error": "not_found",
                                        "message": f"Patent not found: {pub}",
                                    }
                                ),
                            )
                        ]

                data = result.model_dump(mode="json")
                data["_source"] = source
                return [
                    TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))
                ]

            elif name == "get_legal_status":
                pub = str(arguments["publication_number"])
                result = await asyncio.to_thread(web_get_legal_status, pub)
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(result, ensure_ascii=False, indent=2),
                    )
                ]

            elif name == "get_patent_family":
                pub = str(arguments["publication_number"])
                result = await client.get_family(pub)
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(result, ensure_ascii=False, indent=2),
                    )
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
                                {
                                    "publication_number": pub,
                                    "claims": [],
                                    "note": note.strip(),
                                }
                            ),
                        )
                    ]
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "publication_number": pub,
                                "claims": claims,
                                "_source": source,
                            }
                        ),
                    )
                ]

            elif name == "get_cited_by":
                pub = str(arguments["publication_number"])
                result = await asyncio.to_thread(web_fetch_cited_by_with_details, pub)
                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

            elif name == "competitor_citation_matrix":
                pubs = list(arguments["publication_numbers"])
                keywords = list(arguments["competitor_keywords"])
                result = await asyncio.to_thread(web_competitor_matrix, pubs, keywords)
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(result, ensure_ascii=False, indent=2),
                    )
                ]

            elif name == "bidirectional_citation_graph":
                assignee = str(arguments["assignee_name"])
                keywords_comp = list(arguments.get("competitor_keywords", [])) or None
                limit = min(int(arguments.get("limit", 10)), 20)
                result = await asyncio.to_thread(
                    web_bidirectional_graph, assignee, keywords_comp, limit
                )
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(result, ensure_ascii=False, indent=2),
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

    async def handle_agent_card(request: Any) -> Response:
        return Response(
            _AGENT_CARD_JSON,
            media_type="application/json",
        )

    async def handle_post_sse(scope: Any, receive: Any, send: Any) -> None:
        await sse.handle_post_message(scope, receive, send)

    app = Starlette(
        debug=False,
        routes=[
            Mount("/sse/messages", app=handle_post_sse),
            Mount("/sse", app=sse_app),
            Route("/health", endpoint=handle_health),
            Route("/.well-known/agent-card.json", endpoint=handle_agent_card),
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
