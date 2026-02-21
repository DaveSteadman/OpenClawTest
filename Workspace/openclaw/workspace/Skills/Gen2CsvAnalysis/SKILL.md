---
name: Gen2CsvAnalysis
description: Analyze mined domain logs over a timeframe (YYYY, YYYY/MM, or YYYY/MM/DD) using an LLM prompt, normalize results into tabular data, and write CSV output to datastore2 02-Analysis via CommonCode FolderNavigator.
metadata: {"openclaw":{"requires":{"bins":["python","python3"]},"os":["win32","linux","darwin"]}}
---

# Gen2CsvAnalysis

Gen2 analysis skill for producing CSV outputs from mined domain logs.

## Execution

python gen2_csv_analysis.py <domain> --timeframe <YYYY|YYYY/MM|YYYY/MM/DD> --prompt "<csv analysis prompt>" --max-files <number> --max-chars-per-file <number> --max-total-chars <number> --llm-timeout <seconds>

## Arguments

- domain required alphabetic string only A-Z or a-z
- --timeframe required supports YYYY or YYYY/MM or YYYY/MM/DD (also accepts '-')
- --prompt required LLM analysis instruction, should clearly request a CSV-style table outcome
- --max-files optional default 200
- --max-chars-per-file optional default 6000
- --max-total-chars optional default 180000
- --llm-timeout optional default 90

## Prompt guidance

Use explicit table-oriented instructions for best results, for example:
- "Create CSV list of projects and revenue across the last 5 years."
- "Create CSV table of supplier, contract value, contract start date, and risk category."

The skill enforces a structured schema from the LLM and then writes strict CSV.

## LLM configuration

Uses OpenAI-compatible Chat Completions API with environment variables:
- OPENAI_API_KEY required
- OPENAI_MODEL optional default gpt-4o-mini
- OPENAI_BASE_URL optional default https://api.openai.com/v1

## Behavior

1. Resolves input folders from `01-Mine/<domain>` using `FolderNavigator`.
2. Loads `.txt` files matching timeframe.
3. Builds bounded corpus.
4. Sends corpus + prompt to LLM with a table schema contract.
5. Writes CSV output to `02-Analysis/<domain>/<matching timeframe>/`.

## Output

On success returns JSON with:
- domain
- timeframe
- files_analyzed
- output_path
- columns
- rows
- status

On error returns JSON with:
- domain
- timeframe
- error
- status
