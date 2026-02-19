---
name: DLoggedWebTextPlus
description: Start from one explicit URL, extract content-focused links and page summaries, and store logs under a required domain subfolder in datastore. Use when runs should be grouped into separate domain areas to avoid datastore clutter.
metadata: {"openclaw":{"requires":{"bins":["python","python3"]},"os":["win32","linux","darwin"]}}
---

# DLoggedWebTextPlus

Domain-aware version of LoggedWebTextPlus.

## Execution

python d_logged_web_text_plus.py <domain> <url> --max-links <number> --words <number> --timeout-ms <milliseconds>

## Arguments

- domain required alphabetic string only A-Z or a-z
- url required start URL
- --max-links optional default 8 range 1 to 25
- --words optional default 200 range 80 to 400
- --timeout-ms optional default 15000

## Output

On success returns JSON with:
- domain
- url
- start_page_summary
- start_page_words
- links_processed
- results with rank, anchor_text, url, page_summary, page_words, page_status
- log_path
- status

On error returns JSON with:
- domain
- url
- error
- results
- links_processed
- log_path
- status

## Logging

Writes to:
{OPENCLAW_OUTPUT_ROOT}/datastore/<domain>/YYYY/MM/DD/{PageName}.txt

Domain is mandatory and must be alphabetic.
If OPENCLAW_OUTPUT_ROOT is not set, default is ~/.openclaw/data.
