#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class Result:
    url: str
    chars: int
    text: str
    content_type: str
    status: int


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def _normalize_whitespace(s: str) -> str:
    s = s.replace("\r", "")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def _strip_boilerplate(soup: BeautifulSoup) -> None:
    # Hard removals
    for tag_name in ("script", "style", "noscript"):
        for t in soup.find_all(tag_name):
            t.decompose()

    # Common layout containers
    for tag_name in ("header", "footer", "nav", "aside", "form"):
        for t in soup.find_all(tag_name):
            t.decompose()

    # Common roles
    for role in ("navigation", "banner", "contentinfo"):
        for t in soup.find_all(attrs={"role": role}):
            t.decompose()

    # Common class/id hints
    kill_patterns = (
        "cookie", "cookies", "consent", "gdpr",
        "navbar", "nav", "menu", "footer", "header",
        "sidebar", "subscribe", "modal", "popup",
    )

    def _has_kill_attr(tag) -> bool:
        for attr in ("class", "id"):
            v = tag.get(attr)
            if not v:
                continue
            if isinstance(v, list):
                v = " ".join(v)
            v = str(v).lower()
            if any(p in v for p in kill_patterns):
                return True
        return False

    for t in soup.find_all(_has_kill_attr):
        t.decompose()


def _pick_root(soup: BeautifulSoup):
    main = soup.find("main")
    if main is not None:
        return main
    article = soup.find("article")
    if article is not None:
        return article
    body = soup.find("body")
    return body if body is not None else soup


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    _strip_boilerplate(soup)
    root = _pick_root(soup)

    # Add newlines after common block-ish tags to preserve readability
    for br in root.find_all("br"):
        br.replace_with("\n")

    for tag in root.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"]):
        tag.append("\n")

    text = root.get_text(separator=" ", strip=False)
    return _normalize_whitespace(text)


def _fetch(url: str, timeout_ms: int) -> Tuple[int, str, str]:
    headers = {
        "User-Agent": "openclaw-skill-web_text_py/1.0 (+local)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    }
    timeout_s = timeout_ms / 1000.0

    r = requests.get(url, headers=headers, timeout=timeout_s, allow_redirects=True)
    status = r.status_code
    content_type = (r.headers.get("content-type") or "").lower()

    if status < 200 or status >= 300:
        raise RuntimeError(f"HTTP {status} {r.reason}")

    return status, content_type, r.text


def run(url: str, max_chars: int, timeout_ms: int) -> Result:
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ValueError("url must start with http:// or https://")

    status, content_type, body = _fetch(url, timeout_ms)

    if "text/plain" in content_type:
        text = _normalize_whitespace(body)
    elif ("text/html" in content_type) or ("application/xhtml+xml" in content_type) or (body.lstrip().startswith("<")):
        text = _html_to_text(body)
    else:
        raise RuntimeError(f"Unsupported content-type: {content_type or '(missing)'}")

    text = text[:max_chars]
    return Result(
        url          = url,
        chars        = len(text),
        text         = text,
        content_type = content_type,
        status       = status,
    )


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--max-chars", type=int, default=20000)
    ap.add_argument("--timeout-ms", type=int, default=15000)
    args = ap.parse_args(argv)

    max_chars = _clamp(int(args.max_chars), 500, 200000)
    timeout_ms = _clamp(int(args.timeout_ms), 1000, 60000)

    try:
        result = run(args.url, max_chars, timeout_ms)
        print(json.dumps(result.__dict__, ensure_ascii=False))
        return 0
    except Exception as e:
        err = {"url": args.url, "error": str(e)}
        print(json.dumps(err, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
