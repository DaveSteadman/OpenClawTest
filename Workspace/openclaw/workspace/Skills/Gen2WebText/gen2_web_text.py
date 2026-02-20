#!/usr/bin/env python3
"""Gen2WebText - Domain-aware content-focused web text extraction and link following."""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

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
                "url": "",
                "error": "Missing dependencies. Install with: pip install -r requirements.txt",
                "results": [],
                "links_processed": 0,
                "log_path": "",
                "status": "error",
            }
        )
    )
    sys.exit(1)

try:
    from readability import Document
except ImportError:
    Document = None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

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

NON_CONTENT_LINK_HINTS = [
    "login", "sign-in", "signin", "register", "account", "privacy", "cookies", "terms",
    "contact", "help", "newsletter", "podcast", "audio", "video", "weather", "sport"
]

LOW_SIGNAL_ANCHOR_TEXT = {
    "home", "menu", "more", "sign in", "register", "login", "account", "notifications"
}

SECTION_PATH_HINTS = {
    "/", "/news", "/sport", "/weather", "/iplayer", "/sounds", "/food", "/travel", "/culture"
}


def validate_domain(domain):
    if not domain or not isinstance(domain, str):
        raise ValueError("Domain must be a non-empty string")
    cleaned = domain.strip()
    if not re.fullmatch(r"[A-Za-z]+", cleaned):
        raise ValueError("Domain must be alphabetic only (A-Z, a-z)")
    return cleaned


def validate_url(url):
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https scheme")
    return url


def fetch_html(url, timeout_seconds):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=timeout_seconds,
        allow_redirects=True,
        verify=True,
    )
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type:
        raise ValueError(f"Unsupported content type: {response.headers.get('content-type', 'unknown')}")

    return response.text, response.url


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


def _extract_with_readability(html):
    if Document is None:
        return ""
    try:
        doc = Document(html)
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


def extract_readable_text(html):
    readability_text = _extract_with_readability(html)
    if len(readability_text.split()) >= 80:
        return readability_text

    soup = BeautifulSoup(html, "html.parser")
    content_root = _pick_content_container(soup)
    _prune_noise(content_root)

    paragraph_text = _extract_paragraph_text(content_root)
    text = paragraph_text if paragraph_text else _clean_text(content_root.get_text(separator=" ", strip=True))

    if len(text.split()) < 60:
        fallback_soup = BeautifulSoup(html, "html.parser")
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


def _link_score(start_host, normalized_url, anchor_text):
    parsed = urlparse(normalized_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    anchor_lower = anchor_text.lower()

    score = 0
    if host.endswith(start_host):
        score += 2

    path_depth = len([piece for piece in path.split("/") if piece])
    if path_depth >= 2:
        score += 1

    if any(token in path for token in ["/news/", "/article", "/story", "/live", "/202"]):
        score += 2

    anchor_words = len(anchor_text.split())
    if 4 <= anchor_words <= 20:
        score += 2
    elif anchor_words <= 1:
        score -= 2

    if anchor_lower in LOW_SIGNAL_ANCHOR_TEXT:
        score -= 4

    if any(hint in (path + " " + anchor_lower) for hint in NON_CONTENT_LINK_HINTS):
        score -= 3

    path_no_trailing = path.rstrip("/") if path != "/" else path
    if path_no_trailing in SECTION_PATH_HINTS:
        score -= 4

    if re.search(r"/news/(live|topics?)(/|$)", path):
        score -= 2

    if re.search(r"/news/articles/[a-z0-9]+", path):
        score += 3

    return score


def extract_links(start_url, html, max_links):
    soup = BeautifulSoup(html, "html.parser")
    content_root = _pick_content_container(soup)
    links = []
    seen = set()
    start_host = urlparse(start_url).netloc.lower()

    for index, anchor in enumerate(content_root.find_all("a", href=True)):
        href = (anchor.get("href") or "").strip()
        anchor_text = " ".join((anchor.get_text(" ", strip=True) or "").split())

        if not href or href.startswith("#"):
            continue
        if href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:"):
            continue

        absolute = urljoin(start_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue

        normalized = parsed._replace(fragment="").geturl()
        if normalized in seen:
            continue

        seen.add(normalized)
        score = _link_score(start_host, normalized, anchor_text)
        links.append({"url": normalized, "anchor_text": anchor_text, "score": score, "index": index})

    links.sort(key=lambda item: (-item["score"], item["index"]))

    selected = []
    for item in links:
        if len(selected) >= max_links:
            break
        if item["score"] < 0 and len(selected) >= max(2, max_links // 2):
            continue
        selected.append({"url": item["url"], "anchor_text": item["anchor_text"]})

    if not selected:
        selected = [{"url": item["url"], "anchor_text": item["anchor_text"]} for item in links[:max_links]]

    return selected


def url_to_filename(url):
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "").split(".")[0]
        if domain:
            return (domain[:1].upper() + domain[1:])[:80]
    except Exception:
        pass
    return "WebPage"


def write_log(navigator, domain, start_url, start_summary, start_words, results, words_per_page):
    now = dt.datetime.now()
    timestamp = now.isoformat(timespec="seconds")

    filename = url_to_filename(start_url)
    log_dir = navigator.get_today_path(area="mine", domain=domain, create=True)
    log_file = log_dir / f"{filename}.txt"

    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"Domain: {domain}\n")
        handle.write(f"StartURL: {start_url}\n")
        handle.write(f"Timestamp: {timestamp}\n")
        handle.write(f"PerPageSummaryWords: {words_per_page}\n")
        handle.write(f"StartPageSummaryWords: {start_words}\n")
        handle.write("StartPageSummary:\n")
        handle.write(f"{start_summary}\n\n")

        for result in results:
            handle.write(f"- Link {result['rank']}\n")
            if result.get("anchor_text"):
                handle.write(f"  AnchorText: {result['anchor_text']}\n")
            handle.write(f"  URL: {result['url']}\n")
            handle.write(f"  LinkedPageStatus: {result['page_status']}\n")
            handle.write(f"  LinkedPageSummaryWords: {result['page_words']}\n")
            if result.get("page_summary"):
                handle.write("  LinkedPageSummary:\n")
                handle.write(f"  {result['page_summary']}\n")
            handle.write("\n")

        handle.write("\n")

    return str(log_file)


def process_link(link, timeout_seconds, words_per_page):
    url = link["url"]
    anchor_text = link.get("anchor_text", "")

    try:
        html, resolved_url = fetch_html(url, timeout_seconds)
        text = extract_readable_text(html)
        summary = summarize_words(text, words_per_page)
        page_words = len(summary.split()) if summary else 0
        if not summary:
            return {
                "anchor_text": anchor_text,
                "url": resolved_url,
                "page_summary": "",
                "page_words": 0,
                "page_status": "error: empty extracted text",
            }

        return {
            "anchor_text": anchor_text,
            "url": resolved_url,
            "page_summary": summary,
            "page_words": page_words,
            "page_status": "ok",
        }
    except requests.exceptions.Timeout:
        status = "error: timeout"
    except requests.exceptions.ConnectionError as e:
        status = f"error: connection {str(e)}"
    except requests.exceptions.HTTPError as e:
        status = f"error: HTTP {e.response.status_code}"
    except Exception as e:
        status = f"error: {str(e)}"

    return {
        "anchor_text": anchor_text,
        "url": url,
        "page_summary": "",
        "page_words": 0,
        "page_status": status,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Domain-aware content extraction from a start URL and its links"
    )
    parser.add_argument("domain", help="Domain subfolder name (alphabetic only)")
    parser.add_argument("url", help="Start URL")
    parser.add_argument("--max-links", type=int, default=8, help="Max links to process (1-25)")
    parser.add_argument("--words", type=int, default=200, help="Summary words per page (80-400)")
    parser.add_argument("--timeout-ms", type=int, default=15000, help="Network timeout in milliseconds")

    try:
        args = parser.parse_args()
    except SystemExit:
        return 1

    try:
        domain = validate_domain(args.domain)
        start_url = validate_url(args.url)
    except Exception as e:
        print(
            json.dumps(
                {
                    "domain": args.domain if hasattr(args, "domain") else "",
                    "url": args.url if hasattr(args, "url") else "",
                    "error": str(e),
                    "results": [],
                    "links_processed": 0,
                    "log_path": "",
                    "status": "error",
                },
                ensure_ascii=False,
            )
        )
        return 1

    max_links = max(1, min(args.max_links, 25))
    words_per_page = max(80, min(args.words, 400))
    timeout_seconds = max(1, args.timeout_ms / 1000.0)

    navigator = FolderNavigator.from_fixed_point()

    try:
        start_html, resolved_start_url = fetch_html(start_url, timeout_seconds)
        start_text = extract_readable_text(start_html)
        start_summary = summarize_words(start_text, words_per_page)
        start_words = len(start_summary.split()) if start_summary else 0

        links = extract_links(resolved_start_url, start_html, max_links)

        results = []
        for index, link in enumerate(links, start=1):
            entry = process_link(link, timeout_seconds, words_per_page)
            entry["rank"] = index
            results.append(entry)

        log_path = write_log(
            navigator=navigator,
            domain=domain,
            start_url=resolved_start_url,
            start_summary=start_summary,
            start_words=start_words,
            results=results,
            words_per_page=words_per_page,
        )

        response = {
            "domain": domain,
            "url": resolved_start_url,
            "start_page_summary": start_summary,
            "start_page_words": start_words,
            "results": results,
            "links_processed": len(results),
            "log_path": log_path,
            "status": "ok",
        }
        print(json.dumps(response, ensure_ascii=False))
        return 0

    except Exception as e:
        print(
            json.dumps(
                {
                    "domain": domain,
                    "url": start_url,
                    "error": str(e),
                    "results": [],
                    "links_processed": 0,
                    "log_path": "",
                    "status": "error",
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
