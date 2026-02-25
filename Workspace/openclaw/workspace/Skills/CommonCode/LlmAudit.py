from __future__ import annotations

import datetime as dt
import json
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _log_file() -> Path:
    path = _repo_root() / "logs" / "llm_invocation_audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _normalize_prompt(prompt: str, max_chars: int = 500) -> tuple[str, int]:
    full = (prompt or "").replace("\r\n", "\n").replace("\r", "\n")
    clipped = full[:max_chars]
    return clipped, len(full)


def audit_llm_invocation(
    *,
    source: str,
    reason: str,
    prompt: str,
    model: str,
    endpoint: str,
    domain: str | None = None,
    timeframe: str | None = None,
    request_kind: str = "primary",
) -> Path:
    preview, total_chars = _normalize_prompt(prompt, max_chars=500)
    entry = {
        "ts_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": source,
        "request_kind": request_kind,
        "reason": reason,
        "model": model,
        "endpoint": endpoint,
        "domain": domain,
        "timeframe": timeframe,
        "prompt_preview": preview,
        "prompt_preview_chars": len(preview),
        "prompt_total_chars": total_chars,
    }
    log_path = _log_file()
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(
        f"[llm:audit] source={source} kind={request_kind} reason={reason} "
        f"model={model} prompt_preview_chars={len(preview)} log={log_path}",
        flush=True,
    )
    return log_path
