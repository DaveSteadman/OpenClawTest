#!/usr/bin/env python3
"""Gen2WebSearch - DuckDuckGo search + robust linked-page summaries + domain-aware logging."""

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

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print(
        json.dumps(
            {
                "domain": "",
                "query": "",
                "error": "Missing dependencies. Install with: pip install -r requirements.txt",
                "results": [],
                "count": 0,
                "log_path": "",
                "status": "error",
            },
            ensure_ascii=True,
        )
    )
    sys.exit(1)

try:
    from readability import Document
except ImportError:
    Document = None

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

NOISE_TAGS = {
    "script", "style", "noscript", "meta", "link", "nav", "header", "footer",
    "aside", "form", "button", "svg", "picture", "iframe"
}

NOISE_HINTS = [
    "nav", "menu", "header", "footer", "breadcrumb", "cookie", "consent", "privacy",
    "account", "signin", "sign-in", "login", "register", "newsletter", "share", "social",
    "promo", "advert", "ads", "sidebar", "related", "subscribe", "notification"
]

CONTENT_HINTS = [
    "content", "article", "story", "main", "body", "post", "entry", "headline", "news"
]


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


def _attrs_to_text(tag):
    if not hasattr(tag, "get"):
        return ""
    if not hasattr(tag, "attrs") or tag.attrs is None:
        return ""

    attr_values = []
    tag_id = tag.get("id")
    if tag_id:
        attr_values.append(str(tag_id))

    tag_class = tag.get("class")
    if isinstance(tag_class, list):
        attr_values.extend([str(item) for item in tag_class])
    elif tag_class:
        attr_values.append(str(tag_class))

    role = tag.get("role")
    if role:
        attr_values.append(str(role))

    aria_label = tag.get("aria-label")
    if aria_label:
        attr_values.append(str(aria_label))

    return " ".join(attr_values).lower()


def _looks_like_noise(tag):
    attrs_text = _attrs_to_text(tag)
    return any(hint in attrs_text for hint in NOISE_HINTS)


def _prune_noise(container):
    for tag in list(container.find_all(list(NOISE_TAGS))):
        tag.decompose()

    for tag in list(container.find_all(True)):
        if not hasattr(tag, "attrs") or tag.attrs is None:
            continue
        if _looks_like_noise(tag):
            tag.decompose()


def _clean_text(text):
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    cleaned = cleaned.replace("Â", " ").replace("â", "'").replace("â", "-")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _extract_paragraph_text(container):
    paragraphs = []
    for paragraph in container.find_all("p"):
        text = _clean_text(paragraph.get_text(" ", strip=True))
        if len(text.split()) < 8:
            continue
        if any(hint in text.lower() for hint in ["accessibility help", "cookie", "privacy policy", "sign in"]):
            continue
        paragraphs.append(text)

    return " ".join(paragraphs).strip()


def _extract_with_readability(html_text):
    if Document is None:
        return ""
    try:
        doc = Document(html_text)
        summary_html = doc.summary(html_partial=True)
        summary_soup = BeautifulSoup(summary_html, "html.parser")
        _prune_noise(summary_soup)
        paragraph_text = _extract_paragraph_text(summary_soup)
        if paragraph_text:
            return paragraph_text
        fallback = _clean_text(summary_soup.get_text(separator=" ", strip=True))
        return fallback
    except Exception:
        return ""


def _pick_content_container(soup):
    preferred_selectors = ["article", "main", "[role='main']"]
    for selector in preferred_selectors:
        candidate = soup.select_one(selector)
        if candidate:
            preview_words = len(candidate.get_text(" ", strip=True).split())
            if preview_words >= 60:
                return candidate

    best_tag = None
    best_words = 0
    for tag in soup.find_all(["section", "div", "main", "article"]):
        attrs_text = _attrs_to_text(tag)
        if not any(hint in attrs_text for hint in CONTENT_HINTS):
            continue
        if any(hint in attrs_text for hint in NOISE_HINTS):
            continue

        word_count = len(tag.get_text(" ", strip=True).split())
        if word_count > best_words:
            best_words = word_count
            best_tag = tag

    if best_tag:
        return best_tag

    return soup


def extract_readable_text(html_text):
    readability_text = _extract_with_readability(html_text)
    if len(readability_text.split()) >= 80:
        return readability_text

    soup = BeautifulSoup(html_text, "html.parser")
    content_root = _pick_content_container(soup)
    _prune_noise(content_root)

    paragraph_text = _extract_paragraph_text(content_root)
    text = paragraph_text if paragraph_text else _clean_text(content_root.get_text(separator=" ", strip=True))

    if len(text.split()) < 60:
        fallback_soup = BeautifulSoup(html_text, "html.parser")
        _prune_noise(fallback_soup)
        paragraph_text = _extract_paragraph_text(fallback_soup)
        text = paragraph_text if paragraph_text else _clean_text(fallback_soup.get_text(separator=" ", strip=True))

    if len(text.split()) < 40 and readability_text:
        text = readability_text

    return text


def summarize_words(text, target_words):
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

    text = extract_readable_text(html_text)
    summary = summarize_words(text, target_words)
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


def _normalize_query_spacing(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def build_relaxed_queries(query):
    candidates = []
    base = _normalize_query_spacing(query)
    if not base:
        return candidates

    no_latest = _normalize_query_spacing(re.sub(r"\blatest\b", "", base, flags=re.IGNORECASE))
    if no_latest and no_latest.lower() != base.lower():
        candidates.append(no_latest)

    award_singular = _normalize_query_spacing(re.sub(r"\bawards\b", "award", base, flags=re.IGNORECASE))
    if award_singular and award_singular.lower() != base.lower():
        candidates.append(award_singular)

    no_latest_award_singular = _normalize_query_spacing(
        re.sub(r"\bawards\b", "award", no_latest, flags=re.IGNORECASE)
    )
    if no_latest_award_singular and no_latest_award_singular.lower() not in {base.lower(), no_latest.lower(), award_singular.lower()}:
        candidates.append(no_latest_award_singular)

    return candidates


def write_search_plus_log(navigator, domain, query, results, words_per_page):
    now = dt.datetime.now()
    timestamp = now.isoformat(timespec="seconds")

    filename = query_to_filename(query)
    log_dir = navigator.get_today_path(area="mine", domain=domain, create=True)
    log_file = log_dir / f"{filename}.txt"

    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"Domain: {domain}\n")
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

    return str(log_file)


def main():
    parser = argparse.ArgumentParser(
        description="Search DuckDuckGo, summarize linked pages, and log by domain/date"
    )
    parser.add_argument("domain", help="Domain subfolder name (alphabetic only)")
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

    try:
        domain = validate_domain(args.domain)
        query = validate_query(args.query)
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
    timeout_seconds = max(5, min(args.timeout, 60))
    page_timeout = max(5, min(args.page_timeout, 60))
    words_per_page = max(80, min(args.words, 400))

    navigator = FolderNavigator.from_fixed_point()

    try:
        effective_query = query
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

        if not base_results:
            for relaxed_query in build_relaxed_queries(query):
                try:
                    search_html = fetch_duckduckgo_html(relaxed_query, timeout_seconds)
                    base_results = extract_results_from_html(search_html, max_results)
                    if base_results:
                        effective_query = relaxed_query
                        result_source = "duckduckgo_html_relaxed"
                        break
                except Exception:
                    pass

                try:
                    rss_text = fetch_bing_news_rss(relaxed_query, timeout_seconds)
                    base_results = extract_results_from_bing_rss(rss_text, max_results)
                    if base_results:
                        effective_query = relaxed_query
                        result_source = "bing_news_rss_relaxed"
                        break
                except Exception:
                    pass

        enriched_results = enrich_results_with_page_text(base_results, page_timeout, words_per_page)
        log_path = write_search_plus_log(navigator, domain, query, enriched_results, words_per_page)

        response = {
            "domain": domain,
            "query": query,
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
