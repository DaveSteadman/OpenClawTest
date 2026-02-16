---
name: WebSearch
description: Search the web via DuckDuckGo HTML endpoint (no API key). Returns structured JSON results.
metadata: {"openclaw":{"os":["win32","linux","darwin"],"requires":{"bins":["python","python3"]}}}
---

# DuckDuckGo Search (Local)

Use this skill when you need quick web search results without an API key.

## Tool
Run the script and parse its JSON output.

- Script: `{baseDir}/ddg_search.py`
- Input: a query string, plus optional flags
- Output: JSON with `{ query, results[] }`

## How to run
Prefer this pattern:

```bash
python "{baseDir}/ddg_search.py" --query "your query" --max 8
