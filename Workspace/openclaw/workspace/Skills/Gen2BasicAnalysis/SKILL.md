---
name: Gen2BasicAnalysis
description: Analyze mined domain logs over a timeframe (YYYY, YYYY/MM, or YYYY/MM/DD) using an LLM prompt, and write analysis output to datastore2 02-Analysis via CommonCode FolderNavigator.
metadata: {"openclaw":{"requires":{"bins":["python","python3"]},"os":["win32","linux","darwin"]}}
---

# Gen2BasicAnalysis

Gen2 analysis skill for domain/timeframe trend assessment with LLM-based reasoning.

## Execution

python gen2_basic_analysis.py <domain> --timeframe <YYYY|YYYY/MM|YYYY/MM/DD> --prompt "<analysis prompt>" --max-files <number> --max-chars-per-file <number> --max-total-chars <number> --llm-timeout <seconds>

## Arguments

- domain required alphabetic string only A-Z or a-z
- --timeframe required supports YYYY or YYYY/MM or YYYY/MM/DD (also accepts '-')
- --prompt required LLM analysis instruction
- --max-files optional default 200
- --max-chars-per-file optional default 6000
- --max-total-chars optional default 180000
- --llm-timeout optional default 90

## LLM configuration

Uses OpenAI-compatible Chat Completions API with environment variables:
- OPENAI_API_KEY required
- OPENAI_MODEL optional default gpt-4o-mini
- OPENAI_BASE_URL optional default https://api.openai.com/v1

## Behavior

1. Resolves input folders from `01-Mine/<domain>` using `FolderNavigator`.
2. Loads `.txt` files matching timeframe.
3. Builds bounded corpus.
4. Sends corpus + prompt to LLM for analysis.
5. Writes JSON output to `02-Analysis/<domain>/<matching timeframe>/`.

## Output

On success returns JSON with:
- domain
- timeframe
- files_analyzed
- output_path
- status

On error returns JSON with:
- domain
- timeframe
- error
- status
