---
name: LoggedWebSearch
description: Search the web via DuckDuckGo HTML endpoint (no API key) and log results to plain-text files.
capabilities:
  - filesystem:read
  - filesystem:write:workspace
metadata: {"openclaw":{"os":["win32","linux","darwin"],"requires":{"bins":["python","python3"]}}}
---

# DuckDuckGo Search (Logged)

Search the web using DuckDuckGo and automatically save results to a plain-text log file.

## When to use

Use this skill when the LoggedWebSearch name is included in the user query.

## Execution

This skill runs a Python script and parses its JSON output.

**Script location:** `workspace/Skills/LoggedWebSearch/logged_web_search.py`

**Command pattern:**
```
python logged_web_search.py --query "<search_query>" --max <number> --timeout <seconds> --sleep-ms <milliseconds>
```

## Command-Line Arguments

All arguments except `--query` are optional.

- `--query` (required, string)
  - The search query to send to DuckDuckGo
  - Example: `"python programming"`

- `--max` (optional, integer, default: 8)
  - Maximum number of results to return
  - Valid range: 1 to 25
  - Values outside range are clamped

- `--timeout` (optional, integer, default: 20)
  - Network timeout in seconds
  - Valid range: 5 to 60 seconds
  - Values outside range are clamped

- `--sleep-ms` (optional, integer, default: 0)
  - Milliseconds to sleep before searching
  - Useful for rate limiting
  - Example: `--sleep-ms 500` waits 0.5 seconds

## Response Format

The script outputs valid JSON to stdout.

### Success Response (status: "ok")
```json
{
  "query": "search query string",
  "results": [
    {
      "title": "Result Title",
      "url": "https://example.com",
      "snippet": "Brief description of result",
      "rank": 1
    }
  ],
  "log_path": "/path/to/logfile.txt",
  "count": 5,
  "status": "ok"
}
```

### Error Response (status: "error")
```json
{
  "query": "search query string",
  "error": "Error message describing what went wrong",
  "results": [],
  "count": 0,
  "status": "error"
}
```

## Logging

Search results are automatically saved to plain-text files at:

```
{OPENCLAW_OUTPUT_ROOT}/datastore/YYYY/MM/DD/{QueryName}.txt
```

Where:
- `YYYY/MM/DD` is the current date (e.g., 2026/02/17)
- `{QueryName}` is the query converted to CamelCase (e.g., "PythonProgramming")

If `OPENCLAW_OUTPUT_ROOT` environment variable is not set, defaults to:
```
~/.openclaw/data
```

Each log entry includes:
- Query text
- ISO timestamp
- Result title, URL, and snippet for each result

## Examples

**Example 1: Simple search**
```
python logged_web_search.py --query "climate change"
```
Returns up to 8 results (default).

**Example 2: Limited results with timeout**
```
python logged_web_search.py --query "python asyncio" --max 5 --timeout 15
```
Returns up to 5 results with 15-second timeout.

**Example 3: Rate-limited search**
```
python logged_web_search.py --query "AI news" --sleep-ms 1000
```
Waits 1 second before searching.

## Troubleshooting

- **No output from `python logged_web_search.py`**
  - Confirm [workspace/Skills/LoggedWebSearch/logged_web_search.py](workspace/Skills/LoggedWebSearch/logged_web_search.py) exists.
  - Verify Python is available in the sandbox (`python --version` or `python3 --version`).

- **No log files created**
  - Ensure `OPENCLAW_OUTPUT_ROOT` points to a valid, writable path.
  - If unset, the default `~/.openclaw/data` must be writable and exist.

- **Cannot list or create files**
  - The execution environment may be sandboxed; only declared filesystem capabilities are available.

- **Network timeout**: Increase `--timeout` value
- **No results**: Try a simpler query with fewer words
- **Connection refused**: Check internet connectivity
- **Log file not created**: Verify `OPENCLAW_OUTPUT_ROOT` environment variable or `.openclaw/data` directory exists
