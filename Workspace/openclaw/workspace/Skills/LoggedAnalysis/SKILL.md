
---
name: LoggedAnalysis
description: Analyse all logged web search files for a given date and produce a concise assessment.
metadata: {"openclaw":{"requires":{"bins":["python"]}}}
---


This skill reads previously logged search files from the datastore and generates
3 high-level conclusions based on a user-provided assessment criteria.

It is used to summarize or interpret a day’s research activity.

## When to use

Use this skill when the user asks to:

- analyse searches from a specific day
- summarize research activity
- identify trends in logged searches
- draw conclusions from prior browsing/search logs
- review what was learned on a given date

Do NOT use this skill for live web search.
It only reads existing logs.

## Inputs

- `date` (string, required)
  Format: YYYY/MM/DD or YYYY-MM-DD  
  The day of logs to analyse.

- `criteria` (string, required)
  A short instruction describing how the logs should be assessed.
  Examples:
  - "Check for trends"
  - "Summarise main themes"
  - "Identify recurring interests"

- `name` (string, optional)
  Label used for the output filename.

## Execution

This skill runs a Python script.

Command:

python LoggedAnalysis.py --date "<date>" --criteria "<criteria>" --name "<name>"

Environment:

OPENCLAW_OUTPUT_ROOT optionally points to the datastore root.
If not set, the skill will use the workspace root when a datastore folder exists,
otherwise it falls back to C:\Users\<user>\.openclaw\data.

The script reads from:

<root>/datastore/YYYY/MM/DD/

and writes to:

<root>/analysis/YYYY/MM/DD/


## Behavior

The skill:

1. Loads all `.txt` files from:
   datastore/YYYY/MM/DD/
2. Builds a compact corpus of the day’s logs
3. Applies the assessment criteria
4. Produces exactly 3 conclusions
5. Writes a JSON analysis file to:
   analysis/YYYY/MM/DD/

It returns:

- the 3 conclusions
- the output file path

## Output

JSON object containing:

- date
- conclusions (array of 3 strings)
- output_path
- diagnostics (paths + file counts)

## Examples

User:  
"Analyse 2026/02/16 logs and check for trends"

→ Mechanical form:

LoggedAnalysis --date "2026/02/16" --criteria "Check for trends"

---

User:  
"Summarise yesterday’s searches"

→ Convert to date, then call:

LoggedAnalysis --date "<resolved YYYY/MM/DD>" --criteria "Summarise main themes"

## Notes

- This skill does not access the internet
- It only reads existing logs
- It is deterministic and file-backed
- It is safe to run repeatedly
