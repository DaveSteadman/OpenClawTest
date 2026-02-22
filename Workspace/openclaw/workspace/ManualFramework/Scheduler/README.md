# ManualFramework Scheduler (MVP)

Minimal Python launcher for deterministic scheduled tasks.

## What it does

- Starts `ollama serve` at startup.
- Runs scheduled tasks (`mine`, `analyse`, `present`) as child processes.
- Prints each command as it starts and reports completion status.
- Stops managed startup processes (including Ollama) on shutdown.
- Writes per-run logs and a `summary.json` report.

## One-line start

From this folder:

- `run_scheduler.cmd`

Or from terminal:

- `C:/Users/daves/.openclaw/.venv/Scripts/python.exe python_launcher.py --config runbook.json`

## Runtime control

- While running, press `q` to initiate graceful shutdown.
- The launcher prints a heartbeat every 10 seconds by default.
- Set `scheduler.status_interval_sec` in `runbook.json` to change heartbeat cadence.

## Preflight checks

- At startup, the launcher prints resolved token values (including `{workspace}` and `{python}`).
- It validates each task/startup `cwd` and prints `exists=True/False` for executables and Python scripts.
- Missing task script paths fail fast before entering the schedule loop.

## Runbook file

- Edit `runbook.json` to adjust tasks, intervals, and command args.
- Supported tokens in strings:
  - `{python}`
  - `{python_executable}`
  - `{workspace}`
  - `{config_dir}`
  - `{today_iso}` (`YYYY-MM-DD`)
  - `{today_slash}` (`YYYY/MM/DD`)

## Logs

Each run writes to:

- `runs/<timestamp>/startup/...`
- `runs/<timestamp>/tasks/<task_id>/<timestamp>/stdout.log`
- `runs/<timestamp>/tasks/<task_id>/<timestamp>/stderr.log`
- `runs/<timestamp>/summary.json`
