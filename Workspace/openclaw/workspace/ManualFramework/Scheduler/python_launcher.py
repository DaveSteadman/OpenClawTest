#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ActiveTask:
	task_id: str
	process: subprocess.Popen
	started_at_monotonic: float
	started_at_utc: str
	timeout_sec: int
	stdout_path: Path
	stderr_path: Path
	command: list[str]
	cwd: Path


def utc_now() -> dt.datetime:
	return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def utc_now_str() -> str:
	return utc_now().isoformat().replace("+00:00", "Z")


def timestamp_slug() -> str:
	return utc_now().strftime("%Y%m%d_%H%M%SZ")


def read_json(path: Path) -> dict[str, Any]:
	payload = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(payload, dict):
		raise ValueError("Runbook root must be a JSON object")
	return payload


def ensure_list_of_strings(value: Any, field_name: str) -> list[str]:
	if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
		raise ValueError(f"'{field_name}' must be an array of strings")
	return value


def tail_last_line(path: Path, max_bytes: int = 4096) -> str:
	try:
		if not path.exists() or not path.is_file():
			return ""
		file_size = path.stat().st_size
		if file_size <= 0:
			return ""
		with path.open("rb") as handle:
			if file_size > max_bytes:
				handle.seek(file_size - max_bytes)
			chunk = handle.read().decode("utf-8", errors="replace")
		for line in reversed(chunk.splitlines()):
			candidate = line.strip()
			if candidate:
				return candidate[:300]
	except Exception:
		return ""
	return ""


def get_ollama_ps_summary() -> str:
	try:
		proc = subprocess.run(
			["ollama", "ps"],
			capture_output=True,
			text=True,
			check=False,
			timeout=4,
		)
		output = (proc.stdout or "").strip()
		if proc.returncode != 0 or not output:
			return ""
		lines = [line.rstrip() for line in output.splitlines() if line.strip()]
		if len(lines) < 2:
			return ""

		headers = lines[0].split()
		if "CONTEXT" not in headers:
			return ""
		context_idx = headers.index("CONTEXT")
		until_idx = headers.index("UNTIL") if "UNTIL" in headers else -1

		model_line = lines[1].split()
		if len(model_line) <= context_idx:
			return ""
		model_name = model_line[0]
		processor = model_line[3] if len(model_line) > 3 else ""
		context = model_line[context_idx]
		until = ""
		if until_idx >= 0 and len(model_line) > until_idx:
			until = " ".join(model_line[until_idx:])

		text = f"model={model_name}"
		if processor:
			text += f" processor={processor}"
		text += f" context={context}"
		if until:
			text += f" until={until}"
		return text
	except Exception:
		return ""


def wait_for_tcp(host: str, port: int, timeout_sec: int) -> bool:
	end = time.time() + max(1, timeout_sec)
	while time.time() < end:
		try:
			with socket.create_connection((host, port), timeout=1.0):
				return True
		except OSError:
			time.sleep(0.25)
	return False


def load_runbook(config_path: Path) -> dict[str, Any]:
	runbook = read_json(config_path)
	runbook.setdefault("defaults", {})
	runbook.setdefault("startup", [])
	runbook.setdefault("shutdown", [])
	runbook.setdefault("tasks", [])
	runbook.setdefault("scheduler", {})

	if not isinstance(runbook["startup"], list):
		raise ValueError("'startup' must be an array")
	if not isinstance(runbook["shutdown"], list):
		raise ValueError("'shutdown' must be an array")
	if not isinstance(runbook["tasks"], list):
		raise ValueError("'tasks' must be an array")
	if not isinstance(runbook["defaults"], dict):
		raise ValueError("'defaults' must be an object")
	if not isinstance(runbook["scheduler"], dict):
		raise ValueError("'scheduler' must be an object")

	return runbook


class Launcher:
	def __init__(self, config_path: Path, dry_run: bool = False):
		self.config_path = config_path.resolve()
		self.config_dir = self.config_path.parent
		self.workspace_root = self.config_dir.parent.parent.parent
		self.dry_run = dry_run

		self.runbook = load_runbook(self.config_path)
		self.defaults = self.runbook.get("defaults", {})
		self.scheduler_cfg = self.runbook.get("scheduler", {})

		default_log_dir = self.defaults.get("log_dir", "runs")
		self.run_root = (self.config_dir / str(default_log_dir) / timestamp_slug()).resolve()
		self.run_root.mkdir(parents=True, exist_ok=True)

		self.managed_startups: dict[str, subprocess.Popen] = {}
		self.task_next_due: dict[str, float] = {}
		self.active_task: ActiveTask | None = None
		self.stop_requested = False
		self.status_interval_sec = max(1, int(self.scheduler_cfg.get("status_interval_sec", 10)))
		self._last_status_emit_monotonic = 0.0
		self._last_stdout_bytes = 0
		self._last_stderr_bytes = 0
		self._last_heartbeat_task_id = ""

		self.summary: dict[str, Any] = {
			"started_at": utc_now_str(),
			"config_path": str(self.config_path),
			"dry_run": self.dry_run,
			"startup": [],
			"tasks": [],
			"shutdown": [],
			"status": "running",
		}

	def _sep(self, label: str = "") -> None:
		line = "=" * 96
		if label:
			print(f"{line}\n{label}\n{line}")
			return
		print(line)

	def _token_values(self) -> dict[str, str]:
		today = dt.date.today()
		base_values: dict[str, str] = {
			"today_iso": today.isoformat(),
			"today_slash": today.strftime("%Y/%m/%d"),
			"workspace": str(self.workspace_root),
			"config_dir": str(self.config_dir),
			"python_executable": sys.executable,
		}
		values = dict(base_values)
		configured_python = self.defaults.get("python")
		if isinstance(configured_python, str) and configured_python.strip():
			resolved_python = configured_python.strip()
			for token_name, token_value in base_values.items():
				resolved_python = resolved_python.replace(f"{{{token_name}}}", token_value)
			values["python"] = resolved_python
		else:
			values["python"] = sys.executable
		return values

	def _expand(self, value: str) -> str:
		result = value
		for token_name, token_value in self._token_values().items():
			result = result.replace(f"{{{token_name}}}", token_value)
		return result

	def _action_env(self, extra_env: dict[str, Any] | None = None) -> dict[str, str]:
		base_env = dict(os.environ)
		defaults_env = self.defaults.get("env", {})
		if isinstance(defaults_env, dict):
			for key, value in defaults_env.items():
				if isinstance(key, str) and isinstance(value, str):
					base_env[key] = self._expand(value)
		if isinstance(extra_env, dict):
			for key, value in extra_env.items():
				if isinstance(key, str) and isinstance(value, str):
					base_env[key] = self._expand(value)
		return base_env

	def _action_cwd(self, cwd_value: Any) -> Path:
		if isinstance(cwd_value, str) and cwd_value.strip():
			candidate = Path(self._expand(cwd_value))
			if not candidate.is_absolute():
				candidate = self.config_dir / candidate
			return candidate.resolve()
		return self.config_dir

	def _require_existing_dir(self, path: Path, context: str) -> None:
		if not path.exists() or not path.is_dir():
			raise FileNotFoundError(f"{context} directory not found: {path}")

	def _command_resolve_details(self, cmd_expanded: list[str], cwd: Path) -> dict[str, Any]:
		exec_token = cmd_expanded[0] if cmd_expanded else ""
		exec_path: Path | None = None
		exec_exists = False

		if exec_token:
			exec_candidate = Path(exec_token)
			if exec_candidate.is_absolute():
				exec_path = exec_candidate
				exec_exists = exec_candidate.exists()
			elif any(sep in exec_token for sep in ("/", "\\")):
				exec_path = (cwd / exec_candidate).resolve()
				exec_exists = exec_path.exists()
			else:
				resolved = shutil.which(exec_token)
				if resolved:
					exec_path = Path(resolved)
					exec_exists = True

		script_path: Path | None = None
		script_exists: bool | None = None
		if len(cmd_expanded) >= 2 and cmd_expanded[1].lower().endswith(".py"):
			script_candidate = Path(cmd_expanded[1])
			if not script_candidate.is_absolute():
				script_candidate = (cwd / script_candidate).resolve()
			script_path = script_candidate
			script_exists = script_candidate.exists()

		return {
			"exec_token": exec_token,
			"exec_path": str(exec_path) if exec_path else "",
			"exec_exists": exec_exists,
			"script_path": str(script_path) if script_path else "",
			"script_exists": script_exists,
		}

	def _preflight_report(self) -> None:
		self._sep("[preflight] Resolved context")
		tokens = self._token_values()
		self._require_existing_dir(self.workspace_root, "workspace")
		self._require_existing_dir(self.config_dir, "config")
		print(f"[preflight] config_path={self.config_path}")
		print(f"[preflight] config_dir={self.config_dir}")
		print(f"[preflight] workspace={self.workspace_root}")
		print(f"[preflight] token {{workspace}} => {tokens['workspace']}")
		print(f"[preflight] token {{python}} => {tokens['python']}")
		defaults_env = self.defaults.get("env", {})
		if isinstance(defaults_env, dict):
			context_len = defaults_env.get("OLLAMA_CONTEXT_LENGTH")
			if context_len:
				print(f"[preflight] ollama context_length={context_len}")

		for index, action in enumerate(self.runbook.get("startup", []), start=1):
			if not isinstance(action, dict):
				continue
			action_id = str(action.get("id") or f"startup_{index}")
			cmd = ensure_list_of_strings(action.get("cmd"), f"startup[{index}].cmd")
			cmd_expanded = [self._expand(part) for part in cmd]
			cwd = self._action_cwd(action.get("cwd"))
			self._require_existing_dir(cwd, f"startup[{action_id}] cwd")
			details = self._command_resolve_details(cmd_expanded, cwd)
			print(f"[preflight] startup[{action_id}] cwd={cwd}")
			print(f"[preflight] startup[{action_id}] cmd={' '.join(cmd_expanded)}")
			if details["exec_path"]:
				print(f"[preflight] startup[{action_id}] executable={details['exec_path']} exists={details['exec_exists']}")

		for index, task in enumerate(self.runbook.get("tasks", []), start=1):
			if not isinstance(task, dict):
				continue
			task_id = str(task.get("id") or f"task_{index}")
			cmd = ensure_list_of_strings(task.get("cmd"), f"task[{task_id}].cmd")
			cmd_expanded = [self._expand(part) for part in cmd]
			cwd = self._action_cwd(task.get("cwd"))
			self._require_existing_dir(cwd, f"task[{task_id}] cwd")
			details = self._command_resolve_details(cmd_expanded, cwd)
			print(f"[preflight] task[{task_id}] cwd={cwd}")
			print(f"[preflight] task[{task_id}] cmd={' '.join(cmd_expanded)}")
			if details["exec_path"]:
				print(f"[preflight] task[{task_id}] executable={details['exec_path']} exists={details['exec_exists']}")
			if details["script_path"]:
				print(f"[preflight] task[{task_id}] script={details['script_path']} exists={details['script_exists']}")
				if details["script_exists"] is False:
					raise FileNotFoundError(f"Task script not found: {details['script_path']}")

		self._sep("[preflight] Complete")

	def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
		path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

	def _start_action(self, action: dict[str, Any], index: int) -> None:
		action_id = str(action.get("id") or f"startup_{index}")
		cmd = ensure_list_of_strings(action.get("cmd"), f"startup[{index}].cmd")
		cmd_expanded = [self._expand(part) for part in cmd]
		cwd = self._action_cwd(action.get("cwd"))
		self._require_existing_dir(cwd, f"startup[{action_id}] cwd")
		env = self._action_env(action.get("env") if isinstance(action.get("env"), dict) else None)
		background = bool(action.get("background", False))

		action_dir = self.run_root / "startup" / action_id
		action_dir.mkdir(parents=True, exist_ok=True)
		stdout_path = action_dir / "stdout.log"
		stderr_path = action_dir / "stderr.log"

		self._sep(f"[startup] {action_id}")
		print(f"[startup] command: {' '.join(cmd_expanded)}")
		print(f"[startup] cwd: {cwd}")
		if self.dry_run:
			self.summary["startup"].append(
				{
					"id": action_id,
					"status": "dry_run",
					"command": cmd_expanded,
					"cwd": str(cwd),
				}
			)
			return

		with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open("w", encoding="utf-8") as stderr_file:
			if background:
				process = subprocess.Popen(cmd_expanded, cwd=str(cwd), env=env, stdout=stdout_file, stderr=stderr_file)
				self.managed_startups[action_id] = process
				result: dict[str, Any] = {
					"id": action_id,
					"status": "started",
					"pid": process.pid,
					"command": cmd_expanded,
					"cwd": str(cwd),
				}
			else:
				started = time.monotonic()
				rc = subprocess.run(cmd_expanded, cwd=str(cwd), env=env, stdout=stdout_file, stderr=stderr_file).returncode
				result = {
					"id": action_id,
					"status": "ok" if rc == 0 else "error",
					"exit_code": rc,
					"duration_sec": round(time.monotonic() - started, 3),
					"command": cmd_expanded,
					"cwd": str(cwd),
				}

		wait_cfg = action.get("ready")
		if isinstance(wait_cfg, dict) and wait_cfg.get("type") == "tcp":
			host = str(wait_cfg.get("host", "127.0.0.1"))
			port = int(wait_cfg.get("port", 11434))
			timeout_sec = int(wait_cfg.get("timeout_sec", 20))
			ready = True if self.dry_run else wait_for_tcp(host=host, port=port, timeout_sec=timeout_sec)
			result["ready_check"] = {
				"type": "tcp",
				"host": host,
				"port": port,
				"timeout_sec": timeout_sec,
				"ready": ready,
			}
			if not ready:
				result["status"] = "error"

		self.summary["startup"].append(result)
		if result.get("status") == "error":
			raise RuntimeError(f"Startup action failed: {action_id}")

	def run_startup(self) -> None:
		for index, raw_action in enumerate(self.runbook.get("startup", []), start=1):
			if not isinstance(raw_action, dict):
				raise ValueError("Each startup action must be an object")
			self._start_action(raw_action, index)

	def init_task_schedule(self) -> None:
		now = time.monotonic()
		for index, raw_task in enumerate(self.runbook.get("tasks", []), start=1):
			if not isinstance(raw_task, dict):
				raise ValueError("Each task entry must be an object")
			task_id = str(raw_task.get("id") or f"task_{index}")
			start_in_sec = int(raw_task.get("start_in_sec", 0))
			self.task_next_due[task_id] = now + max(0, start_in_sec)

	def _task_timeout(self, task: dict[str, Any]) -> int:
		if "timeout_sec" in task:
			return max(1, int(task["timeout_sec"]))
		return max(1, int(self.defaults.get("timeout_sec", 3600)))

	def _start_task(self, task: dict[str, Any]) -> None:
		task_id = str(task.get("id"))
		command = ensure_list_of_strings(task.get("cmd"), f"task[{task_id}].cmd")
		command_expanded = [self._expand(part) for part in command]
		cwd = self._action_cwd(task.get("cwd"))
		self._require_existing_dir(cwd, f"task[{task_id}] cwd")
		env = self._action_env(task.get("env") if isinstance(task.get("env"), dict) else None)
		timeout_sec = self._task_timeout(task)

		log_dir = self.run_root / "tasks" / task_id / timestamp_slug()
		log_dir.mkdir(parents=True, exist_ok=True)
		stdout_path = log_dir / "stdout.log"
		stderr_path = log_dir / "stderr.log"
		(log_dir / "command.txt").write_text(" ".join(command_expanded) + "\n", encoding="utf-8")
		(log_dir / "cwd.txt").write_text(str(cwd) + "\n", encoding="utf-8")

		self._sep(f"[task:start] {task_id}")
		print(f"[task:start] command: {' '.join(command_expanded)}")
		print(f"[task:start] cwd: {cwd}")
		print(f"[task:start] timeout_sec: {timeout_sec}")
		if self.dry_run:
			self.summary["tasks"].append(
				{
					"id": task_id,
					"status": "dry_run",
					"command": command_expanded,
					"cwd": str(cwd),
					"started_at": utc_now_str(),
				}
			)
			return

		stdout_file = stdout_path.open("w", encoding="utf-8")
		stderr_file = stderr_path.open("w", encoding="utf-8")
		process = subprocess.Popen(
			command_expanded,
			cwd=str(cwd),
			env=env,
			stdout=stdout_file,
			stderr=stderr_file,
		)

		self.active_task = ActiveTask(
			task_id=task_id,
			process=process,
			started_at_monotonic=time.monotonic(),
			started_at_utc=utc_now_str(),
			timeout_sec=timeout_sec,
			stdout_path=stdout_path,
			stderr_path=stderr_path,
			command=command_expanded,
			cwd=cwd,
		)

	def _finish_active_task(self, timed_out: bool = False) -> None:
		if not self.active_task:
			return

		active = self.active_task
		process = active.process
		rc = process.poll()

		if timed_out and rc is None:
			process.terminate()
			try:
				process.wait(timeout=5)
			except subprocess.TimeoutExpired:
				process.kill()
			rc = process.poll()

		if rc is None:
			return

		duration = round(time.monotonic() - active.started_at_monotonic, 3)
		status = "timeout" if timed_out else ("ok" if rc == 0 else "error")

		self.summary["tasks"].append(
			{
				"id": active.task_id,
				"status": status,
				"exit_code": rc,
				"started_at": active.started_at_utc,
				"finished_at": utc_now_str(),
				"duration_sec": duration,
				"timeout_sec": active.timeout_sec,
				"command": active.command,
				"cwd": str(active.cwd),
				"stdout": str(active.stdout_path),
				"stderr": str(active.stderr_path),
			}
		)
		self._sep(f"[task:end] {active.task_id}")
		print(f"[task:end] rc={rc} status={status} duration={duration:.2f}s")
		print(f"[task:end] stdout={active.stdout_path}")
		print(f"[task:end] stderr={active.stderr_path}")
		self._emit_post_task_console_summary(active)

		self.active_task = None

	def _emit_post_task_console_summary(self, active: ActiveTask) -> None:
		try:
			if not active.stdout_path.exists():
				return
			lines = active.stdout_path.read_text(encoding="utf-8", errors="replace").splitlines()
		except Exception:
			return

		if active.task_id == "mine_all_configs_daily":
			prefixes = (
				"[miner:all-configs]",
				"[miner:config:start]",
				"[miner:section:attempt]",
				"[miner:section:skip]",
				"[miner:section:end]",
				"[miner:config:end]",
			)
			selected = [line for line in lines if line.startswith(prefixes)]
			if not selected:
				return
			self._sep("[task:detail] mine_all_configs_daily attempts")
			for line in selected:
				print(line)
			self._sep("[task:detail] end")

	def _due_task(self) -> dict[str, Any] | None:
		now = time.monotonic()
		due: list[tuple[float, dict[str, Any]]] = []
		for raw_task in self.runbook.get("tasks", []):
			if not isinstance(raw_task, dict):
				continue
			if not bool(raw_task.get("enabled", True)):
				continue
			task_id = str(raw_task.get("id"))
			due_time = self.task_next_due.get(task_id)
			if due_time is None:
				continue
			if now >= due_time:
				due.append((due_time, raw_task))

		if not due:
			return None

		due.sort(key=lambda item: item[0])
		return due[0][1]

	def _reschedule(self, task: dict[str, Any]) -> None:
		task_id = str(task.get("id"))
		every_sec = max(1, int(task.get("every_sec", 3600)))
		self.task_next_due[task_id] = time.monotonic() + every_sec

	def _check_for_quit(self) -> None:
		if os.name != "nt":
			return
		try:
			import msvcrt
		except Exception:
			return

		while msvcrt.kbhit():
			ch = msvcrt.getwch().lower()
			if ch == "q":
				self.stop_requested = True
				print("[control] Quit requested (q). No new tasks will start.")

	def _emit_heartbeat(self) -> None:
		now = time.monotonic()
		if now - self._last_status_emit_monotonic < self.status_interval_sec:
			return

		self._last_status_emit_monotonic = now
		if self.active_task:
			elapsed = now - self.active_task.started_at_monotonic
			process_state = "running" if self.active_task.process.poll() is None else "exited"
			stdout_bytes = 0
			stderr_bytes = 0
			stdout_age_sec = None
			stderr_age_sec = None
			try:
				if self.active_task.stdout_path.exists():
					stdout_stat = self.active_task.stdout_path.stat()
					stdout_bytes = int(stdout_stat.st_size)
					stdout_age_sec = round(time.time() - float(stdout_stat.st_mtime), 1)
			except Exception:
				pass
			try:
				if self.active_task.stderr_path.exists():
					stderr_stat = self.active_task.stderr_path.stat()
					stderr_bytes = int(stderr_stat.st_size)
					stderr_age_sec = round(time.time() - float(stderr_stat.st_mtime), 1)
			except Exception:
				pass

			stdout_age_text = "n/a" if stdout_age_sec is None else str(stdout_age_sec)
			stderr_age_text = "n/a" if stderr_age_sec is None else str(stderr_age_sec)
			if self._last_heartbeat_task_id != self.active_task.task_id:
				self._last_stdout_bytes = 0
				self._last_stderr_bytes = 0
				self._last_heartbeat_task_id = self.active_task.task_id
			stdout_delta = stdout_bytes - self._last_stdout_bytes
			stderr_delta = stderr_bytes - self._last_stderr_bytes
			self._last_stdout_bytes = stdout_bytes
			self._last_stderr_bytes = stderr_bytes
			stdout_tail = tail_last_line(self.active_task.stdout_path)
			stderr_tail = tail_last_line(self.active_task.stderr_path)
			print(
				f"[heartbeat] task={self.active_task.task_id} pid={self.active_task.process.pid} state={process_state} "
				f"elapsed_sec={elapsed:.1f}/{self.active_task.timeout_sec} stop_requested={self.stop_requested} "
				f"stdout_delta={stdout_delta}B stdout_age_sec={stdout_age_text} "
				f"stderr_delta={stderr_delta}B stderr_age_sec={stderr_age_text}"
			)
			if stdout_tail:
				print(f"[heartbeat] stdout: {stdout_tail}")
			if stderr_tail:
				print(f"[heartbeat] stderr: {stderr_tail}")
			ollama_summary = get_ollama_ps_summary()
			if ollama_summary:
				print(f"[heartbeat] ollama: {ollama_summary}")
			return

		next_due: tuple[str, float] | None = None
		for task_id, due_time in self.task_next_due.items():
			remaining = max(0.0, due_time - now)
			if next_due is None or remaining < next_due[1]:
				next_due = (task_id, remaining)

		if next_due:
			print(
				f"[heartbeat] idle next_task={next_due[0]} in_sec={next_due[1]:.1f} "
				f"stop_requested={self.stop_requested}"
			)
		else:
			print(f"[heartbeat] idle no_tasks_scheduled stop_requested={self.stop_requested}")

	def run_tasks_loop(self) -> None:
		self.init_task_schedule()
		if self.dry_run:
			print("[control] Dry-run mode: planning one pass of all enabled tasks.")
			for task in self.runbook.get("tasks", []):
				if not isinstance(task, dict):
					continue
				if not bool(task.get("enabled", True)):
					continue
				self._start_task(task)
			return

		poll_interval = max(0.2, float(self.scheduler_cfg.get("poll_interval_sec", 1.0)))

		self._sep("[control] Runtime")
		print("[control] Scheduler is running. Press 'q' to begin shutdown.")
		print(f"[control] status heartbeat every {self.status_interval_sec} seconds")
		while True:
			self._check_for_quit()
			self._emit_heartbeat()

			if self.active_task:
				elapsed = time.monotonic() - self.active_task.started_at_monotonic
				timed_out = elapsed > self.active_task.timeout_sec
				self._finish_active_task(timed_out=timed_out)

			if self.stop_requested and not self.active_task:
				break

			if not self.active_task and not self.stop_requested:
				task = self._due_task()
				if task is not None:
					self._start_task(task)
					self._reschedule(task)

			time.sleep(poll_interval)

	def run_shutdown(self) -> None:
		self._sep("[shutdown] Begin")
		for index, action in enumerate(self.runbook.get("shutdown", []), start=1):
			if not isinstance(action, dict):
				raise ValueError("Each shutdown action must be an object")

			action_id = str(action.get("id") or f"shutdown_{index}")
			ref = str(action.get("ref", "")).strip()
			timeout_sec = max(1, int(action.get("timeout_sec", 5)))

			if self.dry_run:
				self.summary["shutdown"].append({"id": action_id, "status": "dry_run", "ref": ref})
				continue

			if ref and ref in self.managed_startups:
				process = self.managed_startups[ref]
				status = "ok"
				if process.poll() is None:
					process.terminate()
					try:
						process.wait(timeout=timeout_sec)
					except subprocess.TimeoutExpired:
						process.kill()
						status = "killed"
				self.summary["shutdown"].append(
					{
						"id": action_id,
						"status": status,
						"ref": ref,
						"pid": process.pid,
						"exit_code": process.poll(),
					}
				)
				self._sep(f"[shutdown] {action_id}")
				print(f"[shutdown] stopped {ref} (pid={process.pid})")
				continue

			cmd = action.get("cmd")
			if cmd is not None:
				cmd_expanded = [self._expand(part) for part in ensure_list_of_strings(cmd, f"shutdown[{index}].cmd")]
				cwd = self._action_cwd(action.get("cwd"))
				self._require_existing_dir(cwd, f"shutdown[{action_id}] cwd")
				env = self._action_env(action.get("env") if isinstance(action.get("env"), dict) else None)
				self._sep(f"[shutdown] {action_id}")
				print(f"[shutdown] command: {' '.join(cmd_expanded)}")
				print(f"[shutdown] cwd: {cwd}")
				rc = subprocess.run(cmd_expanded, cwd=str(cwd), env=env).returncode
				self.summary["shutdown"].append(
					{"id": action_id, "status": "ok" if rc == 0 else "error", "exit_code": rc}
				)
				continue

			self.summary["shutdown"].append({"id": action_id, "status": "skipped", "reason": "no-op action"})

	def persist_summary(self, status: str) -> None:
		self.summary["finished_at"] = utc_now_str()
		self.summary["status"] = status
		self._write_json(self.run_root / "summary.json", self.summary)

	def run(self) -> int:
		overall_status = "ok"
		try:
			self._preflight_report()
			self.run_startup()
			self.run_tasks_loop()
		except KeyboardInterrupt:
			self.stop_requested = True
			print("[control] KeyboardInterrupt received. Shutting down.")
		except Exception as exc:
			overall_status = "error"
			self.summary["fatal_error"] = str(exc)
			print(f"[error] {exc}", file=sys.stderr)
		finally:
			try:
				self.run_shutdown()
			except Exception as exc:
				overall_status = "error"
				self.summary.setdefault("shutdown_error", str(exc))
				print(f"[shutdown:error] {exc}", file=sys.stderr)

			self.persist_summary(overall_status)
			print(f"[report] Summary written to: {self.run_root / 'summary.json'}")

		return 0 if overall_status == "ok" else 1


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Run scheduled Python tasks with startup/shutdown actions")
	parser.add_argument("--config", default="runbook.json", help="Path to runbook JSON")
	parser.add_argument("--dry-run", action="store_true", help="Print planned activity without executing")
	return parser.parse_args()


def main() -> int:
	args = parse_args()
	config_path = Path(args.config)
	if not config_path.is_absolute():
		config_path = Path.cwd() / config_path
	launcher = Launcher(config_path=config_path, dry_run=bool(args.dry_run))
	return launcher.run()


if __name__ == "__main__":
	raise SystemExit(main())
