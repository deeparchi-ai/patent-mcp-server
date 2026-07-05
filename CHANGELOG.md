# Changelog

## v1.9.0 (2026-07-05) — Cost Gate Hardening (deploy v2.12)

Three-layer cost gate closed:

- **cost_limit explicit surfacing** — budget exhaustion returns `{"error": "cost_limit"}` instead of a silent `[]`; batch items tagged individually; `get_family` step-1 now logs `[COST]`.
- **`maximum_bytes_billed` hard cap** — every real execution capped at 500 GB (env `PATENT_MCP_MAX_BYTES_BILLED_GB`); BigQuery aborts over-limit queries **without billing**. All four tool paths converge on `BigQueryClient._execute()`.
- **Engine error mapping** — `bytesBilledLimitExceeded` / `quotaExceeded` (project daily custom quota) raise `BigQueryCostError` → MCP `cost_limit`.
- Project-level quota: 5 TiB/day custom quota on `leafy-summer-499803-k6` (GCP console, no code).

---

## v1.7.0 (2026-06-24) — CN Web Search Fallback

**Major feature:** CN patent web search fallback. BigQuery CPC coverage for Chinese patents is sparse in some CPC classes. `search_patents` now falls back to web search when BigQuery returns fewer results than expected.

### Architecture

Three-layer CN patent discovery:
1. **BigQuery** — primary (fast, cheap, structured)
2. **Firecrawl** — web fallback (2 credits/query, reliable for CN)
3. **Google Patents** — enrichment (related patents, claims)

### Changes

- **Firecrawl web search** — primary CN fallback backend. Replaces SearXNG after all CN-relevant engines were CAPTCHA-blocked.
- **Related-patent crawling** — after discovering a patent via web search, crawls Google Patents "related" section for additional patents.
- **Dual-format patent number parsing** — handles both `CN107452705A` and `CN 107452705 A` formats.
- **DOCDB format handling** — recognized and normalized during related-patent discovery.
- **Proxy support** — Google Patents enrichment now routes through configured proxy.
- **Multi-query + pagination** — broader CPC coverage via multiple search formulations.

### Files changed

| File | Δ |
|------|---|
| `src/web/google_patents.py` | +383 lines (web search, related crawling, Firecrawl) |
| `src/server.py` | +54 lines (web fallback integration) |
| `docs/glama-submission.md` | New (Glama registry submission draft) |

### Known limitations

- SearXNG CN engines (Baidu, Google, DuckDuckGo, Startpage) all CAPTCHA-blocked as of 2026-06-24. Only Bing works, and returns junk for CN queries.
- Firecrawl web fallback consumes credits (2/search). BigQuery remains the preferred path.
- Web fallback returns fewer structured fields than BigQuery (no CPC codes, fewer citations).

---

## v1.6.0 (2026-06-21) — Partition Pruning & Cost Control

- Partition pruning as default query strategy (reduces BigQuery bytes scanned)
- Dry-run budget guard before real queries
- `assignee` filter parameter (city/company-level patent analysis)
- CN keyword search now queries both EN+ZH abstracts (was EN-only)

## v1.5.2 (2026-06-21)

- `search_patents` returns `cpc_codes` in results
- CN patent regex fix (RE2-compatible lookbehind removal)

## v1.5.1 (2026-06-20)

- PyPI publish with corrected package metadata

## v1.5.0 (2026-06-18)

- Product strategy: Five Deadly Sins pressure test, CPC correction table, mindshare metrics
- Devil's Advocate expanded 7→9

## v1.4.1 (2026-06-17)

- Async fixes, CN claims support, HTTP/SSE transport

## v1.0.0 (2026-06-15)

- Initial release: search_patents, get_patent, get_patent_claims via BigQuery
