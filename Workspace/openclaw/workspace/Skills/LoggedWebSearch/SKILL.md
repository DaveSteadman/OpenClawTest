---
name: LoggedWebSearch
description: Search the web via DuckDuckGo HTML endpoint (no API key) and log results to plain-text files.
metadata: {"openclaw":{"os":["win32","linux","darwin"],"requires":{"bins":["python","python3"]}}}
---

# DuckDuckGo Search (Logged)

Use this skill when you need quick web search results without an API key, and also want a plain-text log file.

## Tool
Run the script and parse its JSON output.

- Script: {baseDir}/logged_web_search.py
- Input: a query string, plus optional flags
- Output: JSON with { query, results[], log_path }

## How to run
Prefer this pattern:

```bash
python "{baseDir}/logged_web_search.py" --query "your query" --max 8
```

## Logging
A plain-text log file is created at:

- {workspaceDir}/datastore/YYYY/MM/DD/<CamelCaseQuery>.txt
