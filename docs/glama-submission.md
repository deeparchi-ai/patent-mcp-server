# Glama MCP Server Submission — deeparchi-patent-mcp

## Server Details

**Name:** deeparchi-patent-mcp

**Description:** 
Search 1.4B global patents via BigQuery + Google Patents. 3 MCP tools: search_patents (CPC/assignee/country/date filters), get_patent (full details + citations), get_patent_claims (legal scope). MIT. Hybrid architecture: $0 web scraping for single lookups, BigQuery for bulk search.

**Repository:** https://github.com/deeparchi-ai/patent-mcp-server

**Install command:** `pip install deeparchi-patent-mcp`

**Run command:** `deeparchi-patent-mcp`

**Transports:** stdio, http-sse

**License:** MIT

**Categories:** Search, Research, Legal

## Tools

| Tool | Description |
|------|-------------|
| `search_patents` | Search 1.4B patents by CPC, assignee, country, date range |
| `get_patent` | Full patent details: classifications, citations, inventors, assignees |
| `get_patent_claims` | Patent claims text (legal scope) for US, CN, and most countries |
