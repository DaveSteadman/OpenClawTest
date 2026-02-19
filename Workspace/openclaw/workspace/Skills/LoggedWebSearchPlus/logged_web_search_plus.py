#!/usr/bin/env python3
"""DuckDuckGo Search Plus (Logged) - Search, follow result links, and log per-page summaries."""

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DDG_URL = "https://duckduckgo.com/html/?q={q}"

REDIRECT_PATTERN = re.compile(r"/l/\?uddg=([^&\"'>]+)")
ANCHOR_PATTERN = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
SNIPPET_PATTERN = re.compile(
    r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>',
    re.IGNORECASE | re.DOTALL,
)
TAG_PATTERN = re.compile(r"<[^>]+>")
SCRIPT_STYLE_PATTERN = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
WHITESPACE_PATTERN = re.compile(r"\s+")


def decode_html_entities(text):
    if not text:
        return ""
    return html.unescape(text)


def remove_html_tags(text):
    if not text:
        return ""
    cleaned = TAG_PATTERN.sub(" ", text)
    cleaned = decode_html_entities(cleaned)
    cleaned = WHITESPACE_PATTERN.sub(" ", cleaned)
    return cleaned.strip()


def decode_redirect_url(redirect_url):
    if not redirect_url:
        return ""
    match = REDIRECT_PATTERN.search(redirect_url)
    if match:
        try:
            return urllib.parse.unquote(match.group(1))
        except Exception:
            return redirect_url
    return redirect_url


def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
    }


def fetch_url_text(url, timeout_seconds):
    request = urllib.request.Request(url, headers=get_headers(), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            html_bytes = response.read()
            final_url = response.geturl()
        return html_bytes.decode("utf-8", errors="replace"), content_type, final_url
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {str(e.reason) if getattr(e, 'reason', None) else str(e)}")
    except Exception as e:
        raise RuntimeError(str(e))


def fetch_duckduckgo_html(query, timeout_seconds):
    if not query or not isinstance(query, str):
        raise ValueError("Query must be a non-empty string")

    encoded_query = urllib.parse.quote_plus(query)
    search_url = DDG_URL.format(q=encoded_query)
    html_text, _, _ = fetch_url_text(search_url, timeout_seconds)
    return html_text


def extract_results_from_html(html_text, max_count):
    if not html_text:
        return []

    results = []
    anchors = list(ANCHOR_PATTERN.finditer(html_text))
    snippets = list(SNIPPET_PATTERN.finditer(html_text))

    for index, anchor_match in enumerate(anchors):
        if len(results) >= max_count:
            break

        try:
            href = anchor_match.group(1)
            title_html = anchor_match.group(2)
            title = remove_html_tags(title_html)
            url = decode_redirect_url(href)

            if not title or not url or url.startswith("/"):
                continue

            snippet = ""
            if index < len(snippets):
                snippet = remove_html_tags(snippets[index].group(1))

            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "rank": len(results) + 1,
                }
            )
        except Exception:
            continue

    return results


def html_to_plain_text(html_text):
    if not html_text:
        return ""

    text = COMMENT_PATTERN.sub(" ", html_text)
    text = SCRIPT_STYLE_PATTERN.sub(" ", text)
    text = TAG_PATTERN.sub(" ", text)
    text = decode_html_entities(text)
    text = WHITESPACE_PATTERN.sub(" ", text)
    return text.strip()


def make_word_summary(text, target_words):
    if not text:
        return ""

    words = text.split()
    if len(words) <= target_words:
        return " ".join(words)
    return " ".join(words[:target_words])


def summarize_linked_page(url, timeout_seconds, target_words):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "", 0, "skipped: unsupported scheme"

    html_text, content_type, final_url = fetch_url_text(url, timeout_seconds)
    if content_type and "html" not in content_type:
        return "", 0, f"skipped: non-html ({content_type})"

    plain_text = html_to_plain_text(html_text)
    summary = make_word_summary(plain_text, target_words)
    word_count = len(summary.split()) if summary else 0
    if not summary:
        return "", 0, "error: empty extracted text"

    return summary, word_count, f"ok ({final_url})"


def enrich_results_with_page_text(results, page_timeout, words_per_page):
    enriched = []
    for result in results:
        entry = dict(result)
        url = entry.get("url", "")

        try:
            summary, word_count, status = summarize_linked_page(url, page_timeout, words_per_page)
            entry["page_summary"] = summary
            entry["page_words"] = word_count
            entry["page_status"] = status
        except Exception as e:
            entry["page_summary"] = ""
            entry["page_words"] = 0
            entry["page_status"] = f"error: {str(e)}"

        enriched.append(entry)

    return enriched


def query_to_filename(query):
    tokens = re.findall(r"[A-Za-z0-9]+", query or "")
    if not tokens:
        return "Search"

    parts = []
    for token in tokens:
        if token.isdigit():
            parts.append(token)
        else:
            parts.append(token[0].upper() + token[1:].lower())

    return "".join(parts)[:80]


def get_data_root():
    env_root = os.environ.get("OPENCLAW_OUTPUT_ROOT")
    if env_root:
        return env_root
    return str(Path.home() / ".openclaw" / "data")


def write_search_plus_log(data_root, query, results, words_per_page):
    now = dt.datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    day = now.strftime("%d")
    timestamp = now.isoformat(timespec="seconds")

    filename = query_to_filename(query)
    log_dir = os.path.join(data_root, "datastore", year, month, day)
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{filename}.txt")

    with open(log_file, "a", encoding="utf-8") as handle:
        handle.write(f"Query: {query}\n")
        handle.write(f"Timestamp: {timestamp}\n")
        handle.write(f"PerPageSummaryWords: {words_per_page}\n")

        for item in results:
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            snippet = (item.get("snippet") or "").strip()
            page_summary = (item.get("page_summary") or "").strip()
            page_words = item.get("page_words", 0)
            page_status = (item.get("page_status") or "").strip()

            if title:
                handle.write(f"- {title}\n")
            if url:
                handle.write(f"  {url}\n")
            if snippet:
                handle.write(f"  {snippet}\n")

            handle.write(f"  LinkedPageStatus: {page_status}\n")
            handle.write(f"  LinkedPageSummaryWords: {page_words}\n")

            if page_summary:
                handle.write("  LinkedPageSummary:\n")
                handle.write(f"  {page_summary}\n")

            handle.write("\n")

        handle.write("\n")

    return log_file


def main():
    parser = argparse.ArgumentParser(
        description="Search DuckDuckGo, follow each result link, and log short page summaries"
    )
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--max", type=int, default=8, help="Max results (1-25)")
    parser.add_argument("--timeout", type=int, default=20, help="Search timeout seconds (5-60)")
    parser.add_argument("--page-timeout", type=int, default=15, help="Page timeout seconds (5-60)")
    parser.add_argument("--words", type=int, default=200, help="Target words per linked page summary (80-400)")
    parser.add_argument("--sleep-ms", type=int, default=0, help="Optional sleep before search in milliseconds")

    try:
        args = parser.parse_args()
    except SystemExit:
        return 1

    query = args.query or ""
    if not query.strip():
        print(json.dumps({"query": query, "error": "Query must be non-empty", "results": [], "count": 0, "status": "error"}, ensure_ascii=False))
        return 1

    if args.sleep_ms > 0:
        time.sleep(args.sleep_ms / 1000.0)

    max_results = max(1, min(args.max, 25))
    timeout_seconds = max(5, min(args.timeout, 60))
    page_timeout = max(5, min(args.page_timeout, 60))
    words_per_page = max(80, min(args.words, 400))

    data_root = get_data_root()

    try:
        search_html = fetch_duckduckgo_html(query, timeout_seconds)
        base_results = extract_results_from_html(search_html, max_results)
        enriched_results = enrich_results_with_page_text(base_results, page_timeout, words_per_page)
        log_path = write_search_plus_log(data_root, query, enriched_results, words_per_page)

        response = {
            "query": query,
            "results": enriched_results,
            "log_path": log_path,
            "count": len(enriched_results),
            "status": "ok",
        }
        print(json.dumps(response, ensure_ascii=False))
        return 0
    except Exception as e:
        print(
            json.dumps(
                {
                    "query": query,
                    "error": str(e),
                    "results": [],
                    "count": 0,
                    "status": "error",
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
