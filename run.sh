#!/bin/bash
# patent-mcp-server wrapper — sets GCP env then starts MCP server on stdio
export GOOGLE_APPLICATION_CREDENTIALS="/home/kuang/.hermes/cache/documents/doc_f31af7ba461f_leafy-summer-499803-k6-5f9b582e2127.json"
export GCP_PROJECT_ID="leafy-summer-499803-k6"
cd /home/kuang/.hermes/projects/patent-mcp-server || exit 1
exec python -m src.server
