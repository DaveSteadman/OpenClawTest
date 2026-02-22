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
      "llm_timeout": 300
    }
  ]
}
```

## Time tokens

- `{today_iso}` -> `YYYY-MM-DD`
- `{today_slash}` -> `YYYY/MM/DD`
- `{year}` -> `YYYY`
- `{year_month}` -> `YYYY/MM`
