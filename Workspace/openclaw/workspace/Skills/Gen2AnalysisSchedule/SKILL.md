# Gen2AnalysisSchedule

Runs recurring analysis tasks from JSON configs, similar to Gen2MinerSchedule.

## Supported task types

- `basic` -> `Gen2BasicAnalysis/gen2_basic_analysis.py`
- `csv` -> `Gen2CsvAnalysis/gen2_csv_analysis.py`
- `report` -> `Gen2ReportAnalysis/gen2_report_analysis.py`

## CLI

- `--config <path>`
- `--cadence daily|monthly|all`
- `--date YYYY-MM-DD`
- `--model <model_name>`
- `--dry-run`
- `--max-tasks <int>`
- `--all-configs`
- `--inter-config-delay <seconds>`

## Config shape

```json
{
  "default_domain": "SAAB",
  "tasks": [
    {
      "name": "SAAB Basic Daily Brief",
      "enabled": true,
      "cadence": "daily",
      "type": "basic",
      "timeframe": "{today_slash}",
      "prompt": "Summarise key developments.",
      "model": "openai-oss-20b",
      "llm_timeout": 300
    }
  ]
}
```

## Model selection

- `--model` on `Gen2AnalysisSchedule` sets the LLM model for all tasks in that run.
- Task-level `model` in JSON overrides the scheduler-level `--model` value.
- If neither is provided, downstream skills fall back to `OPENAI_MODEL` (then their internal default).

## Time tokens

- `{today_iso}` -> `YYYY-MM-DD`
- `{today_slash}` -> `YYYY/MM/DD`
- `{year}` -> `YYYY`
- `{year_month}` -> `YYYY/MM`
