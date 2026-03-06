```skill
---
name: Gen3ReadWebpageLinks
description: Read a source webpage, use LLM to pick 10 most relevant non-ad links, then run Gen3ReadWebpage flow for each selected link.
metadata: {"openclaw":{"requires":{"bins":["python","python3"]},"os":["win32","linux","darwin"]}}
---

# Gen3ReadWebpageLinks

Two-stage skill:
1) Reads a source URL and asks local LLM to choose the 10 best related links from real links found on that page.
2) Runs Gen3ReadWebpage-style extraction and LLM cleanup for each selected link.

## Execution

python gen3_read_webpage_links.py --url <source_url> --domain <domain> --area <area> --count 10 --timeout 30 --llm-model gpt-oss:20b

## Arguments

- --url required source webpage URL
- --domain required domain folder name under datastore3
- --area optional default mine
- --count optional default 10 range 1 to 20
- --timeout optional default 30 range 10 to 180
- --llm-model optional default gpt-oss:20b
- --selector-prompt optional custom prompt for link selection
- --llm-prompt optional custom prompt for linked-page content cleanup
- --llm-max-chars optional default 12000

## Output

Returns JSON:
- source_url
- domain
- area
- selected_count
- selected_links
- processed: [{url, output_path, status}]
- status

## Storage

Linked-page markdown files are written using the same Gen3ReadWebpage output logic:
`data/datastore3/<Area>/<Domain>/YYYY/MM/DD/<page-title-or-slug>.md`
```
