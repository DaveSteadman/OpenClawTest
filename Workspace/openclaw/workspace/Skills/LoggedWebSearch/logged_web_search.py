#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DDG_HTML = "https://duckduckgo.com/html/?q={q}"

REDIRECT_RE = re.compile(r"/l/\?uddg=([^&\"'>]+)")
A_TAG_RE = re.compile(
    r"<a[^>]+class=\"result__a\"[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
SNIPPET_RE = re.compile(
    r"class=\"result__snippet\"[^>]*>(.*?)</(?:a|div)>",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")


def html_unescape(s: str) -> str:
    return (
        s.replace("&amp;", "&")
        .replace("&quot;", "\"")
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


def strip_tags(s: str) -> str:
    s = TAG_RE.sub("", s)
    return html_unescape(s).strip()


def resolve_ddg_redirect(url: str) -> str:
    m = REDIRECT_RE.search(url)
    if m:
        return urllib.parse.unquote(m.group(1))
    return url


def fetch_html(query: str, timeout_s: int) -> str:
    q = urllib.parse.quote_plus(query)
    url = DDG_HTML.format(q=q)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; OpenClawSkill/1.0)",
            "Accept": "text/html",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = resp.read()
    return data.decode("utf-8", errors="replace")


def parse_results(html: str, max_results: int):
    anchors = list(A_TAG_RE.finditer(html))
    snippets = list(SNIPPET_RE.finditer(html))

    results = []
    for i, a in enumerate(anchors):
        if len(results) >= max_results:
            break

        href = a.group(1)
        title = strip_tags(a.group(2))
        url = resolve_ddg_redirect(href)

        snippet = ""
        if i < len(snippets):
            snippet = strip_tags(snippets[i].group(1))

        if url.startswith("/"):
            continue

        results.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "rank": len(results) + 1,
            }
        )
    return results


def to_camel_case(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", query)
    if not tokens:
        return "Search"

    parts = []
    for token in tokens:
        if token.isdigit():
            parts.append(token)
        else:
            parts.append(token[:1].upper() + token[1:].lower())

    name = "".join(parts)
    return name[:80]


def get_output_root() -> str:
    env = os.environ.get("OPENCLAW_OUTPUT_ROOT")
    if env:
        return env

    home = Path.home()
    return str(home / ".openclaw" / "data")


def write_log(output_root: str, query: str, results) -> str:
    now = dt.datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    day = now.strftime("%d")
    name = to_camel_case(query)

    log_dir = os.path.join(output_root, "datastore", year, month, day)
    os.makedirs(log_dir, exist_ok=True)

    log_path = os.path.join(log_dir, f"{name}.txt")

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"Query: {query}\n")
        f.write(f"Timestamp: {now.isoformat(timespec='seconds')}\n")
        for item in results:
            title = item.get("title", "").strip()
            url = item.get("url", "").strip()
            snippet = item.get("snippet", "").strip()

            if title:
                f.write(f"- {title}\n")
            if url:
                f.write(f"  {url}\n")
            if snippet:
                f.write(f"  {snippet}\n")
        f.write("\n")

    return log_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--max", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--sleep-ms", type=int, default=0)
    args = ap.parse_args()

    if args.sleep_ms > 0:
        time.sleep(args.sleep_ms / 1000.0)

    output_root = get_output_root()

    try:
        html = fetch_html(args.query, args.timeout)
        results = parse_results(html, max(1, min(args.max, 25)))
        log_path = write_log(output_root, args.query, results)

        out = {
            "query": args.query,
            "results": results,
            "log_path": log_path,
            "diag": {
                "cwd": os.getcwd(),
                "__file__": os.path.abspath(__file__),
                "output_root": output_root,
            },
        }
        print(json.dumps(out, ensure_ascii=False))
        return 0

    except Exception as e:
        err = {
            "query": args.query,
            "error": str(e),
            "results": [],
            "diag": {
                "cwd": os.getcwd(),
                "__file__": os.path.abspath(__file__),
                "output_root": output_root,
            },
        }
        print(json.dumps(err, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
