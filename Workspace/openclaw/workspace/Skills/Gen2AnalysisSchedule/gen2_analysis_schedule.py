#!/usr/bin/env python3
"""Gen2AnalysisSchedule - recurring orchestrator for Gen2Basic/Csv/Report analysis skills."""

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from queue import Empty, Queue
from pathlib import Path
from threading import Thread


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


def _pump_stream(stream, stream_name: str, output_queue: Queue) -> None:
    try:
        for raw_line in iter(stream.readline, ""):
            output_queue.put((stream_name, raw_line.rstrip("\r\n")))
    finally:
        output_queue.put((stream_name, None))


def run_subprocess_with_streaming(
    cmd: list[str],
    context_label: str,
    heartbeat_sec: int = 10,
    stall_timeout_sec: int = 240,
) -> tuple[int, str, str, float]:
    start = time.monotonic()
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    output_queue: Queue = Queue()
    stdout_done = False
    stderr_done = False
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    latest_text = ""
    last_heartbeat = 0.0
    last_activity = time.monotonic()
    stalled = False

    stdout_thread = Thread(target=_pump_stream, args=(process.stdout, "stdout", output_queue), daemon=True)
    stderr_thread = Thread(target=_pump_stream, args=(process.stderr, "stderr", output_queue), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    while True:
        drained = False
        while True:
            try:
                stream_name, line = output_queue.get_nowait()
            except Empty:
                break

            drained = True
            if line is None:
                if stream_name == "stdout":
                    stdout_done = True
                else:
                    stderr_done = True
                continue

            if stream_name == "stdout":
                stdout_lines.append(line)
            else:
                stderr_lines.append(line)

            text = line.strip()
            if text:
                last_activity = time.monotonic()
                latest_text = text
                if stream_name == "stdout":
                    print(f"[analysis:token] {context_label} :: {text}", flush=True)
                else:
                    print(f"[analysis:stderr] {context_label} :: {text}", flush=True)

        now = time.monotonic()
        if now - last_heartbeat >= max(1, heartbeat_sec):
            elapsed = now - start
            latest_preview = latest_text[:220] if latest_text else "no output yet"
            print(
                f"[analysis:progress] {context_label} elapsed_sec={elapsed:.1f} latest={latest_preview}",
                flush=True,
            )
            last_heartbeat = now

        idle_for = now - last_activity
        if process.poll() is None and idle_for >= max(30, stall_timeout_sec):
            stalled = True
            print(
                f"[analysis:stall] {context_label} idle_sec={idle_for:.1f} threshold_sec={stall_timeout_sec} action=terminate",
                flush=True,
            )
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            break

        rc = process.poll()
        if rc is not None and stdout_done and stderr_done:
            break

        if not drained:
            time.sleep(0.2)

    duration = time.monotonic() - start
    rc = process.returncode
    if stalled and (rc is None or rc == 0):
        rc = 124
        stderr_lines.append(f"stalled: no output for >= {stall_timeout_sec}s")
    return (rc or 0), "\n".join(stdout_lines), "\n".join(stderr_lines), duration


def expand_tokens(value: str, run_date: dt.date) -> str:
    text = (value or "").strip()
    if not text:
        return text

    replacements = {
        "{today_iso}": run_date.isoformat(),
        "{today_slash}": run_date.strftime("%Y/%m/%d"),
        "{year}": f"{run_date.year:04d}",
        "{year_month}": run_date.strftime("%Y/%m"),
    }

    for token, token_value in replacements.items():
        text = text.replace(token, token_value)
    return text


def run_task(
    task: dict,
    default_domain: str,
    skills_root: Path,
    python_exe: str,
    dry_run: bool,
    run_date: dt.date,
    config_name: str,
    section_index: int,
) -> dict:
    task_name = str(task.get("name", "Unnamed Task")).strip() or "Unnamed Task"
    task_type = str(task.get("type", "basic")).strip().lower()
    domain = validate_domain(task.get("domain") or default_domain)

    timeframe = expand_tokens(str(task.get("timeframe", "{today_slash}")), run_date)
    prompt = expand_tokens(str(task.get("prompt", "Summarize key developments.")), run_date)

    max_files = int(task.get("max_files", 200))
    max_chars_per_file = int(task.get("max_chars_per_file", 6000))
    max_total_chars = int(task.get("max_total_chars", 180000))
    llm_timeout = int(task.get("llm_timeout", 90))

    if task_type == "basic":
        script = skills_root / "Gen2BasicAnalysis" / "gen2_basic_analysis.py"
    elif task_type == "csv":
        script = skills_root / "Gen2CsvAnalysis" / "gen2_csv_analysis.py"
    elif task_type == "report":
        script = skills_root / "Gen2ReportAnalysis" / "gen2_report_analysis.py"
    else:
        raise ValueError(f"Task '{task_name}' has unsupported type '{task_type}'")

    cmd = [
        python_exe,
        str(script),
        domain,
        "--timeframe",
        timeframe,
        "--prompt",
        prompt,
        "--max-files",
        str(max_files),
        "--max-chars-per-file",
        str(max_chars_per_file),
        "--max-total-chars",
        str(max_total_chars),
        "--llm-timeout",
        str(llm_timeout),
    ]

    if dry_run:
        return {
            "name": task_name,
            "type": task_type,
            "domain": domain,
            "command": cmd,
            "status": "dry_run",
        }

    context_label = f"file={config_name} section={section_index} task={task_name}"
    print(f"[analysis:start] {context_label} type={task_type} domain={domain}", flush=True)
    print(f"[analysis:command] {' '.join(cmd)}", flush=True)
    stall_timeout_sec = max(30, int(task.get("stall_timeout_sec", max(120, llm_timeout * 2))))
    rc, stdout_raw, stderr_raw, duration = run_subprocess_with_streaming(
        cmd=cmd,
        context_label=context_label,
        stall_timeout_sec=stall_timeout_sec,
    )
    stdout = stdout_raw.strip()
    stderr = stderr_raw.strip()
    parsed = parse_json_from_output(stdout)

    status = "ok" if rc == 0 else "error"
    result = {
        "name": task_name,
        "type": task_type,
        "domain": domain,
        "command": cmd,
        "exit_code": rc,
        "duration_sec": round(duration, 3),
        "status": status,
        "result": parsed,
        "stderr": stderr,
    }
    print(
        f"[analysis:end] {context_label} status={status} rc={rc} duration_sec={duration:.1f}",
        flush=True,
    )
    return result


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

    print(
        f"[analysis:config:start] file={config_path.name} tasks_total={summary['tasks_total']} cadence={args.cadence}",
        flush=True,
    )

    for section_index, task in enumerate(config.get("tasks", []), start=1):
        if not isinstance(task, dict):
            summary["tasks_skipped"] += 1
            summary["results"].append({"status": "skipped", "reason": "task entry must be object"})
            print(
                f"[analysis:section:skip] file={config_path.name} section={section_index} reason=task_entry_must_be_object",
                flush=True,
            )
            continue

        section_name = str(task.get("name", "Unnamed Task")).strip() or "Unnamed Task"

        due, reason = task_is_due(task, run_date=run_date, cadence_filter=args.cadence)
        if not due:
            summary["tasks_skipped"] += 1
            summary["results"].append(
                {
                    "name": section_name,
                    "status": "skipped",
                    "reason": reason,
                }
            )
            print(
                f"[analysis:section:skip] file={config_path.name} section={section_index} name={section_name} reason={reason}",
                flush=True,
            )
            continue

        summary["tasks_due"] += 1

        if args.max_tasks > 0 and summary["tasks_executed"] >= args.max_tasks:
            summary["tasks_skipped"] += 1
            summary["results"].append(
                {
                    "name": section_name,
                    "status": "skipped",
                    "reason": "max_tasks cap reached",
                }
            )
            print(
                f"[analysis:section:skip] file={config_path.name} section={section_index} name={section_name} reason=max_tasks_cap_reached",
                flush=True,
            )
            continue

        print(
            f"[analysis:section:start] file={config_path.name} section={section_index} name={section_name}",
            flush=True,
        )

        try:
            result = run_task(
                task=task,
                default_domain=default_domain,
                skills_root=skills_root,
                python_exe=python_exe,
                dry_run=args.dry_run,
                run_date=run_date,
                config_name=config_path.name,
                section_index=section_index,
            )
            summary["results"].append(result)
            summary["tasks_executed"] += 1
            if result.get("status") == "error":
                summary["tasks_failed"] += 1
            section_rc = result.get("exit_code", "n/a")
            print(
                f"[analysis:section:end] file={config_path.name} section={section_index} name={section_name} status={result.get('status')} rc={section_rc}",
                flush=True,
            )
        except Exception as exc:
            summary["tasks_executed"] += 1
            summary["tasks_failed"] += 1
            summary["results"].append(
                {
                    "name": section_name,
                    "status": "error",
                    "error": str(exc),
                }
            )
            print(
                f"[analysis:section:end] file={config_path.name} section={section_index} name={section_name} status=error error={exc}",
                flush=True,
            )

    if summary["tasks_failed"] > 0:
        summary["status"] = "partial_error"

    print(
        f"[analysis:config:end] file={config_path.name} status={summary['status']} due={summary['tasks_due']} executed={summary['tasks_executed']} failed={summary['tasks_failed']} skipped={summary['tasks_skipped']}",
        flush=True,
    )

    exit_code = 0 if summary["tasks_failed"] == 0 else 1
    return summary, exit_code


def discover_config_files(base_config_path: Path) -> list[Path]:
    config_dir = base_config_path.parent
    all_candidates = sorted(config_dir.glob("gen2_analysis_schedule*_config.json"))
    excluded = {
        "gen2_analysis_schedule_config.json",
    }
    selected = [path.resolve() for path in all_candidates if path.name not in excluded]
    if base_config_path.resolve() not in selected:
        selected.append(base_config_path.resolve())
        selected.sort()
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Run recurring analysis tasks from JSON config")
    parser.add_argument("--config", default="gen2_analysis_schedule_config.json", help="Path to task config JSON")
    parser.add_argument("--cadence", default="daily", choices=["daily", "monthly", "all"])
    parser.add_argument("--date", default="", help="Run date in YYYY-MM-DD (default today)")
    parser.add_argument("--dry-run", action="store_true", help="Plan tasks without executing")
    parser.add_argument("--max-tasks", type=int, default=0, help="Optional execution cap")
    parser.add_argument(
        "--all-configs",
        action="store_true",
        help="Run all gen2_analysis_schedule*_config.json files in the config directory",
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
        print(
            f"[analysis:all-configs] index={index + 1}/{len(config_paths)} file={config_path.name}",
            flush=True,
        )
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
