#!/usr/bin/env python3
"""Gen2ReportAnalysis - Domain/timeframe LLM analysis with markdown report output."""

import argparse
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


def safe_name(text: str, fallback: str = "ReportAnalysis") -> str:
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


def normalize_heading(value: str, fallback: str = "Section") -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    text = re.sub(r"\s+", " ", text)
    return text[:120]


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


def call_llm_for_report(prompt_text: str, timeframe: Timeframe, domain: str, corpus_blocks, llm_timeout_seconds: int):
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for LLM analysis")

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    endpoint = f"{base_url}/chat/completions"

    corpus_text = "\n\n".join(item["text"] for item in corpus_blocks)

    system_prompt = (
        "You are a rigorous analyst producing a formal report structure. "
        "Return JSON only, no markdown fences, and no text outside JSON."
    )

    user_prompt = (
        f"Domain: {domain}\n"
        f"Timeframe: {timeframe.normalized}\n"
        f"Instruction: {prompt_text}\n\n"
        "Return strict JSON with top-level key 'sections'.\n"
        "'sections' must be an array of objects, where each object has:\n"
        "- title (string)\n"
        "- paragraphs (array of strings, each paragraph complete and report-style)\n\n"
        "Rules:\n"
        "- First section title must be exactly 'Introduction'.\n"
        "- Last section title must be exactly 'Summary'.\n"
        "- Include 3 to 8 total sections.\n"
        "- Do not include markdown headings in paragraph text.\n"
        "- Keep content evidence-based from dataset excerpts.\n\n"
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

    if not isinstance(parsed, dict):
        raise RuntimeError("LLM response must be a JSON object")

    return {
        "model": model,
        "endpoint": endpoint,
        "payload": parsed,
    }


def normalize_sections(raw_payload: dict) -> list[dict]:
    raw_sections = raw_payload.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise RuntimeError("LLM JSON must include non-empty 'sections' array")

    normalized = []
    for entry in raw_sections:
        if not isinstance(entry, dict):
            continue

        title = normalize_heading(entry.get("title", ""), fallback="Section")
        paragraphs_raw = entry.get("paragraphs")
        if isinstance(paragraphs_raw, list):
            paragraphs = [re.sub(r"\s+", " ", str(p or "")).strip() for p in paragraphs_raw if str(p or "").strip()]
        else:
            single = re.sub(r"\s+", " ", str(paragraphs_raw or "")).strip()
            paragraphs = [single] if single else []

        if not paragraphs:
            continue

        normalized.append({"title": title, "paragraphs": paragraphs})

    if not normalized:
        raise RuntimeError("LLM returned no valid sections")

    first_title = normalized[0]["title"].strip().lower()
    last_title = normalized[-1]["title"].strip().lower()

    if first_title != "introduction":
        normalized.insert(
            0,
            {
                "title": "Introduction",
                "paragraphs": [
                    "This report analyzes the selected domain and timeframe using the available mined source material and the provided prompt focus."
                ],
            },
        )

    if last_title != "summary":
        normalized.append(
            {
                "title": "Summary",
                "paragraphs": [
                    "Overall findings are constrained by the available source excerpts and should be interpreted with appropriate caution where data is sparse."
                ],
            }
        )

    normalized[0]["title"] = "Introduction"
    normalized[-1]["title"] = "Summary"

    if len(normalized) > 10:
        normalized = normalized[:9] + [normalized[-1]]
        normalized[0]["title"] = "Introduction"
        normalized[-1]["title"] = "Summary"

    return normalized


def render_markdown_report(domain: str, timeframe: Timeframe, prompt_text: str, sections: list[dict], input_files: list[str]) -> str:
    lines = []
    lines.append(f"# {domain} Report ({timeframe.normalized})")
    lines.append("")
    lines.append(f"Prompt focus: {prompt_text}")
    lines.append("")
    lines.append("## Table of Contents")
    lines.append("")

    for index, section in enumerate(sections, start=1):
        lines.append(f"{index}. {section['title']} .... paragraph {index}")

    lines.append("")
    for index, section in enumerate(sections, start=1):
        lines.append(f"## {index}. {section['title']}")
        lines.append("")
        for paragraph in section["paragraphs"]:
            lines.append(paragraph)
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("### Source Context")
    lines.append("")
    lines.append(f"- Domain: {domain}")
    lines.append(f"- Timeframe: {timeframe.normalized}")
    lines.append(f"- Source files used: {len(input_files)}")

    return "\n".join(lines).rstrip() + "\n"


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


def write_output(
    navigator: FolderNavigator,
    domain: str,
    timeframe: Timeframe,
    prompt_text: str,
    sections: list[dict],
    files: list[tuple[dt.date, Path]],
):
    out_dir = timeframe_output_dir(navigator, domain, timeframe)
    prompt_name = safe_name(prompt_text, fallback="ReportAnalysis")
    scope_token = timeframe.normalized.replace("/", "-")
    out_path = out_dir / f"{prompt_name}_{scope_token}.md"

    markdown = render_markdown_report(
        domain=domain,
        timeframe=timeframe,
        prompt_text=prompt_text,
        sections=sections,
        input_files=[str(item[1]) for item in files],
    )

    out_path.write_text(markdown, encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="LLM report analysis over mined domain logs across timeframe")
    parser.add_argument("domain", help="Domain name (alphabetic only)")
    parser.add_argument("--timeframe", required=True, help="YYYY or YYYY/MM or YYYY/MM/DD")
    parser.add_argument("--prompt", required=True, help="LLM report analysis instruction")
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

        llm_result = call_llm_for_report(
            prompt_text=prompt_text,
            timeframe=timeframe,
            domain=domain,
            corpus_blocks=corpus_blocks,
            llm_timeout_seconds=args.llm_timeout,
        )

        sections = normalize_sections(llm_result["payload"])

        out_path = write_output(
            navigator=navigator,
            domain=domain,
            timeframe=timeframe,
            prompt_text=prompt_text,
            sections=sections,
            files=files,
        )

        print(
            json.dumps(
                {
                    "domain": domain,
                    "timeframe": timeframe.normalized,
                    "files_analyzed": len(corpus_blocks),
                    "sections": len(sections),
                    "output_path": str(out_path),
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
