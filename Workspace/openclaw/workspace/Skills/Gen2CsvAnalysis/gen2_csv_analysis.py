#!/usr/bin/env python3
"""Gen2CsvAnalysis - Domain/timeframe LLM analysis with CSV output."""

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

import requests

SKILLS_ROOT = Path(__file__).resolve().parent.parent
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from CommonCode.FolderNavigator import FolderNavigator


@dataclass(frozen=True)
class Timeframe:
    scope: str  # year|month|day
    year: int
    month: int | None
    day: int | None

    @property
    def normalized(self) -> str:
        if self.scope == "year":
            return f"{self.year:04d}"
        if self.scope == "month":
            return f"{self.year:04d}/{self.month:02d}"
        return f"{self.year:04d}/{self.month:02d}/{self.day:02d}"


def validate_domain(domain: str) -> str:
    if not domain or not isinstance(domain, str):
        raise ValueError("Domain must be a non-empty string")
    cleaned = domain.strip()
    if not re.fullmatch(r"[A-Za-z]+", cleaned):
        raise ValueError("Domain must be alphabetic only (A-Z, a-z)")
    return cleaned


def parse_timeframe(value: str) -> Timeframe:
    cleaned = (value or "").strip().replace("-", "/")
    if not cleaned:
        raise ValueError("Timeframe must be non-empty")

    parts = cleaned.split("/")
    if len(parts) not in (1, 2, 3):
        raise ValueError("Timeframe must be YYYY or YYYY/MM or YYYY/MM/DD")

    try:
        year = int(parts[0])
    except ValueError as exc:
        raise ValueError("Year must be numeric") from exc

    if len(parts) == 1:
        if year < 1900 or year > 2200:
            raise ValueError("Year out of supported range")
        return Timeframe(scope="year", year=year, month=None, day=None)

    try:
        month = int(parts[1])
    except ValueError as exc:
        raise ValueError("Month must be numeric") from exc

    if month < 1 or month > 12:
        raise ValueError("Month must be in range 01-12")

    if len(parts) == 2:
        return Timeframe(scope="month", year=year, month=month, day=None)

    try:
        day = int(parts[2])
        dt.date(year, month, day)
    except ValueError as exc:
        raise ValueError("Invalid day for given year/month") from exc

    return Timeframe(scope="day", year=year, month=month, day=day)


def safe_name(text: str, fallback: str = "CsvAnalysis") -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", text or "")
    if not tokens:
        return fallback
    parts = []
    for token in tokens:
        if token.isdigit():
            parts.append(token)
        else:
            parts.append(token[0].upper() + token[1:].lower())
    return "".join(parts)[:80]


def extract_date_from_mine_path(path: Path, mine_domain_root: Path) -> dt.date | None:
    try:
        rel = path.relative_to(mine_domain_root)
    except Exception:
        return None

    if len(rel.parts) < 4:
        return None

    year_part, month_part, day_part = rel.parts[0], rel.parts[1], rel.parts[2]
    if not (year_part.isdigit() and len(year_part) == 4):
        return None
    if not (month_part.isdigit() and len(month_part) == 2):
        return None
    if not (day_part.isdigit() and len(day_part) == 2):
        return None

    try:
        return dt.date(int(year_part), int(month_part), int(day_part))
    except ValueError:
        return None


def date_matches_timeframe(value: dt.date, timeframe: Timeframe) -> bool:
    if timeframe.scope == "year":
        return value.year == timeframe.year
    if timeframe.scope == "month":
        return value.year == timeframe.year and value.month == timeframe.month
    return value.year == timeframe.year and value.month == timeframe.month and value.day == timeframe.day


def collect_files(navigator: FolderNavigator, domain: str, timeframe: Timeframe, max_files: int) -> List[tuple[dt.date, Path]]:
    mine_domain_root = navigator.get_domain_root("mine", domain)
    if not mine_domain_root.exists():
        raise FileNotFoundError(f"Mine domain folder not found: {mine_domain_root}")

    matched = []
    for path in sorted(mine_domain_root.glob("**/*.txt")):
        date_value = extract_date_from_mine_path(path, mine_domain_root)
        if not date_value:
            continue
        if date_matches_timeframe(date_value, timeframe):
            matched.append((date_value, path))

    matched.sort(key=lambda item: (item[0], str(item[1]).lower()))
    if max_files > 0:
        matched = matched[:max_files]
    return matched


def build_corpus(files: List[tuple[dt.date, Path]], max_chars_per_file: int, max_total_chars: int):
    blocks = []
    total = 0

    for index, (date_value, path) in enumerate(files, start=1):
        try:
            raw = path.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            continue

        if max_chars_per_file > 0 and len(raw) > max_chars_per_file:
            raw = raw[:max_chars_per_file].rstrip() + "\n…"

        header = f"### File {index} | Date {date_value.isoformat()} | Name {path.name}"
        block = f"{header}\n{raw}".strip()

        next_total = total + len(block)
        if max_total_chars > 0 and next_total > max_total_chars:
            break

        blocks.append({"date": date_value.isoformat(), "path": str(path), "text": block})
        total = next_total

    return blocks


def sanitize_csv_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value).replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()
    return text


def normalize_table_payload(payload: dict) -> tuple[list[str], list[list[str]]]:
    if not isinstance(payload, dict):
        raise RuntimeError("LLM response must be a JSON object")

    columns_raw = payload.get("columns")
    rows_raw = payload.get("rows")

    if not isinstance(columns_raw, list) or not columns_raw:
        raise RuntimeError("LLM JSON must include non-empty 'columns' array")
    if not isinstance(rows_raw, list):
        raise RuntimeError("LLM JSON must include 'rows' array")

    columns = [sanitize_csv_cell(col) for col in columns_raw if sanitize_csv_cell(col)]
    if not columns:
        raise RuntimeError("LLM returned empty columns after normalization")

    normalized_rows: list[list[str]] = []
    for item in rows_raw:
        if isinstance(item, dict):
            row_values = [sanitize_csv_cell(item.get(col, "")) for col in columns]
        elif isinstance(item, list):
            row_values = [sanitize_csv_cell(item[i] if i < len(item) else "") for i in range(len(columns))]
        else:
            continue

        normalized_rows.append(row_values)

    if not normalized_rows:
        raise RuntimeError("LLM returned no valid row entries")

    return columns, normalized_rows


def call_llm_for_table(prompt_text: str, timeframe: Timeframe, domain: str, corpus_blocks, llm_timeout_seconds: int):
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for LLM analysis")

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    endpoint = f"{base_url}/chat/completions"

    corpus_text = "\n\n".join(item["text"] for item in corpus_blocks)

    system_prompt = (
        "You are a rigorous analyst that outputs tabular results for CSV export. "
        "Return JSON only with a stable table schema. "
        "No markdown fences and no extra commentary."
    )

    user_prompt = (
        f"Domain: {domain}\n"
        f"Timeframe: {timeframe.normalized}\n"
        f"Instruction: {prompt_text}\n\n"
        "Generate a CSV-ready table from the dataset excerpts.\n"
        "Return strict JSON with exactly these top-level keys:\n"
        "- columns: array of column names\n"
        "- rows: array of rows (either objects keyed by column names or arrays aligned to columns)\n"
        "- notes: short string describing assumptions (optional)\n\n"
        "Requirements:\n"
        "- Include meaningful headers that match the instruction.\n"
        "- Keep values concise and text-safe for CSV cells.\n"
        "- Do not include markdown, code fences, or prose outside JSON.\n\n"
        "Dataset excerpts:\n"
        f"{corpus_text}"
    )

    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    response = requests.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=max(30, llm_timeout_seconds),
    )
    response.raise_for_status()

    body = response.json()
    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("LLM returned empty response")

    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError("LLM response was not valid JSON") from exc

    columns, rows = normalize_table_payload(parsed)

    return {
        "model": model,
        "endpoint": endpoint,
        "table": {
            "columns": columns,
            "rows": rows,
            "notes": sanitize_csv_cell(parsed.get("notes", "")),
        },
    }


def timeframe_output_dir(navigator: FolderNavigator, domain: str, timeframe: Timeframe) -> Path:
    root = navigator.get_domain_root("analyse", domain, create=True)
    if timeframe.scope == "year":
        path = root / f"{timeframe.year:04d}"
    elif timeframe.scope == "month":
        path = root / f"{timeframe.year:04d}" / f"{timeframe.month:02d}"
    else:
        path = root / f"{timeframe.year:04d}" / f"{timeframe.month:02d}" / f"{timeframe.day:02d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_csv_output(
    navigator: FolderNavigator,
    domain: str,
    timeframe: Timeframe,
    prompt_text: str,
    table: dict,
) -> Path:
    out_dir = timeframe_output_dir(navigator, domain, timeframe)
    prompt_name = safe_name(prompt_text, fallback="CsvAnalysis")
    scope_token = timeframe.normalized.replace("/", "-")
    out_path = out_dir / f"{prompt_name}_{scope_token}.csv"

    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(table["columns"])
        writer.writerows(table["rows"])

    return out_path


def main():
    parser = argparse.ArgumentParser(description="LLM CSV analysis over mined domain logs across timeframe")
    parser.add_argument("domain", help="Domain name (alphabetic only)")
    parser.add_argument("--timeframe", required=True, help="YYYY or YYYY/MM or YYYY/MM/DD")
    parser.add_argument("--prompt", required=True, help="LLM CSV analysis instruction")
    parser.add_argument("--max-files", type=int, default=200)
    parser.add_argument("--max-chars-per-file", type=int, default=6000)
    parser.add_argument("--max-total-chars", type=int, default=180000)
    parser.add_argument("--llm-timeout", type=int, default=90)

    try:
        args = parser.parse_args()
    except SystemExit:
        return 1

    try:
        domain = validate_domain(args.domain)
        timeframe = parse_timeframe(args.timeframe)
        prompt_text = (args.prompt or "").strip()
        if not prompt_text:
            raise ValueError("Prompt must be non-empty")
    except Exception as exc:
        print(
            json.dumps(
                {
                    "domain": args.domain if hasattr(args, "domain") else "",
                    "timeframe": args.timeframe if hasattr(args, "timeframe") else "",
                    "error": str(exc),
                    "status": "error",
                },
                ensure_ascii=False,
            )
        )
        return 1

    navigator = FolderNavigator.from_fixed_point()

    try:
        files = collect_files(
            navigator=navigator,
            domain=domain,
            timeframe=timeframe,
            max_files=max(1, args.max_files),
        )
        if not files:
            raise FileNotFoundError(
                f"No input .txt files found for domain '{domain}' and timeframe '{timeframe.normalized}'"
            )

        corpus_blocks = build_corpus(
            files=files,
            max_chars_per_file=max(500, args.max_chars_per_file),
            max_total_chars=max(2000, args.max_total_chars),
        )
        if not corpus_blocks:
            raise RuntimeError("No readable corpus content after bounds were applied")

        llm_result = call_llm_for_table(
            prompt_text=prompt_text,
            timeframe=timeframe,
            domain=domain,
            corpus_blocks=corpus_blocks,
            llm_timeout_seconds=args.llm_timeout,
        )

        out_path = write_csv_output(
            navigator=navigator,
            domain=domain,
            timeframe=timeframe,
            prompt_text=prompt_text,
            table=llm_result["table"],
        )

        print(
            json.dumps(
                {
                    "domain": domain,
                    "timeframe": timeframe.normalized,
                    "files_analyzed": len(corpus_blocks),
                    "output_path": str(out_path),
                    "columns": llm_result["table"]["columns"],
                    "rows": len(llm_result["table"]["rows"]),
                    "status": "ok",
                },
                ensure_ascii=False,
            )
        )
        return 0

    except Exception as exc:
        print(
            json.dumps(
                {
                    "domain": domain,
                    "timeframe": timeframe.normalized,
                    "error": str(exc),
                    "status": "error",
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
