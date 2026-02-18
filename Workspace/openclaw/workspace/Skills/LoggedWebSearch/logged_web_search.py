#!/usr/bin/env python3
"""DuckDuckGo Search (Logged) - Simple web search with plain-text logging."""

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

# DuckDuckGo HTML endpoint
DDG_URL = "https://duckduckgo.com/html/?q={q}"

# ============================================================================
# HTML PARSING: Regex patterns for DuckDuckGo results
# ============================================================================

# Find redirect links: /l/?uddg=<encoded_url>
REDIRECT_PATTERN = re.compile(r"/l/\?uddg=([^&\"'>]+)")

# Find result anchors with class="result__a"
ANCHOR_PATTERN = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL
)

# Find snippets with class="result__snippet"
SNIPPET_PATTERN = re.compile(
    r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>',
    re.IGNORECASE | re.DOTALL
)

# Strip any HTML tags
TAG_PATTERN = re.compile(r"<[^>]+>")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def decode_html_entities(text):
    """Decode common HTML entities to plain text."""
    if not text:
        return ""
    
    replacements = [
        ("&amp;", "&"),
        ("&quot;", '"'),
        ("&#39;", "'"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&nbsp;", " "),
        ("&mdash;", "—"),
        ("&ndash;", "–"),
    ]
    
    for entity, char in replacements:
        text = text.replace(entity, char)
    
    return text


def remove_html_tags(text):
    """Remove all HTML tags from text."""
    if not text:
        return ""
    text = TAG_PATTERN.sub("", text)
    text = decode_html_entities(text)
    return text.strip()


def decode_redirect_url(redirect_url):
    """Decode DuckDuckGo redirect URL to actual target URL."""
    if not redirect_url:
        return ""
    
    match = REDIRECT_PATTERN.search(redirect_url)
    if match:
        try:
            return urllib.parse.unquote(match.group(1))
        except Exception:
            return redirect_url
    
    return redirect_url


def fetch_duckduckgo_html(query, timeout_seconds):
    """Fetch HTML from DuckDuckGo search."""
    if not query or not isinstance(query, str):
        raise ValueError("Query must be a non-empty string")
    
    if timeout_seconds <= 0:
        timeout_seconds = 20
    
    # URL-encode the query
    encoded_query = urllib.parse.quote_plus(query)
    search_url = DDG_URL.format(q=encoded_query)
    
    # Create request with proper headers
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    request = urllib.request.Request(search_url, headers=headers, method="GET")
    
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            html_bytes = response.read()
        
        # Decode with error replacement for robustness
        html_text = html_bytes.decode("utf-8", errors="replace")
        return html_text
    
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {str(e)}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Failed to fetch: {str(e)}")


def extract_results_from_html(html, max_count):
    """Extract search results from DuckDuckGo HTML response."""
    if not html:
        return []
    
    if max_count <= 0:
        max_count = 8
    
    results = []
    
    # Find all anchors (result titles)
    anchors = list(ANCHOR_PATTERN.finditer(html))
    
    # Find all snippets (result descriptions)
    snippets = list(SNIPPET_PATTERN.finditer(html))
    
    # Extract result for each anchor, up to max_count
    for index, anchor_match in enumerate(anchors):
        # Stop when we have enough
        if len(results) >= max_count:
            break
        
        try:
            # Extract fields from anchor
            href = anchor_match.group(1)
            title_html = anchor_match.group(2)
            
            # Clean up title
            title = remove_html_tags(title_html)
            
            # Decode redirect URL
            url = decode_redirect_url(href)
            
            # Skip relative URLs
            if url.startswith("/"):
                continue
            
            # Extract snippet if available
            snippet = ""
            if index < len(snippets):
                snippet_html = snippets[index].group(1)
                snippet = remove_html_tags(snippet_html)
            
            # Skip empty entries
            if not title or not url:
                continue
            
            # Add result
            result = {
                "title": title,
                "url": url,
                "snippet": snippet,
                "rank": len(results) + 1,
            }
            results.append(result)
        
        except Exception as parse_error:
            # Skip malformed results
            continue
    
    return results


def query_to_filename(query):
    """Convert query string to a safe filename (CamelCase)."""
    if not query:
        return "Search"
    
    # Extract alphanumeric tokens
    tokens = re.findall(r"[A-Za-z0-9]+", query)
    
    if not tokens:
        return "Search"
    
    # Convert tokens to CamelCase
    camel_parts = []
    for token in tokens:
        if token.isdigit():
            camel_parts.append(token)
        else:
            # Capitalize first letter, lowercase rest
            camel_parts.append(token[0].upper() + token[1:].lower())
    
    filename = "".join(camel_parts)
    
    # Limit to 80 characters
    return filename[:80]


def get_data_root():
    """Get the root directory for storing data."""
    # Check environment variable first
    env_root = os.environ.get("OPENCLAW_OUTPUT_ROOT")
    if env_root:
        return env_root
    
    # Fall back to default location
    home_dir = Path.home()
    default_root = home_dir / ".openclaw" / "data"
    
    return str(default_root)


def write_search_log(data_root, query, results):
    """Write search results to plain-text log file."""
    if not query:
        raise ValueError("Query cannot be empty")
    
    # Get current date/time
    now = dt.datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    day = now.strftime("%d")
    timestamp = now.isoformat(timespec="seconds")
    
    # Determine filename
    filename = query_to_filename(query)
    
    # Create directory path: datastore/YYYY/MM/DD/
    log_dir = os.path.join(data_root, "datastore", year, month, day)
    
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception as e:
        raise RuntimeError(f"Failed to create log directory: {str(e)}")
    
    # Create full path
    log_file = os.path.join(log_dir, f"{filename}.txt")
    
    # Write log
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            # Write header
            f.write(f"Query: {query}\n")
            f.write(f"Timestamp: {timestamp}\n")
            
            # Write each result
            for result in results:
                title = result.get("title", "").strip()
                url = result.get("url", "").strip()
                snippet = result.get("snippet", "").strip()
                
                if title:
                    f.write(f"- {title}\n")
                if url:
                    f.write(f"  {url}\n")
                if snippet:
                    f.write(f"  {snippet}\n")
            
            # Add blank line between entries
            f.write("\n")
    
    except Exception as e:
        raise RuntimeError(f"Failed to write log file: {str(e)}")
    
    return log_file


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main entry point."""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Search DuckDuckGo and log results to plain text"
    )
    parser.add_argument("--query", required=True, help="Search query (required)")
    parser.add_argument("--max", type=int, default=8, help="Max results (1-25, default 8)")
    parser.add_argument("--timeout", type=int, default=20, help="Network timeout in seconds (default 20)")
    parser.add_argument("--sleep-ms", type=int, default=0, help="Sleep before search in milliseconds (default 0)")
    
    try:
        args = parser.parse_args()
    except SystemExit:
        return 1
    
    # Validate arguments
    if not args.query or not isinstance(args.query, str):
        error_response = {
            "query": "",
            "error": "Query must be provided and must be a string",
            "results": [],
        }
        print(json.dumps(error_response, ensure_ascii=False))
        return 1
    
    # Optional sleep
    if args.sleep_ms > 0:
        try:
            time.sleep(args.sleep_ms / 1000.0)
        except Exception:
            pass
    
    # Clamp max results
    max_results = max(1, min(args.max, 25))
    timeout_seconds = max(5, min(args.timeout, 60))
    
    # Get data root
    data_root = get_data_root()
    
    # Execute search
    try:
        # Fetch HTML from DuckDuckGo
        html = fetch_duckduckgo_html(args.query, timeout_seconds)
        
        # Parse results from HTML
        results = extract_results_from_html(html, max_results)
        
        # Log results to file
        log_path = write_search_log(data_root, args.query, results)
        
        # Return success response
        response = {
            "query": args.query,
            "results": results,
            "log_path": log_path,
            "count": len(results),
            "status": "ok",
        }
        print(json.dumps(response, ensure_ascii=False))
        return 0
    
    except Exception as e:
        # Return error response
        error_response = {
            "query": args.query,
            "error": str(e),
            "results": [],
            "count": 0,
            "status": "error",
        }
        print(json.dumps(error_response, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
