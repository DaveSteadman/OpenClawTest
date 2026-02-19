---
name: LoggedWebTextPlus
description: Start from one explicit website URL, extract links from that page, fetch linked HTML pages, extract about 200 words from each, and log results to datastore. Use when the user wants page content from links found on a specific site.
metadata: {"openclaw":{"requires":{"bins":["python","python3"]},"os":["win32","linux","darwin"]}}
---

# LoggedWebTextPlus

Given a start URL, this skill collects links on that page and extracts short text summaries from linked pages.

## Execution

python logged_web_text_plus.py --url <start_url> --max-links <number> --words <number> --timeout-ms <milliseconds>

## Arguments

- --url required start page URL
- --max-links optional default 8 range 1 to 25
- --words optional default 200 range 80 to 400
- --timeout-ms optional default 15000

## Output

On success returns JSON with:
- url
- start_page_summary
- start_page_words
- links_processed
- results with rank, anchor_text, url, page_summary, page_words, page_status
- log_path
- status

On error returns JSON with:
- url
- error
- results
- links_processed
- log_path
- status

## Logging

Writes to:
{OPENCLAW_OUTPUT_ROOT}/datastore/YYYY/MM/DD/{PageName}.txt

Each run appends the start URL summary and linked page summaries.

If OPENCLAW_OUTPUT_ROOT is not set, default is ~/.openclaw/data.
