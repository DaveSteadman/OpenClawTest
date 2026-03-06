```skill
---
name: Gen3WebSearch
description: Search DuckDuckGo and process linked result pages with Gen3ReadWebpage-style LLM cleanup before logging by domain/date.
metadata: {"openclaw":{"requires":{"bins":["python","python3"]},"os":["win32","linux","darwin"]}}
---

# Gen3WebSearch

Creates search results and runs each linked page through the same local Ollama cleanup approach used by Gen3ReadWebpage.

## Execution

python gen3_web_search.py <domain> --query <search_query> --max <number> --timeout <seconds> --page-timeout <seconds> --date-context <none|month_year|year> --date <YYYY-MM-DD> --llm-model <model> --llm-max-chars <number>

## Arguments

- domain required alphabetic string only A-Z or a-z
- --query required search query
- --max optional default 10 range 1 to 25
- --timeout optional default 20 range 5 to 120
- --page-timeout optional default 30 range 5 to 180
- --sleep-ms optional default 0
- --date-context optional default none
- --date optional reference date YYYY-MM-DD
- --llm-model optional default gpt-oss:20b
- --llm-prompt optional custom cleanup prompt for linked pages
- --llm-max-chars optional default 12000

## Output

On success returns JSON with domain, query, effective_query, date_context, query_reference_date, count, results, log_path, status.
Each result includes title, url, snippet, rank, page_summary, page_words, page_status.

## Logging

Writes to:
{OPENCLAW_ROOT}/data/datastore3/01-Mine/<domain>/YYYY/MM/DD/{QueryName}.txt

Path resolution uses `FolderNavigator.from_fixed_point()` and `get_today_path(area="mine", domain=..., create=True)`.
```
