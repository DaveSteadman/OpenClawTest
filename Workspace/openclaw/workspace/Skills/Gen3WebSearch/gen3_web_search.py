#!/usr/bin/env python3
"""Gen3WebSearch - DuckDuckGo search + Gen3ReadWebpage-style LLM cleanup for linked pages."""

import argparse
import datetime as dt
import html
import json
import random
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parent.parent
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from CommonCode.FolderNavigator import FolderNavigator
from CommonCode.OllamaPrompt import generate_with_ollama

try:
    import requests
except ImportError:
    print(
        json.dumps(
            {
                "domain": "",
                "query": "",
                "error": "Missing dependencies. Install with: pip install requests",
                "results": [],
                "count": 0,
                "log_path": "",
                "status": "error",
            },
            ensure_ascii=True,
        )
    )
    sys.exit(1)

DDG_URL = "https://duckduckgo.com/html/?q={q}"
BING_NEWS_RSS_URL = "https://www.bing.com/news/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "close",
}

MIN_REQUEST_DELAY_SECONDS = 3.0
MAX_REQUEST_DELAY_SECONDS = 5.0

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
WHITESPACE_PATTERN = re.compile(r"\s+")

DATE_CONTEXT_OPTIONS = {"none", "month_year", "year"}
MONTH_ABBR = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def validate_domain(domain):
    if not domain or not isinstance(domain, str):
        raise ValueError("Domain must be a non-empty string")
    cleaned = domain.strip()
    if not re.fullmatch(r"[A-Za-z]+", cleaned):
        raise ValueError("Domain must be alphabetic only (A-Z, a-z)")
    return cleaned


def validate_query(query):
    if not query or not isinstance(query, str) or not query.strip():
        raise ValueError("Query must be non-empty")
    return query.strip()


def validate_date_context(value):
    mode = (value or "none").strip().lower()
    if mode not in DATE_CONTEXT_OPTIONS:
        raise ValueError("--date-context must be one of: none, month_year, year")
    return mode


def parse_reference_date(value):
    if not value:
        return dt.date.today()
    cleaned = value.strip()
    try:
        return dt.date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError("--date must be YYYY-MM-DD") from exc


def apply_date_context_to_query(query, date_context, reference_date):
    base = validate_query(query)
    mode = validate_date_context(date_context)

    if mode == "none":
        return base

    if mode == "year":
        return f"{base} {reference_date.year}"

    month_token = MONTH_ABBR[reference_date.month - 1]
    return f"{base} {month_token} {reference_date.year}"


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


def fetch_url_text(url, timeout_seconds):
    time.sleep(random.uniform(MIN_REQUEST_DELAY_SECONDS, MAX_REQUEST_DELAY_SECONDS))
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=timeout_seconds,
        allow_redirects=True,
        verify=True,
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    return response.text, content_type, response.url


def fetch_duckduckgo_html(query, timeout_seconds):
    encoded_query = urllib.parse.quote_plus(query)
    search_url = DDG_URL.format(q=encoded_query)
    html_text, _, _ = fetch_url_text(search_url, timeout_seconds)
    return html_text


def fetch_bing_news_rss(query, timeout_seconds):
    time.sleep(random.uniform(MIN_REQUEST_DELAY_SECONDS, MAX_REQUEST_DELAY_SECONDS))
    response = requests.get(
        BING_NEWS_RSS_URL,
        params={"q": query, "format": "rss", "mkt": "en-US"},
        headers=HEADERS,
        timeout=timeout_seconds,
        allow_redirects=True,
        verify=True,
    )
    response.raise_for_status()
    return response.text


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


def extract_results_from_bing_rss(rss_text, max_count):
    if not rss_text:
        return []

    try:
        root = ET.fromstring(rss_text)
    except ET.ParseError:
        return []

    results = []
    for item in root.findall(".//item"):
        if len(results) >= max_count:
            break

        title = remove_html_tags(item.findtext("title", default=""))
        url = (item.findtext("link", default="") or "").strip()
        snippet = remove_html_tags(item.findtext("description", default=""))

        if not title or not url:
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


def extract_markdown_from_json_ld(html_text: str) -> str:
    script_blocks = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    def normalize_item(obj):
        if isinstance(obj, list):
            for entry in obj:
                yield from normalize_item(entry)
            return
        if not isinstance(obj, dict):
            return
        if isinstance(obj.get("@graph"), list):
            for entry in obj["@graph"]:
                yield from normalize_item(entry)
        yield obj

    for block in script_blocks:
        payload = html.unescape(block).strip()
        if not payload:
            continue
        try:
            parsed = json.loads(payload)
        except Exception:
            continue

        for item in normalize_item(parsed):
            type_value = item.get("@type", "")
            if isinstance(type_value, list):
                types = {str(value).lower() for value in type_value}
            else:
                types = {str(type_value).lower()}

            is_article = any("article" in value for value in types)
            article_body = (item.get("articleBody") or "").strip()
            headline = (item.get("headline") or item.get("name") or "").strip()

            if not is_article or not article_body:
                continue

            text = re.sub(r"\s+", " ", article_body).strip()
            sentences = re.split(r"(?<=[.!?])\s+", text)
            paragraphs = []
            chunk = []
            for sentence in sentences:
                chunk.append(sentence)
                if len(" ".join(chunk)) > 450:
                    paragraphs.append(" ".join(chunk).strip())
                    chunk = []
            if chunk:
                paragraphs.append(" ".join(chunk).strip())

            parts = []
            if headline:
                parts.append(f"# {headline}")
            for paragraph in paragraphs:
                if paragraph:
                    parts.append(paragraph)

            markdown = "\n\n".join(parts).strip()
            if markdown:
                return markdown + "\n"

    return ""


def extract_markdown_from_embedded_state(html_text: str) -> str:
    match = re.search(r'window\.__INITIAL_DATA__="(.*?)";</script>', html_text, flags=re.DOTALL)
    if not match:
        return ""

    escaped_json = match.group(1)
    try:
        decoded = bytes(escaped_json, "utf-8").decode("unicode_escape")
        payload = json.loads(decoded)
    except Exception:
        return ""

    headline = ""
    description = ""
    text_candidates = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "text" and isinstance(value, str):
                    cleaned = re.sub(r"\s+", " ", value).strip()
                    if len(cleaned) >= 20:
                        text_candidates.append(cleaned)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    stores = payload.get("stores", {}) if isinstance(payload, dict) else {}
    if isinstance(stores, dict):
        analytics = stores.get("analytics", {})
        if isinstance(analytics, dict):
            headline = str(analytics.get("title", "")).strip()

        article = stores.get("article", {})
        if isinstance(article, dict):
            metadata = article.get("metadata", {})
            if isinstance(metadata, dict):
                description = str(metadata.get("description", "")).strip()
            walk(article)

    data_root = payload.get("data", {}) if isinstance(payload, dict) else {}
    if isinstance(data_root, dict):
        for key, value in data_root.items():
            if isinstance(key, str) and key.startswith("article?") and isinstance(value, dict):
                article_data = value.get("data", value)
                walk(article_data)

    seen = set()
    paragraphs = []
    for candidate in text_candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        if headline and candidate == headline:
            continue
        paragraphs.append(candidate)

    parts = []
    if headline:
        parts.append(f"# {headline}")
    if description:
        parts.append(description)
    parts.extend(paragraphs[:40])

    markdown = "\n\n".join(part for part in parts if part).strip()
    if not markdown:
        return ""
    return markdown + "\n"


def run_ollama_cleanup(
    text: str,
    model: str,
    prompt: str,
    timeout: int,
    max_chars: int,
) -> str:
    snippet = text[:max_chars]
    llm_prompt = (
        f"{prompt}\n\n"
        "Return ONLY the article main body in clean Markdown.\n"
        "Keep meaningful headings/subheadings and paragraph flow.\n"
        "Discard navigation, sidebars, cookie notices, promo boxes, related links, footers, social widgets, and repeated boilerplate.\n"
        "Do not output raw HTML, tags, scripts, CSS, JSON, or UI labels.\n"
        "If some content is uncertain, omit it rather than including noisy text.\n\n"
        f"PAGE_TEXT:\n{snippet}"
    )

    result = generate_with_ollama(
        prompt=llm_prompt,
        requested_model=model,
        preferred_models=[model, "gpt-oss:120b", "gpt-oss:20b", "qwen3-coder-next:q8_0"],
        auto_pull=False,
        temperature=0.1,
        timeout=timeout,
        startup_wait=20,
    )
    cleaned = (result.get("response") or "").strip()
    if not cleaned:
        raise RuntimeError("LLM returned empty response")
    return cleaned


def summarize_linked_page_with_llm(url, timeout_seconds, llm_model, llm_prompt, llm_max_chars):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "", 0, "skipped: unsupported scheme"

    html_text, content_type, final_url = fetch_url_text(url, timeout_seconds)
    if content_type and "html" not in content_type:
        return "", 0, f"skipped: non-html ({content_type})"

    text = remove_html_tags(html_text)
    if len(text.strip()) < 300:
        fallback_markdown = extract_markdown_from_json_ld(html_text)
        if fallback_markdown:
            text = fallback_markdown

    if len(text.strip()) < 300:
        fallback_markdown = extract_markdown_from_embedded_state(html_text)
        if fallback_markdown:
            text = fallback_markdown

    cleaned = run_ollama_cleanup(
        text=text,
        model=llm_model,
        prompt=llm_prompt,
        timeout=timeout_seconds,
        max_chars=llm_max_chars,
    )
    word_count = len(cleaned.split()) if cleaned else 0
    if not cleaned:
        return "", 0, "error: empty llm summary"

    return cleaned, word_count, f"ok ({final_url})"


def enrich_results_with_page_text(results, page_timeout, llm_model, llm_prompt, llm_max_chars):
    enriched = []
    for result in results:
        entry = dict(result)
        url = entry.get("url", "")

        try:
            summary, word_count, status = summarize_linked_page_with_llm(
                url,
                page_timeout,
                llm_model,
                llm_prompt,
                llm_max_chars,
            )
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


def write_search_plus_log(navigator, domain, query, results, llm_model, llm_max_chars):
    now = dt.datetime.now()
    timestamp = now.isoformat(timespec="seconds")

    filename = query_to_filename(query)
    log_dir = navigator.get_today_path(area="mine", domain=domain, create=True)
    log_file = log_dir / f"{filename}.txt"

    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"Domain: {domain}\n")
        handle.write(f"Query: {query}\n")
        handle.write(f"Timestamp: {timestamp}\n")
        handle.write(f"LLMModel: {llm_model}\n")
        handle.write(f"LLMMaxChars: {llm_max_chars}\n")

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

    return str(log_file)


def main():
    parser = argparse.ArgumentParser(
        description="Search DuckDuckGo, run Gen3 LLM cleanup on linked pages, and log by domain/date"
    )
    parser.add_argument("domain", help="Domain subfolder name (alphabetic only)")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--max", type=int, default=10, help="Max results (1-25)")
    parser.add_argument("--timeout", type=int, default=20, help="Search timeout seconds (5-120)")
    parser.add_argument("--page-timeout", type=int, default=30, help="Page timeout seconds (5-180)")
    parser.add_argument("--sleep-ms", type=int, default=0, help="Optional sleep before search in milliseconds")
    parser.add_argument(
        "--date-context",
        default="none",
        choices=["none", "month_year", "year"],
        help="Optional date context appended to search query",
    )
    parser.add_argument(
        "--date",
        default="",
        help="Optional reference date for date context in YYYY-MM-DD format (defaults to today)",
    )
    parser.add_argument("--llm-model", default="gpt-oss:20b", help="Local Ollama model name")
    parser.add_argument(
        "--llm-prompt",
        default=(
            "Extract the main webpage content into a markdown summary. "
            "Ensure sidebar and navigation text is not included. "
            "The output text needs to read as a singular article."
        ),
        help="Instruction prompt sent to the LLM for each linked page",
    )
    parser.add_argument(
        "--llm-max-chars",
        type=int,
        default=12000,
        help="Maximum input characters sent to the LLM per linked page",
    )

    try:
        args = parser.parse_args()
    except SystemExit as exc:
        return int(exc.code or 0)

    try:
        domain = validate_domain(args.domain)
        query = validate_query(args.query)
        date_context = validate_date_context(args.date_context)
        reference_date = parse_reference_date(args.date)
        effective_query = apply_date_context_to_query(query, date_context, reference_date)
    except Exception as e:
        print(
            json.dumps(
                {
                    "domain": args.domain if hasattr(args, "domain") else "",
                    "query": args.query if hasattr(args, "query") else "",
                    "error": str(e),
                    "results": [],
                    "count": 0,
                    "log_path": "",
                    "status": "error",
                },
                ensure_ascii=True,
            )
        )
        return 1

    if args.sleep_ms > 0:
        time.sleep(args.sleep_ms / 1000.0)

    max_results = max(1, min(args.max, 25))
    timeout_seconds = max(5, min(args.timeout, 120))
    page_timeout = max(5, min(args.page_timeout, 180))

    navigator = FolderNavigator.from_fixed_point()

    filename = query_to_filename(query)
    log_dir = navigator.get_today_path(area="mine", domain=domain, create=True)
    existing_log_file = log_dir / f"{filename}.txt"
    if existing_log_file.exists():
        print(
            json.dumps(
                {
                    "domain": domain,
                    "query": query,
                    "results": [],
                    "count": 0,
                    "log_path": str(existing_log_file),
                    "status": "skipped_existing_output",
                },
                ensure_ascii=True,
            )
        )
        return 0

    try:
        search_html = fetch_duckduckgo_html(effective_query, timeout_seconds)
        base_results = extract_results_from_html(search_html, max_results)
        result_source = "duckduckgo_html"

        if not base_results:
            try:
                rss_text = fetch_bing_news_rss(effective_query, timeout_seconds)
                base_results = extract_results_from_bing_rss(rss_text, max_results)
                if base_results:
                    result_source = "bing_news_rss"
            except Exception:
                pass

        enriched_results = enrich_results_with_page_text(
            base_results,
            page_timeout,
            args.llm_model,
            args.llm_prompt,
            args.llm_max_chars,
        )
        log_path = write_search_plus_log(
            navigator,
            domain,
            query,
            enriched_results,
            args.llm_model,
            args.llm_max_chars,
        )

        response = {
            "domain": domain,
            "query": query,
            "date_context": date_context,
            "query_reference_date": reference_date.isoformat(),
            "effective_query": effective_query,
            "results": enriched_results,
            "log_path": log_path,
            "count": len(enriched_results),
            "result_source": result_source,
            "status": "ok",
        }
        print(json.dumps(response, ensure_ascii=True))
        return 0
    except Exception as e:
        print(
            json.dumps(
                {
                    "domain": domain,
                    "query": query,
                    "error": str(e),
                    "results": [],
                    "count": 0,
                    "log_path": "",
                    "status": "error",
                },
                ensure_ascii=True,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
