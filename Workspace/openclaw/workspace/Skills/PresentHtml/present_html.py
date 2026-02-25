#!/usr/bin/env python3

import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parent.parent
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from CommonCode.FolderNavigator import FolderNavigator


def validate_domain(domain: str) -> str:
    value = (domain or "").strip()
    if not value:
        raise ValueError("Domain must be a non-empty string")
    if not re.fullmatch(r"[A-Za-z]+", value):
        raise ValueError("Domain must be alphabetic only (A-Z, a-z)")
    return value


def parse_timeframe(value: str) -> dt.date:
    cleaned = (value or "").strip().replace("-", "/")
    parts = cleaned.split("/")
    if len(parts) != 3:
        raise ValueError("--timeframe must be YYYY/MM/DD or YYYY-MM-DD")
    year, month, day = (int(part) for part in parts)
    return dt.date(year, month, day)


def safe_name(text: str, fallback: str = "Presentation") -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", text or "")
    if not tokens:
        return fallback
    output = []
    for token in tokens:
        if token.isdigit():
            output.append(token)
        else:
            output.append(token[0].upper() + token[1:].lower())
    return "".join(output)[:80]


def resolve_analysis_day_dir(navigator: FolderNavigator, source_domain: str, as_of_date: dt.date) -> Path:
    root = navigator.get_domain_root("analyse", source_domain)
    day_dir = root / f"{as_of_date.year:04d}" / f"{as_of_date.month:02d}" / f"{as_of_date.day:02d}"
    if not day_dir.exists():
        raise FileNotFoundError(f"No analysis day folder found: {day_dir}")
    return day_dir


def parse_markdown_sections(markdown_text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_title = "Overview"
    current_lines: list[str] = []

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            if current_lines:
                sections.append((current_title, current_lines))
            current_title = line[3:].strip() or "Section"
            current_lines = []
            continue
        if line.startswith("# "):
            continue
        if line.startswith("-"):
            current_lines.append(line)
            continue
        if line:
            current_lines.append(line)

    if current_lines:
        sections.append((current_title, current_lines))

    if not sections:
        sections.append(("Overview", ["No sectioned content available."]))

    return sections


def render_html(title: str, source_domain: str, date_value: dt.date, sources: list[Path], sections: list[tuple[str, list[str]]]) -> str:
    source_items = "".join(
        f"<li>{html.escape(path.name)}</li>" for path in sources
    )

    section_blocks = []
    for section_title, lines in sections:
        if not lines:
            continue
        body_parts = []
        for line in lines:
            if line.startswith("-"):
                body_parts.append(f"<li>{html.escape(line.lstrip('-').strip())}</li>")
            else:
                body_parts.append(f"<p>{html.escape(line)}</p>")

        list_items = [item for item in body_parts if item.startswith("<li>")]
        para_items = [item for item in body_parts if item.startswith("<p>")]

        section_html = [
            "<section class=\"card\">",
            f"<h2>{html.escape(section_title)}</h2>",
        ]
        section_html.extend(para_items)
        if list_items:
            section_html.append("<ul>")
            section_html.extend(list_items)
            section_html.append("</ul>")
        section_html.append("</section>")
        section_blocks.append("\n".join(section_html))

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f7fb;
      --card: #ffffff;
      --ink: #0f172a;
      --muted: #475569;
      --brand: #0b5fff;
      --line: #e2e8f0;
    }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: Segoe UI, Arial, sans-serif; }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 28px; }}
    .hero {{ background: linear-gradient(135deg, #0b5fff, #1d4ed8); color: #fff; border-radius: 16px; padding: 28px; box-shadow: 0 12px 30px rgba(15,23,42,.18); }}
    .hero h1 {{ margin: 0 0 10px; font-size: 34px; line-height: 1.15; }}
    .meta {{ font-size: 14px; opacity: .95; }}
    .grid {{ display: grid; gap: 16px; margin-top: 18px; }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 18px; box-shadow: 0 6px 18px rgba(2,6,23,.06); }}
    h2 {{ margin: 0 0 10px; font-size: 22px; }}
    p {{ margin: 8px 0; color: var(--ink); line-height: 1.55; }}
    ul {{ margin: 8px 0 0 20px; color: var(--muted); }}
    li {{ margin: 6px 0; }}
    .sources {{ margin-top: 20px; background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 16px; }}
    .sources h3 {{ margin: 0 0 8px; font-size: 16px; color: var(--muted); }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <header class=\"hero\">
      <h1>{html.escape(title)}</h1>
      <div class=\"meta\">Domain: {html.escape(source_domain)} · Date: {date_value.isoformat()}</div>
    </header>
    <main class=\"grid\">{''.join(section_blocks)}</main>
    <aside class=\"sources\">
      <h3>Source files</h3>
      <ul>{source_items}</ul>
    </aside>
  </div>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a manager-ready HTML presentation from analysis markdown outputs")
    parser.add_argument("domain", help="Output domain (alphabetic only)")
    parser.add_argument("--timeframe", required=True, help="YYYY/MM/DD or YYYY-MM-DD")
    parser.add_argument("--source-domain", default="", help="Optional source analysis domain, defaults to domain")
    parser.add_argument("--title", default="", help="Optional presentation title")
    parser.add_argument("--max-files", type=int, default=4, help="Max analysis markdown files to include")

    try:
        args = parser.parse_args()
        output_domain = validate_domain(args.domain)
        source_domain = validate_domain((args.source_domain or "").strip() or output_domain)
        date_value = parse_timeframe(args.timeframe)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1

    navigator = FolderNavigator.from_fixed_point()

    try:
        day_dir = resolve_analysis_day_dir(navigator, source_domain, date_value)
        analysis_files = sorted(day_dir.glob("*.md"))[: max(1, args.max_files)]
        if not analysis_files:
            raise FileNotFoundError(f"No .md analysis files in {day_dir}")

        merged = "\n\n".join(path.read_text(encoding="utf-8", errors="replace") for path in analysis_files)
        sections = parse_markdown_sections(merged)

        present_root = navigator.get_domain_root("present", output_domain, create=True)
        out_dir = present_root / f"{date_value.year:04d}" / f"{date_value.month:02d}" / f"{date_value.day:02d}"
        out_dir.mkdir(parents=True, exist_ok=True)

        title = (args.title or "").strip() or f"{source_domain} Executive Brief"
        out_path = out_dir / f"{safe_name(title, fallback='ExecutiveBrief')}_{date_value.isoformat()}.html"
        out_path.write_text(render_html(title, source_domain, date_value, analysis_files, sections), encoding="utf-8")

        print(json.dumps({
            "status": "ok",
            "domain": output_domain,
            "source_domain": source_domain,
            "timeframe": date_value.strftime("%Y/%m/%d"),
            "analysis_files": [str(path) for path in analysis_files],
            "output_path": str(out_path),
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "domain": output_domain,
            "source_domain": source_domain,
            "timeframe": date_value.strftime("%Y/%m/%d"),
            "error": str(exc),
        }, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
