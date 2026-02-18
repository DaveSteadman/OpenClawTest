#!/usr/bin/env python3
"""Web Text Extraction (Logged) - Fetch a page and extract readable text, with logging to datastore."""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print(json.dumps({
        "url": "",
        "error": "Missing dependencies. Install with: pip install -r requirements.txt",
        "text": "",
        "chars": 0,
        "log_path": "",
        "status": "error"
    }), file=sys.stdout)
    sys.exit(1)


# ============================================================================
# CONSTANTS
# ============================================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
}

# Maximum characters to extract (prevent huge files)
DEFAULT_MAX_CHARS = 50000


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def validate_url(url):
    """Validate that URL is properly formatted."""
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")
    
    # Try to parse it
    try:
        result = urlparse(url)
        if result.scheme not in ("http", "https"):
            raise ValueError("URL must use http or https scheme")
    except Exception as e:
        raise ValueError(f"Invalid URL: {str(e)}")
    
    return url


def fetch_page(url, timeout_seconds):
    """Fetch a web page and return HTML content."""
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")
    
    if timeout_seconds <= 0:
        timeout_seconds = 15
    
    # Create request headers
    headers = HEADERS.copy()
    
    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=timeout_seconds,
            allow_redirects=True,
            verify=True
        )
        response.raise_for_status()
        
        # Check content type
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type:
            raise ValueError(f"Unsupported content type: {response.headers.get('content-type', 'unknown')}")
        
        return response.text, response.url
    
    except requests.exceptions.Timeout:
        raise RuntimeError("Request timeout")
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Connection error: {str(e)}")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"HTTP {e.response.status_code}: {str(e)}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Request failed: {str(e)}")


def extract_readable_text(html, max_chars=DEFAULT_MAX_CHARS):
    """Extract readable plain text from HTML."""
    if not html:
        return ""
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        
        # Remove script, style, noscript, and other non-content tags
        for tag in soup(["script", "style", "noscript", "meta", "link"]):
            tag.decompose()
        
        # Get text with line breaks
        text = soup.get_text(separator="\n", strip=True)
        
        # Clean up excessive whitespace and newlines
        lines = [line.strip() for line in text.split("\n")]
        lines = [line for line in lines if line]  # Remove empty lines
        text = "\n".join(lines)
        
        # Limit to max chars
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[... text truncated ...]"
        
        return text
    
    except Exception as e:
        raise RuntimeError(f"Failed to parse HTML: {str(e)}")


def url_to_filename(url):
    """Convert URL to a safe filename (CamelCase)."""
    if not url:
        return "WebPage"
    
    try:
        # Extract domain or path
        parsed = urlparse(url)
        
        # Prefer domain name over full URL
        domain = parsed.netloc.replace("www.", "").split(".")[0]
        
        if domain:
            # Capitalize domain
            filename = domain[0].upper() + domain[1:].lower()
        else:
            # Fall back to path segments
            path_parts = parsed.path.strip("/").split("/")
            tokens = []
            for part in path_parts[:3]:  # Take first 3 path segments
                clean = re.sub(r"[^a-zA-Z0-9]", "", part)
                if clean:
                    tokens.append(clean)
            
            if tokens:
                filename = "".join(t[0].upper() + t[1:].lower() for t in tokens)
            else:
                filename = "WebPage"
        
        # Limit to 80 characters
        return filename[:80]
    
    except Exception:
        return "WebPage"


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


def write_log_file(data_root, url, text):
    """Write extracted text to log file in structured directory."""
    if not url:
        raise ValueError("URL cannot be empty")
    
    # Get current date/time
    now = dt.datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    day = now.strftime("%d")
    timestamp = now.isoformat(timespec="seconds")
    
    # Determine filename from URL
    filename = url_to_filename(url)
    
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
            f.write(f"URL: {url}\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write("=" * 80 + "\n\n")
            
            # Write extracted text
            f.write(text)
            
            # Add separator
            f.write("\n" + "=" * 80 + "\n\n")
    
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
        description="Fetch a web page, extract readable text, and log to datastore"
    )
    parser.add_argument("--url", required=True, help="URL to fetch (required)")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help=f"Max characters to extract (default {DEFAULT_MAX_CHARS})")
    parser.add_argument("--timeout-ms", type=int, default=15000,
                        help="Network timeout in milliseconds (default 15000)")
    
    try:
        args = parser.parse_args()
    except SystemExit:
        return 1
    
    # Convert timeout from milliseconds to seconds
    timeout_seconds = max(1, args.timeout_ms / 1000.0)
    
    # Validate URL
    try:
        url = validate_url(args.url)
    except ValueError as e:
        error_response = {
            "url": args.url,
            "error": f"Invalid URL: {str(e)}",
            "text": "",
            "chars": 0,
            "log_path": "",
            "status": "error"
        }
        print(json.dumps(error_response, ensure_ascii=False))
        return 1
    
    # Get data root
    data_root = get_data_root()
    
    # Execute fetch and extract
    try:
        # Fetch the page
        html, resolved_url = fetch_page(url, timeout_seconds)
        
        # Extract readable text
        text = extract_readable_text(html, args.max_chars)
        
        # Log to file
        log_path = write_log_file(data_root, resolved_url, text)
        
        # Return success response
        response = {
            "url": resolved_url,
            "chars": len(text),
            "text": text,
            "log_path": log_path,
            "status": "ok"
        }
        print(json.dumps(response, ensure_ascii=False))
        return 0
    
    except Exception as e:
        # Return error response
        error_response = {
            "url": url,
            "error": str(e),
            "text": "",
            "chars": 0,
            "log_path": "",
            "status": "error"
        }
        print(json.dumps(error_response, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
