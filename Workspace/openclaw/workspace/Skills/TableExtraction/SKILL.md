---
name: TableExtraction
description: Fetch a web page, extract the main data table, save as CSV.
capabilities:
  - filesystem:read
  - filesystem:write:workspace
metadata: {"openclaw":{"os":["win32","linux","darwin"],"requires":{"bins":["python","python3"]}}}
---

# TableExtraction

Fetch a web page, extract the main data table, and save as CSV.

## Usage

python TableExtraction.py --url "<URL>" [--timeout-ms 15000]

## Parameters

- --url (required): The web page URL to analyze
- --timeout-ms (optional, default 15000): Network timeout in milliseconds

## Requirements

- Python 3.8+
- Dependencies: requests, beautifulsoup4, lxml, pandas

## Response

Returns JSON with fields:
- url: The final URL (after redirects)
- csv_path: Path to the saved CSV file
- rows: Number of data rows extracted (excluding header)
- status: "ok" or "error"
- error: Error message (if status is "error")

## How It Works

1. Fetches the webpage HTML
2. Uses pandas to find all HTML tables
3. Selects the largest table (by row × column count)
4. Converts to CSV format
5. Saves to datastore as {PageName}_table.csv

## Logging

CSV files are saved to:
{OPENCLAW_OUTPUT_ROOT}/datastore/YYYY/MM/DD/{PageName}_table.csv

If OPENCLAW_OUTPUT_ROOT is not set, defaults to ~/.openclaw/data

## Examples

Extract table from FTSE-100 page:
python TableExtraction.py --url "https://www.hl.co.uk/shares/stock-market-summary/ftse-100"

Custom timeout:
python TableExtraction.py --url "https://example.com/data" --timeout-ms 30000
