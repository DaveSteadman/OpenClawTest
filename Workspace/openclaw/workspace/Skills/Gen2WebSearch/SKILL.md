---
name: Gen2WebSearch
description: Search DuckDuckGo, summarize linked result pages with robust content extraction, and save logs by domain/date using CommonCode FolderNavigator.
metadata: {"openclaw":{"requires":{"bins":["python","python3"]},"os":["win32","linux","darwin"]}}
---

# Gen2WebSearch

Combines search from LoggedWebSearchPlus with page extraction quality from Gen2WebText, and domain-aware folder resolution via CommonCode FolderNavigator.

## Execution

python gen2_web_search.py <domain> --query <search_query> --max <number> --timeout <seconds> --page-timeout <seconds> --words <number> --sleep-ms <milliseconds>

## Arguments

- domain required alphabetic string only A-Z or a-z
- --query required search query
- --max optional default 8 range 1 to 25
- --timeout optional default 20 range 5 to 60
- --page-timeout optional default 15 range 5 to 60
- --words optional default 200 range 80 to 400
- --sleep-ms optional default 0

## Output

On success returns JSON with domain, query, count, results, log_path, status.
Each result includes title, url, snippet, rank, page_summary, page_words, page_status.

On error returns JSON with domain, query, error, results, count, status.

## Logging

Writes to:
{OPENCLAW_ROOT}/data/datastore2/01-Mine/<domain>/YYYY/MM/DD/{QueryName}.txt

File name is derived from the query text.
Path resolution is handled by `FolderNavigator.from_fixed_point()` and `get_today_path(area="mine", domain=..., create=True)`.
