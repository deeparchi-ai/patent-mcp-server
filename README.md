# Patent MCP Server

> 🚀 **Zero API key required.** Your AI agent can read any global patent right now.

[![Tests](https://img.shields.io/badge/tests-32%2F32-brightgreen)](https://github.com/deeparchi-ai/patent-mcp-server/actions)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-purple)](https://modelcontextprotocol.io/)

An MCP (Model Context Protocol) server that gives AI agents access to global patent data — **1.4 billion patent records**, Chinese full-text included.

---

## Why

Every AI agent can search the web. None can read patents. This fixes that.

- **PM doing competitive analysis** → agent searches competitors' patent portfolios
- **Engineer evaluating prior art** → agent reads patent claims and citations
- **Lawyer drafting opinions** → agent pulls full patent details with citation graphs

No more copy-pasting patent numbers into a browser. Your agent does it.

---

## Zero-Config Mode (No API Key)

Two of the three tools work with **zero setup** — they scrape Google Patents public pages:

| Tool | Description | Setup |
|------|-------------|-------|
| `get_patent` | Full patent details: classifications, citations, dates, inventors, assignees | **None** |
| `get_patent_claims` | US patent claims text (legal scope of protection) | **None** |

These cover 80% of use cases and cost nothing.

---

## Full Mode (Optional BigQuery)

Add `GCP_PROJECT_ID` + service account credentials to unlock the third tool:

| Tool | Description | Setup |
|------|-------------|-------|
| `search_patents` | Search 1.4B patents by keyword, country, CPC code, date range | GCP required |

Includes CN patents with Chinese titles and abstracts.

---

## Quick Start

### Claude Desktop

```json
{
  "mcpServers": {
    "patent-mcp": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/patent-mcp-server"
    }
  }
}
```

That's it. Ask Claude: *"Get patent US-7650331-B1 and summarize the claims."*

### Cursor / Windsurf

```json
{
  "mcpServers": {
    "patent-mcp": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/patent-mcp-server"
    }
  }
}
```

### Hermes Agent

```yaml
mcp_servers:
  patent-mcp:
    command: "python"
    args: ["-m", "src.server"]
    workdir: "/path/to/patent-mcp-server"
```

### Remote (HTTP/SSE)

Start the server:
```bash
cp run-http.sh.example run-http.sh   # Fill in GCP creds if using search
PORT=8090 ./run-http.sh
```

Connect any MCP client:
```yaml
mcp_servers:
  patent-mcp:
    url: "http://<ip>:8090/sse"
```

---

## Installation

```bash
git clone https://github.com/deeparchi-ai/patent-mcp-server.git
cd patent-mcp-server
pip install -e .
```

That's all you need for zero-config mode.

### Optional: BigQuery Search

1. Create a [GCP project](https://console.cloud.google.com/) with BigQuery enabled
2. Create a service account and download JSON key
3. Set environment variables:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"
   export GCP_PROJECT_ID="your-project-id"
   ```
4. Copy and edit the wrapper:
   ```bash
   cp run.sh.example run.sh   # stdio mode
   cp run-http.sh.example run-http.sh  # HTTP mode
   # Edit both to set your GCP paths
   ```

BigQuery free tier gives 1 TB/month — plenty for individual use.

---

## Tools Reference

### `search_patents`

Search patents by keyword, country, CPC code, or date range.

```
search_patents(query="transformer attention", country="CN", after="2023-01-01", limit=5)
```

### `get_patent`

Get full patent details by publication number (DOCDB format).

```
get_patent(publication_number="US-7650331-B1")
```

Returns: classifications, citations (with X/Y/A/D prior art markers), family ID, dates, inventors, assignees.

### `get_patent_claims`

Get US patent claims text.

```
get_patent_claims(publication_number="US-7650331-B1")
```

Note: claims are only available for US patents.

---

## Architecture

```
┌──────────────┐     ┌─────────────────────────────┐
│  AI Agent    │────▶│  patent-mcp-server          │
│  (Claude,    │     │                             │
│   Cursor,    │     │  ┌──────────┐ ┌───────────┐ │
│   Hermes)    │     │  │ Web      │ │ BigQuery  │ │
│              │     │  │ Scraper  │ │ Client    │ │
│              │     │  │ (free)   │ │ (optional)│ │
│              │     │  └────┬─────┘ └─────┬─────┘ │
│              │     │       │             │       │
│              │     │  Google Patents   BigQuery  │
│              │     │  Public Pages     1.4B rows │
└──────────────┘     └─────────────────────────────┘
```

- **Hybrid data sources**: web scraping for details (free, fast), BigQuery for search (large-scale)
- **Dual transport**: stdio (local) + HTTP/SSE (remote/team)
- **Smart fallback**: `get_patent` tries web first, falls back to BigQuery automatically

---

## Development

```bash
# Install dev deps
pip install -e ".[dev]"

# Run tests
pytest tests/ -v           # 32 tests, ~1.5s

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

---

## License

MIT — see [LICENSE](LICENSE).

---

## Author

[DeepArchi OPC](https://github.com/deeparchi-ai) — AI agent infrastructure for enterprise architecture.
