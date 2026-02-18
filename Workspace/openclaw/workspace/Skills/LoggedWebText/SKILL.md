---
name: LoggedWebText
description: Fetch a web page (single URL), extract readable plain text from HTML, and log to datastore.
capabilities:
  - filesystem:read
  - filesystem:write:workspace
metadata: {"openclaw":{"os":["win32","linux","darwin"],"requires":{"bins":["python","python3"]}}}
---

# LoggedWebText

Fetch a web page, extract readable plain text, and log to datastore.

## Usage

python LoggedWebText.py --url "<URL>" [--max-chars 50000] [--timeout-ms 15000]

## Parameters

- --url (required): The web page URL to fetch
- --max-chars (optional, default 50000): Maximum characters to extract
- --timeout-ms (optional, default 15000): Network timeout in milliseconds

## Response

Returns JSON with fields:
- url: The final URL (after redirects)
- chars: Number of extracted characters
- text: The extracted readable text
- log_path: Path to the saved log file
- status: "ok" or "error"
- error: Error message (if status is "error")

## Logging

Extracted text is saved to:
{OPENCLAW_OUTPUT_ROOT}/datastore/YYYY/MM/DD/{PageName}.txt

If OPENCLAW_OUTPUT_ROOT is not set, defaults to ~/.openclaw/data

## Examples

Fetch a page:
python LoggedWebText.py --url "https://www.example.com"

Limit to 10,000 characters:
python LoggedWebText.py --url "https://www.example.com" --max-chars 10000

Custom 30-second timeout:
python LoggedWebText.py --url "https://www.example.com" --timeout-ms 30000

