---
name: PresentHtml
description: Build a high-end manager HTML presentation from analysis markdown files for a named domain/day folder.
metadata: {"openclaw":{"requires":{"bins":["python","python3"]},"os":["win32","linux","darwin"]}}
---

# PresentHtml

Creates a polished HTML executive presentation from analysis outputs in datastore3.

## Execution

python present_html.py <domain> --timeframe <YYYY/MM/DD> [--source-domain <domain>] [--title <title>] [--max-files <n>]

## Arguments

- domain required output presentation domain (alphabetic only)
- --timeframe required YYYY/MM/DD (also accepts '-')
- --source-domain optional analysis source domain (defaults to domain)
- --title optional presentation title
- --max-files optional default 4

## Behavior

1. Reads `02-Analysis/<source-domain>/<YYYY>/<MM>/<DD>/` markdown files.
2. Parses section headings and narrative content.
3. Builds manager-ready HTML with modern layout and source listing.
4. Writes output to `03-Present/<domain>/<YYYY>/<MM>/<DD>/`.

## Output

On success returns JSON with:
- domain
- source_domain
- timeframe
- analysis_files
- output_path
- status

On error returns JSON with:
- domain
- source_domain
- timeframe
- error
- status
