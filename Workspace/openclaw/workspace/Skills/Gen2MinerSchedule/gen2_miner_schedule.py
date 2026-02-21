#!/usr/bin/env python3
"""Gen2MinerSchedule - recurring topic miner orchestrator for Gen2WebSearch and Gen2WebText."""

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path


def validate_domain(domain: str) -> str:
    value = (domain or "").strip()
    if not value:
        raise ValueError("Domain must be non-empty")
    if not re.fullmatch(r"[A-Za-z]+", value):
        raise ValueError(f"Invalid domain '{domain}'. Domain must be alphabetic only (A-Z, a-z)")
    return value


def parse_date(value: str | None) -> dt.date:
    if not value:
        return dt.date.today()
    cleaned = value.strip()
    try:
        return dt.date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError("--date must be YYYY-MM-DD") from exc


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Config root must be a JSON object")
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("Config must include 'tasks' as an array")
    return data


def task_is_due(task: dict, run_date: dt.date, cadence_filter: str) -> tuple[bool, str]:
    enabled = bool(task.get("enabled", True))
    if not enabled:
        return False, "disabled"

    cadence = str(task.get("cadence", "daily")).strip().lower()
    if cadence not in {"daily", "monthly"}:
        return False, f"unsupported cadence '{cadence}'"

    if cadence_filter != "all" and cadence != cadence_filter:
        return False, f"filtered by cadence={cadence_filter}"

    if cadence == "monthly":
        day_of_month = int(task.get("day_of_month", 1))
        if day_of_month < 1 or day_of_month > 31:
            return False, "invalid day_of_month"
        if run_date.day != day_of_month:
            return False, f"monthly task due on day {day_of_month}"

    return True, "due"


def parse_json_from_output(text: str) -> dict:
    content = (text or "").strip()
    if not content:
        return {}

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"raw": content}


def run_task(task: dict, default_domain: str, skills_root: Path, python_exe: str, dry_run: bool) -> dict:
    task_name = str(task.get("name", "Unnamed Task")).strip() or "Unnamed Task"
    task_type = str(task.get("type", "")).strip().lower()
    domain = validate_domain(task.get("domain") or default_domain)

    if task_type == "websearch":
        script = skills_root / "Gen2WebSearch" / "gen2_web_search.py"
        query = str(task.get("query", "")).strip()
        if not query:
            raise ValueError(f"Task '{task_name}' missing 'query'")
        max_results = int(task.get("max", 8))
        timeout = int(task.get("timeout", 20))
        page_timeout = int(task.get("page_timeout", 15))
        words = int(task.get("words", 200))
        sleep_ms = int(task.get("sleep_ms", 0))

        cmd = [
            python_exe,
            str(script),
            domain,
            "--query",
            query,
            "--max",
            str(max_results),
            "--timeout",
            str(timeout),
            "--page-timeout",
            str(page_timeout),
            "--words",
            str(words),
            "--sleep-ms",
            str(sleep_ms),
        ]

    elif task_type == "webtext":
        script = skills_root / "Gen2WebText" / "gen2_web_text.py"
        url = str(task.get("url", "")).strip()
        if not url:
            raise ValueError(f"Task '{task_name}' missing 'url'")
        max_links = int(task.get("max_links", 8))
        words = int(task.get("words", 200))
        timeout_ms = int(task.get("timeout_ms", 15000))

        cmd = [
            python_exe,
            str(script),
            domain,
            url,
            "--max-links",
            str(max_links),
            "--words",
            str(words),
            "--timeout-ms",
            str(timeout_ms),
        ]

    else:
        raise ValueError(f"Task '{task_name}' has unsupported type '{task_type}'")

    if dry_run:
        return {
            "name": task_name,
            "type": task_type,
            "domain": domain,
            "command": cmd,
            "status": "dry_run",
        }

    process = subprocess.run(cmd, capture_output=True, text=True, check=False)
    stdout = (process.stdout or "").strip()
    stderr = (process.stderr or "").strip()
    parsed = parse_json_from_output(stdout)

    status = "ok" if process.returncode == 0 else "error"
    return {
        "name": task_name,
        "type": task_type,
        "domain": domain,
        "command": cmd,
        "exit_code": process.returncode,
        "status": status,
        "result": parsed,
        "stderr": stderr,
    }


def run_single_config(config_path: Path, args, run_ts: str, skills_root: Path, python_exe: str) -> tuple[dict, int]:
    try:
        run_date = parse_date(args.date)
        config = load_config(config_path)
        default_domain = validate_domain(config.get("default_domain", "GeneralNews"))
    except Exception as exc:
        summary = {
            "status": "error",
            "run_ts": run_ts,
            "run_date": args.date if args.date else dt.date.today().isoformat(),
            "cadence": args.cadence,
            "dry_run": args.dry_run,
            "config_path": str(config_path),
            "tasks_total": 0,
            "tasks_due": 0,
            "tasks_executed": 0,
            "tasks_skipped": 0,
            "tasks_failed": 0,
            "results": [],
            "error": str(exc),
        }
        return summary, 1

    summary = {
        "status": "ok",
        "run_ts": run_ts,
        "run_date": run_date.isoformat(),
        "cadence": args.cadence,
        "dry_run": args.dry_run,
        "config_path": str(config_path),
        "tasks_total": len(config.get("tasks", [])),
        "tasks_due": 0,
        "tasks_executed": 0,
        "tasks_skipped": 0,
        "tasks_failed": 0,
        "results": [],
    }

    for task in config.get("tasks", []):
        if not isinstance(task, dict):
            summary["tasks_skipped"] += 1
            summary["results"].append({"status": "skipped", "reason": "task entry must be object"})
            continue

        due, reason = task_is_due(task, run_date=run_date, cadence_filter=args.cadence)
        if not due:
            summary["tasks_skipped"] += 1
            summary["results"].append(
                {
                    "name": str(task.get("name", "Unnamed Task")),
                    "status": "skipped",
                    "reason": reason,
                }
            )
            continue

        summary["tasks_due"] += 1

        if args.max_tasks > 0 and summary["tasks_executed"] >= args.max_tasks:
            summary["tasks_skipped"] += 1
            summary["results"].append(
                {
                    "name": str(task.get("name", "Unnamed Task")),
                    "status": "skipped",
                    "reason": "max_tasks cap reached",
                }
            )
            continue

        try:
            result = run_task(
                task=task,
                default_domain=default_domain,
                skills_root=skills_root,
                python_exe=python_exe,
                dry_run=args.dry_run,
            )
            summary["results"].append(result)
            summary["tasks_executed"] += 1
            if result.get("status") == "error":
                summary["tasks_failed"] += 1
        except Exception as exc:
            summary["tasks_executed"] += 1
            summary["tasks_failed"] += 1
            summary["results"].append(
                {
                    "name": str(task.get("name", "Unnamed Task")),
                    "status": "error",
                    "error": str(exc),
                }
            )

    if summary["tasks_failed"] > 0:
        summary["status"] = "partial_error"

    exit_code = 0 if summary["tasks_failed"] == 0 else 1
    return summary, exit_code


def discover_config_files(base_config_path: Path) -> list[Path]:
    config_dir = base_config_path.parent
    all_candidates = sorted(config_dir.glob("gen2_miner_schedule*_config.json"))
    excluded = {
        "gen2_miner_schedule_config.json",
        "gen2_miner_schedule_defence_companies_config.json",
    }
    selected = [path.resolve() for path in all_candidates if path.name not in excluded]
    if base_config_path.resolve() not in selected:
        selected.append(base_config_path.resolve())
        selected.sort()
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Run recurring web mining tasks from JSON config")
    parser.add_argument("--config", default="gen2_miner_schedule_config.json", help="Path to task config JSON")
    parser.add_argument("--cadence", default="daily", choices=["daily", "monthly", "all"])
    parser.add_argument("--date", default="", help="Run date in YYYY-MM-DD (default today)")
    parser.add_argument("--dry-run", action="store_true", help="Plan tasks without executing")
    parser.add_argument("--max-tasks", type=int, default=0, help="Optional execution cap")
    parser.add_argument(
        "--all-configs",
        action="store_true",
        help="Run all gen2_miner_schedule*_config.json files in the config directory",
    )
    parser.add_argument(
        "--inter-config-delay",
        type=int,
        default=0,
        help="Delay in seconds between configs when using --all-configs",
    )

    try:
        args = parser.parse_args()
    except SystemExit:
        return 1

    run_ts = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    if args.inter_config_delay < 0:
        print(json.dumps({"status": "error", "error": "--inter-config-delay must be >= 0"}, ensure_ascii=True))
        return 1

    this_script = Path(__file__).resolve()
    skills_root = this_script.parent.parent
    python_exe = sys.executable

    try:
        base_config_path = Path(args.config).resolve()
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=True))
        return 1

    if not args.all_configs:
        summary, exit_code = run_single_config(base_config_path, args, run_ts, skills_root, python_exe)
        print(json.dumps(summary, ensure_ascii=True))
        return exit_code

    config_paths = discover_config_files(base_config_path)
    aggregate = {
        "status": "ok",
        "run_ts": run_ts,
        "mode": "all_configs",
        "config_directory": str(base_config_path.parent),
        "inter_config_delay_seconds": args.inter_config_delay,
        "configs_total": len(config_paths),
        "configs_executed": 0,
        "configs_failed": 0,
        "tasks_total": 0,
        "tasks_due": 0,
        "tasks_executed": 0,
        "tasks_skipped": 0,
        "tasks_failed": 0,
        "config_runs": [],
    }

    for index, config_path in enumerate(config_paths):
        summary, exit_code = run_single_config(config_path, args, run_ts, skills_root, python_exe)
        aggregate["config_runs"].append(summary)
        aggregate["configs_executed"] += 1
        aggregate["tasks_total"] += int(summary.get("tasks_total", 0))
        aggregate["tasks_due"] += int(summary.get("tasks_due", 0))
        aggregate["tasks_executed"] += int(summary.get("tasks_executed", 0))
        aggregate["tasks_skipped"] += int(summary.get("tasks_skipped", 0))
        aggregate["tasks_failed"] += int(summary.get("tasks_failed", 0))
        if exit_code != 0:
            aggregate["configs_failed"] += 1

        if args.inter_config_delay > 0 and index < len(config_paths) - 1:
            time.sleep(args.inter_config_delay)

    if aggregate["configs_failed"] > 0 or aggregate["tasks_failed"] > 0:
        aggregate["status"] = "partial_error"

    print(json.dumps(aggregate, ensure_ascii=True))
    return 0 if aggregate["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
