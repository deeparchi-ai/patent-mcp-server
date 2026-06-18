# Patent MCP Server

> 🚀 **Clone. Install. Done.** Give your AI agent the ability to read global patents — no API key, no cloud, no external service.

[![Tests](https://img.shields.io/badge/tests-32%2F32-brightgreen)](https://github.com/deeparchi-ai/patent-mcp-server/actions)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-purple)](https://modelcontextprotocol.io/)

An MCP (Model Context Protocol) server that gives AI agents access to global patent data — **1.4 billion patent records**, Chinese full-text included. Runs locally on your machine. No external API, no subscription.

---

## Why Self-Deployed

- **It's just Python.** Install it, your agent uses it. No server to maintain, no credential to share.
- **No API key for 80% of use cases.** Patent details and claims come straight from Google Patents public pages.
- **Your data stays local.** Nothing leaves your machine except the same HTTP requests a browser would make.
- **BigQuery search is optional.** Only turn it on if you need full-text search across 1.4B records.

---

## 30-Second Install

```bash
git clone https://github.com/deeparchi-ai/patent-mcp-server.git
cd patent-mcp-server
pip install -e .
```

---

## Quick Start

Pick your agent platform and add this to its MCP config:

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

### Cursor / Windsurf / Cline

Same config as Claude Desktop above.

### Hermes Agent

```yaml
mcp_servers:
  patent-mcp:
    command: "python"
    args: ["-m", "src.server"]
    workdir: "/path/to/patent-mcp-server"
```

### Any MCP Client (via mcp.json)

```bash
mcp-get install deeparchi-ai/patent-mcp-server
```

---

Now ask your agent:

> *"Get patent US-7650331-B1 and summarize the claims."*

---

## What's Included

| Tool | What It Does | Needs Setup? |
|------|-------------|:---:|
| `get_patent` | Full patent details: classifications, citations (X/Y/A/D), inventors, assignees, family | No |
| `get_patent_claims` | US patent claims text — the legal scope of protection | No |
| `search_patents` | Search 1.4B patents by keyword, country, CPC, date range | Optional GCP |

The first two cover 80% of use cases. Zero cost. Zero setup.

---

## Optional: Enable BigQuery Search

If you need `search_patents`, add a GCP project:

1. Create a [GCP project](https://console.cloud.google.com/) with BigQuery enabled
2. Create a service account, download JSON key
3. Set env vars:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"
   export GCP_PROJECT_ID="your-project-id"
   ```
4. Copy the wrapper template and fill in your paths:
   ```bash
   cp run.sh.example run.sh
   # Edit run.sh → set your GCP paths
   ```

BigQuery free tier: 1 TB/month — individual use is essentially free.

---

## Advanced: Team Server (HTTP/SSE)

Need multiple people to share one patent-mcp instance? Start it as an HTTP server:

```bash
cp run-http.sh.example run-http.sh
# Edit → set GCP creds (skip if only using web tools)
PORT=8090 ./run-http.sh
```

Team members connect with:
```yaml
mcp_servers:
  patent-mcp:
    url: "http://<server-ip>:8090/sse"
```

A [systemd service template](run-http.sh.example) is included for production deployment.

---

## Tools Reference

### `get_patent`

```
get_patent(publication_number="US-7650331-B1")
```

Returns: classifications, citations (X/Y/A/D prior art markers), family ID, dates, inventors, assignees. Cites prior art markers so your agent can assess novelty at a glance.

### `get_patent_claims`

```
get_patent_claims(publication_number="US-7650331-B1")
```

Returns: full claims text. (US patents only; non-US return empty.)

### `search_patents`

```
search_patents(query="transformer attention", country="CN", after="2023-01-01", limit=5)
```

CN results include Chinese titles and abstracts. At least one of `country`, `cpc`, or `after` is required.

---

## How It Works

```
┌──────────────┐     ┌─────────────────────────────┐
│  AI Agent    │────▶│  patent-mcp-server          │
│  (Claude,    │     │  (runs on YOUR machine)     │
│   Cursor,    │     │                             │
│   Hermes)    │     │  ┌──────────┐ ┌───────────┐ │
│              │     │  │ Web      │ │ BigQuery  │ │
│              │     │  │ Scraper  │ │ Client    │ │
│              │     │  │ (free)   │ │ (optional)│ │
│              │     │  └────┬─────┘ └─────┬─────┘ │
│              │     │       │             │       │
│              │     │  Google Patents   BigQuery  │
│              │     │  Public Pages     1.4B rows │
└──────────────┘     └─────────────────────────────┘
```

- **Web scraping for details** — fast (~1.5s), free, no credentials
- **BigQuery for search** — 1.4B records, CN full-text, optional
- **Smart fallback** — `get_patent` tries web first, auto-falls to BigQuery if you have it

---

## Development

```bash
pip install -e ".[dev]"

pytest tests/ -v          # 32 tests, ~1.5s
ruff check src/ tests/    # lint
mypy src/                 # type check
```

---

## License

MIT — see [LICENSE](LICENSE).

---

## Author

[DeepArchi OPC](https://github.com/deeparchi-ai) — AI agent infrastructure for enterprise architecture.
