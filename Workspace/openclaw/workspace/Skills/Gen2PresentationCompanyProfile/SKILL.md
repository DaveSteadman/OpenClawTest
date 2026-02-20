---
name: Gen2PresentationCompanyProfile
description: Build a CompanyProfile PowerPoint slide from Gen2 analysis JSON for a domain and date.
metadata: {"openclaw":{"requires":{"bins":["python","python3"]},"os":["win32","linux","darwin"]}}
---

# Gen2PresentationCompanyProfile

Creates a single-slide CompanyProfile presentation from analysis files in datastore2.

## Execution

python gen2_presentation_company_profile.py <domain> --date <YYYY/MM/DD> --prompt "<formatting instruction>" --llm-timeout <seconds>

## Arguments

- domain required alphabetic string only A-Z or a-z
- --date required supports YYYY/MM/DD (also accepts '-')
- --prompt optional LLM formatting instruction for slide bullets
- --analysis-file optional absolute/relative path to a single analysis JSON file
- --max-analysis-files optional default 6
- --max-analysis-chars optional default 18000
- --llm-timeout optional default 90

## LLM configuration

Uses OpenAI-compatible Chat Completions API with environment variables:
- OPENAI_API_KEY required
- OPENAI_MODEL optional default gpt-4o-mini
- OPENAI_BASE_URL optional default https://api.openai.com/v1

## Behavior

1. Resolves analysis input from `02-Analysis/<domain>/` for provided date scope.
2. Builds bounded context from analysis JSON files.
3. Calls LLM to produce strict slide JSON payload.
4. Renders one A4 landscape PPTX slide using python-pptx.
5. Writes output to `03-Present/<domain>/<YYYY>/<MM>/<DD>/`.

## Output

On success returns JSON with:
- domain
- date
- analysis_files
- presentation_path
- payload_path
- status

On error returns JSON with:
- domain
- date
- error
- status
