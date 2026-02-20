---
name: Gen2WebText
description: Derivative of DLoggedWebTextPlus that starts from one URL, extracts content-focused links and summaries, and logs outputs using CommonCode FolderNavigator into datastore2 mine/domain/yyyy/mm/dd.
metadata: {"openclaw":{"requires":{"bins":["python","python3"]},"os":["win32","linux","darwin"]}}
---

# Gen2WebText

Gen2 derivative of DLoggedWebTextPlus, with centralized folder resolution via `CommonCode/FolderNavigator.py`.

## Execution

python gen2_web_text.py <domain> <url> --max-links <number> --words <number> --timeout-ms <milliseconds>

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
{OPENCLAW_ROOT}/data/datastore2/01-Mine/<domain>/YYYY/MM/DD/{PageName}.txt

Path resolution is handled by `FolderNavigator.from_fixed_point()` and `get_today_path(area="mine", domain=..., create=True)`.
