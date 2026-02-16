
---

## `scripts/ddg_search.py`

```python
#!/usr/bin/env python3
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

DDG_HTML = "https://duckduckgo.com/html/?q={q}"

# DuckDuckGo HTML uses redirects like "/l/?uddg=<encoded_url>"
REDIRECT_RE = re.compile(r"/l/\?uddg=([^&\"'>]+)")

# Result blocks often contain: <a class="result__a" href="...">Title</a>
A_TAG_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)

# Snippets often: <a class="result__snippet" ...> or <div class="result__snippet">...
SNIPPET_RE = re.compile(
    r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>',
    re.IGNORECASE | re.DOTALL,
)

TAG_RE = re.compile(r"<[^>]+>")

def html_unescape(s: str) -> str:
    # Minimal unescape without extra deps
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
            "User-Agent": "Mozilla/5.0 (compatible; OpenClawSkill/1.0; +https://duckduckgo.com)",
            "Accept": "text/html",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = resp.read()
    return data.decode("utf-8", errors="replace")

def parse_results(html: str, max_results: int):
    # Find all titles/links first
    anchors = list(A_TAG_RE.finditer(html))
    snippets = list(SNIPPET_RE.finditer(html))

    results = []
    for i, a in enumerate(anchors):
        if len(results) >= max_results:
            break

        href = a.group(1)
        title_html = a.group(2)

        title = strip_tags(title_html)
        url = resolve_ddg_redirect(href)

        snippet = ""
        if i < len(snippets):
            snippet = strip_tags(snippets[i].group(1))

        # Filter obvious DDG internal links
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--max", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--sleep-ms", type=int, default=0, help="Optional politeness delay before request.")
    args = ap.parse_args()

    if args.sleep_ms > 0:
        time.sleep(args.sleep_ms / 1000.0)

    try:
        html = fetch_html(args.query, args.timeout)
        results = parse_results(html, max(1, min(args.max, 25)))
        out = {"query": args.query, "results": results}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    except Exception as e:
        err = {"query": args.query, "error": str(e), "results": []}
        print(json.dumps(err, ensure_ascii=False))
        return 1

if __name__ == "__main__":
    sys.exit(main())
