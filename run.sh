#!/bin/bash
# patent-mcp-server wrapper — sets GCP env then starts MCP server on stdio
export GOOGLE_APPLICATION_CREDENTIALS="/home/kuang/.hermes/projects/patent-mcp-server/gcp-key.json"
export GCP_PROJECT_ID="leafy-summer-499803-k6"
export HTTPS_PROXY="http://127.0.0.1:7897"
export HTTP_PROXY="http://127.0.0.1:7897"
cd /home/kuang/.hermes/projects/patent-mcp-server || exit 1
exec python -m src.server
