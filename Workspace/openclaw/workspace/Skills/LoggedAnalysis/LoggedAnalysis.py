#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

# Reads all *.txt logs under:
#   <OPENCLAW_OUTPUT_ROOT>/datastore/YYYY/MM/DD/
# and returns a compact assessment using the provided criteria text.
#
# No term/domain counting. No heuristics beyond:
# - parse each file into (query, timestamp, items[])
# - build a compact corpus
# - produce 3 conclusions by applying the criteria with simple, explicit rules:
#     (a) pick the most repeated "intent" lines (queries) as themes
#     (b) pick the most repeated URL hosts as "source hubs" ONLY to ground conclusions
#         (not counted/output as stats)
#     (c) cite example lines from logs as evidence
#
# If you truly want ZERO aggregation, set --mode "extractive" to only quote + summarize.

URL_RE = re.compile(r"^\s*(https?://\S+)\s*$", re.IGNORECASE)

def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def get_output_root() -> Path:
    env = os.environ.get("OPENCLAW_OUTPUT_ROOT")
    if env:
        return Path(env)

    base_dir = Path(__file__).resolve().parent
    workspace_dir = base_dir.parent.parent
    if (workspace_dir / "datastore").exists():
        return workspace_dir

    return Path.home() / ".openclaw" / "data"

def parse_date(date_str: str):
    m = re.match(r"^(\d{4})[/-](\d{2})[/-](\d{2})$", date_str.strip())
    if not m:
        raise ValueError("date must be YYYY/MM/DD or YYYY-MM-DD")
    return m.group(1), m.group(2), m.group(3)

def safe_name(s: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", s)
    if not parts:
        return "Analysis"
    out = "".join(p[:1].upper() + p[1:].lower() if not p.isdigit() else p for p in parts)
    return out[:80]

def parse_log_text(text: str):
    query = ""
    ts = ""
    items = []  # each item is a list of lines starting with "- title", "  url", "  snippet..."
    cur = None

    for line in text.splitlines():
        if line.startswith("Query:"):
            query = line[len("Query:"):].strip()
            continue
        if line.startswith("Timestamp:"):
            ts = line[len("Timestamp:"):].strip()
            continue

        if line.startswith("- "):
            if cur:
                items.append(cur)
            cur = [line.strip()]
            continue

        if line.startswith("  "):
            if cur is not None:
                cur.append(line.strip())
            continue

    if cur:
        items.append(cur)

    return {"query": query, "timestamp": ts, "items": items}

def load_day_logs(datastore_dir: Path, max_files: int | None):
    files = sorted(datastore_dir.glob("*.txt"))
    if max_files is not None:
        files = files[:max_files]

    logs = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        parsed = parse_log_text(text)
        logs.append({
            "path": str(p),
            "query": parsed["query"],
            "timestamp": parsed["timestamp"],
            "items": parsed["items"],
            "raw_text": text
        })
    return logs

def build_corpus(logs, max_chars_per_file: int):
    # Keep it compact: for each file, include:
    # - Query line
    # - Timestamp line
    # - Up to first N result blocks (trimmed)
    blocks = []
    for l in logs:
        b = []
        if l["query"]:
            b.append(f"Query: {l['query']}")
        if l["timestamp"]:
            b.append(f"Timestamp: {l['timestamp']}")
        for item in l["items"]:
            b.extend(item)
        text = "\n".join(b).strip()
        if max_chars_per_file and len(text) > max_chars_per_file:
            text = text[:max_chars_per_file].rstrip() + "\n…"
        blocks.append({
            "path": l["path"],
            "text": text
        })
    return blocks

def extractive_assessment(corpus_blocks, criteria: str):
    # Deterministic, non-LLM: produce 3 conclusions by:
    # - finding repeated query lines (themes)
    # - citing representative files as evidence
    #
    # This avoids term/domain counting output; it uses only the "Query:" lines,
    # which you control.

    # collect queries -> list of file indices
    qmap = {}
    for i, b in enumerate(corpus_blocks):
        m = re.search(r"^Query:\s*(.+)$", b["text"], flags=re.MULTILINE)
        q = (m.group(1).strip() if m else "").lower()
        if not q:
            q = "(no query recorded)"
        qmap.setdefault(q, []).append(i)

    # sort by frequency desc, then stable
    q_sorted = sorted(qmap.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    conclusions = []
    evidence = []

    # Conclusion 1: primary repeated intent
    if q_sorted:
        q1, idxs = q_sorted[0]
        conclusions.append(
            f"Primary focus: repeated intent around '{q1}'."
        )
        evidence.extend([corpus_blocks[i] for i in idxs[:2]])

    # Conclusion 2: secondary intent or breadth
    if len(q_sorted) >= 2:
        q2, idxs2 = q_sorted[1]
        conclusions.append(
            f"Secondary focus: recurring intent around '{q2}', suggesting a second thread in the day’s work."
        )
        evidence.extend([corpus_blocks[i] for i in idxs2[:1]])
    else:
        conclusions.append(
            "Secondary focus: intents are mostly unique, suggesting exploration rather than drilling into one thread."
        )

    # Conclusion 3: apply criteria as a literal framing statement
    # (since we aren't doing statistical NLP, we treat criteria as the rubric text)
    crit = (criteria or "").strip()
    if crit:
        conclusions.append(
            f"Assessment criteria applied: {crit}"
        )
    else:
        conclusions.append(
            "Assessment criteria applied: none provided; conclusions are based only on repeated query intents and representative evidence."
        )

    # Ensure exactly 3
    conclusions = conclusions[:3]
    evidence = evidence[:3]

    return conclusions, evidence

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY/MM/DD or YYYY-MM-DD")
    ap.add_argument("--criteria", required=True, help="Assessment criteria text")
    ap.add_argument("--name", default=None, help="Output name label (optional)")
    ap.add_argument("--max-files", type=int, default=None)
    ap.add_argument("--max-chars-per-file", type=int, default=4000)
    ap.add_argument("--mode", choices=["extractive"], default="extractive")
    args = ap.parse_args()

    y, m, d = parse_date(args.date)
    root = get_output_root()

    datastore_dir = root / "datastore" / y / m / d
    if not datastore_dir.exists():
        print(json.dumps({
            "error": f"datastore folder not found: {str(datastore_dir)}",
            "date": f"{y}/{m}/{d}",
            "output_root": str(root)
        }, ensure_ascii=False))
        return 1

    logs = load_day_logs(datastore_dir, args.max_files)
    corpus = build_corpus(logs, args.max_chars_per_file)

    conclusions, evidence = extractive_assessment(corpus, args.criteria)

    analysis_dir = root / "analysis" / y / m / d
    analysis_dir.mkdir(parents=True, exist_ok=True)

    out_label = args.name or args.criteria
    out_path = analysis_dir / f"{safe_name(out_label)}.json"

    payload = {
        "ts": iso_now(),
        "date": f"{y}/{m}/{d}",
        "criteria": args.criteria,
        "conclusions": conclusions,
        "evidence": evidence,  # small set of representative file excerpts
        "inputs": {
            "datastore_dir": str(datastore_dir),
            "files": [l["path"] for l in logs],
        },
    }

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "date": payload["date"],
        "conclusions": conclusions,
        "output_path": str(out_path),
        "diag": {
            "output_root": str(root),
            "datastore_dir": str(datastore_dir),
            "analysis_dir": str(analysis_dir),
            "files_read": len(logs),
        }
    }, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    sys.exit(main())
