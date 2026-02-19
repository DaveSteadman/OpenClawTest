---
name: LoggedWebSearchPlus
description: Search DuckDuckGo, follow result links, extract about 200 words from each linked HTML page, and log query, links, snippets, and page summaries to datastore. Use when the user asks for web search results plus short content from each result page.
metadata: {"openclaw":{"requires":{"bins":["python","python3"]},"os":["win32","linux","darwin"]}}
---

# LoggedWebSearchPlus

Search DuckDuckGo and enrich each result with extracted text from the linked page.

## Execution

python logged_web_search_plus.py --query <search_query> --max <number> --timeout <seconds> --page-timeout <seconds> --words <number> --sleep-ms <milliseconds>

## Arguments

- --query required search query
- --max optional default 8 range 1 to 25
- --timeout optional default 20 range 5 to 60
- --page-timeout optional default 15 range 5 to 60
- --words optional default 200 range 80 to 400
- --sleep-ms optional default 0

## Output

On success returns JSON with query, count, results, log_path, status.
Each result includes title, url, snippet, rank, page_summary, page_words, page_status.

On error returns JSON with query, error, results, count, status.

## Logging

Writes to:
{OPENCLAW_OUTPUT_ROOT}/datastore/YYYY/MM/DD/{QueryName}.txt

Each run appends query, timestamp, title, URL, DuckDuckGo snippet, and linked page summary text.

If OPENCLAW_OUTPUT_ROOT is not set, default is ~/.openclaw/data.
