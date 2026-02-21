---
name: Gen2MinerSchedule
description: Run a scheduled instruction list of web mining tasks (Gen2WebSearch and Gen2WebText) with daily/monthly cadence, using domain-aware logging.
metadata: {"openclaw":{"requires":{"bins":["python","python3"]},"os":["win32","linux","darwin"]}}
---

# Gen2MinerSchedule

Batch mining orchestrator skill for recurring topic instructions.

## What it does

- Reads a JSON instruction file.
- Selects tasks due for a run date based on cadence (`daily` or `monthly`).
- Executes:
  - `Gen2WebSearch` for query-based headline/topic mining.
  - `Gen2WebText` for URL-based content mining (for example BBC pages).
- Returns a structured JSON run summary.

## Execution

python gen2_miner_schedule.py --config <path_to_json> --cadence <daily|monthly|all> --date <YYYY-MM-DD> [--dry-run] [--all-configs] [--inter-config-delay <seconds>]

## Arguments

- --config optional path to instruction JSON (default: `gen2_miner_schedule_config.json` in this folder)
- --cadence optional: `daily` (default), `monthly`, or `all`
- --date optional run date (default today)
- --dry-run optional; plans tasks without executing them
- --max-tasks optional hard cap to limit executed tasks per run
- --all-configs optional; run all `gen2_miner_schedule*_config.json` files in the config directory
- --inter-config-delay optional seconds between each config run (used with `--all-configs`)

## Instruction JSON format

```json
{
  "default_domain": "GeneralNews",
  "tasks": [
    {
      "name": "UK Headlines",
      "enabled": true,
      "cadence": "daily",
      "type": "websearch",
      "domain": "GeneralNews",
      "query": "latest UK news headlines",
      "max": 8
    },
    {
      "name": "BBC News Front Page",
      "enabled": true,
      "cadence": "daily",
      "type": "webtext",
      "domain": "GeneralNews",
      "url": "https://www.bbc.com/news",
      "max_links": 8,
      "words": 220
    },
    {
      "name": "Monthly Europe Defence Headlines",
      "enabled": true,
      "cadence": "monthly",
      "day_of_month": 1,
      "type": "websearch",
      "query": "europe defence industry headlines"
    }
  ]
}
```

## Notes

- `monthly` tasks run only when `run_date.day == day_of_month`.
- If `domain` is omitted on a task, `default_domain` is used.
- Domain values must be alphabetic (A-Z, a-z), matching Gen2 skill constraints.

### Run all company configs in one invocation

```bash
python gen2_miner_schedule.py --config gen2_miner_schedule_SAAB_config.json --cadence daily --all-configs --inter-config-delay 10
```

This pays orchestration startup once, then executes all discovered company config files sequentially, with a fixed delay between configs.
