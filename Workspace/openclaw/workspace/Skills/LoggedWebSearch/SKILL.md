---
name: LoggedWebSearch
description: Search the web via DuckDuckGo HTML endpoint (no API key) and log results to plain-text files.
version: 1.0.0
metadata:
  openclaw:
    os:
      - win32
      - linux
      - darwin
    requires:
      bins:
        - python
        - python3
  changelog:
    - version: 1.0.0
      date: 2026-02-18
      changes:
        - Enhanced metadata with explicit OS and binary requirements
        - Removed API key requirements (DuckDuckGo does not require authentication)
        - Added detailed execution instructions and sample commands
        - Improved error reporting documentation
        - Added versioning and changelog
---

# DuckDuckGo Search (Logged)

Use this skill when you need quick web search results without an API key, and also want a plain-text log file.

**Key Features:**
- No authentication or API keys required
- Automatic logging to structured plain-text files
- Cross-platform compatibility (Windows, Linux, macOS)
- Configurable result limits and timeouts

## Tool

Run the script and parse its JSON output.

**Script:** `{baseDir}/logged_web_search.py`

### Inputs

- `--query` (string, **required**)  
  The search query string to execute on DuckDuckGo.

- `--max` (integer, optional, default: 8)  
  Maximum number of search results to return (range: 1-25).

- `--timeout` (integer, optional, default: 20)  
  HTTP request timeout in seconds.

- `--sleep-ms` (integer, optional, default: 0)  
  Delay in milliseconds before executing the search.

### Output

JSON object containing:

```json
{
  "query": "search query",
  "results": [
    {
      "title": "Result Title",
      "url": "https://example.com",
      "snippet": "Description text",
      "rank": 1
    }
  ],
  "log_path": "/path/to/log/file.txt",
  "diag": {
    "cwd": "/current/working/directory",
    "__file__": "/path/to/script",
    "output_root": "/path/to/output/root"
  }
}
```

On error:

```json
{
  "query": "search query",
  "error": "error message",
  "results": [],
  "diag": { ... }
}
```

## How to Run

### Basic Usage

```bash
python "{baseDir}/logged_web_search.py" --query "your search query"
```

### With Custom Options

```bash
python "{baseDir}/logged_web_search.py" --query "Python tutorials" --max 10 --timeout 30
```

### Cross-Platform Examples

**Windows:**
```cmd
python "{baseDir}\logged_web_search.py" --query "machine learning" --max 5
```

**Linux/macOS:**
```bash
python3 "{baseDir}/logged_web_search.py" --query "artificial intelligence" --max 8
```

### Using python3 explicitly

```bash
python3 "{baseDir}/logged_web_search.py" --query "data science" --max 12
```

## Logging

A plain-text log file is automatically created at:

**Default path:** `{workspaceDir}/datastore/YYYY/MM/DD/<CamelCaseQuery>.txt`

**Custom path:** Set the `OPENCLAW_OUTPUT_ROOT` environment variable to specify a custom output directory:

```bash
# Linux/macOS
export OPENCLAW_OUTPUT_ROOT="/path/to/custom/output"

# Windows
set OPENCLAW_OUTPUT_ROOT=C:\path\to\custom\output
```

### Log File Format

Each search is appended to the daily log file with the following format:

```
Query: your search query
Timestamp: 2026-02-18T13:00:00
- Result Title
  https://example.com
  Description snippet

```

## Environment Variables

- `OPENCLAW_OUTPUT_ROOT` (optional)  
  Root directory for output files. If not set, defaults to `~/.openclaw/data`.

## Requirements

### Operating Systems
- Windows (win32)
- Linux
- macOS (darwin)

### Binaries
- Python 3.6 or higher (accessible as `python` or `python3`)

### Dependencies
- No external packages required (uses only Python standard library)

### Authentication
- **None required** - DuckDuckGo HTML endpoint is free and open

## Error Handling

The script handles common errors gracefully:

- **Network errors:** Returns error in JSON with details
- **Timeout errors:** Configurable via `--timeout` parameter
- **Invalid queries:** Returns empty results array
- **File system errors:** Reported in diagnostic output

### Sandbox Considerations

To ensure proper execution in sandboxed environments:

1. **Python availability:** Verify `python` or `python3` is in system PATH
2. **File permissions:** Ensure write access to output directory
3. **Network access:** Requires HTTP/HTTPS connectivity to duckduckgo.com
4. **Environment variables:** Set `OPENCLAW_OUTPUT_ROOT` if default path is restricted

## Troubleshooting

### Issue: "command not found: python"
**Solution:** Use `python3` instead, or ensure Python is installed and in PATH.

### Issue: "Permission denied" when writing logs
**Solution:** Check write permissions for the output directory or set a custom `OPENCLAW_OUTPUT_ROOT`.

### Issue: Network timeout errors
**Solution:** Increase the `--timeout` value or check network connectivity.

### Issue: Empty results
**Solution:** Try a different query or check if DuckDuckGo is accessible from your network.

## Notes

- This skill does not require API keys or authentication
- Results are fetched from DuckDuckGo's HTML endpoint (not API)
- The User-Agent is set to "Mozilla/5.0 (compatible; OpenClawSkill/1.0)"
- Search results are limited to a maximum of 25 per query
- Log files are appended to (not overwritten) for date-based organization
