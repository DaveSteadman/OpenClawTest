#!/usr/bin/env python3
"""Table Extraction - Fetch a page, extract the main data table using LLM, save as CSV."""

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
from io import StringIO
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
    import pandas as pd
except ImportError:
    print(json.dumps({
        "url": "",
        "error": "Missing dependencies. Install with: pip install -r requirements.txt",
        "csv_path": "",
        "status": "error"
    }), file=sys.stdout)
    sys.exit(1)


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
}


def validate_url(url):
    """Validate that URL is properly formatted."""
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")
    
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


def extract_tables_html(html):
    """Extract all table elements from HTML as clean strings."""
    if not html:
        return []
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        
        table_strings = []
        for i, table in enumerate(tables):
            # Convert table back to string, cleaned up
            table_str = str(table)
            table_strings.append(table_str)
        
        return table_strings
    
    except Exception as e:
        raise RuntimeError(f"Failed to extract tables: {str(e)}")


def extract_table_as_csv(html):
    """Extract the largest table from HTML and convert to CSV."""
    if not html:
        raise ValueError("HTML content is empty")
    
    try:
        # Use pandas to extract HTML tables
        tables = pd.read_html(StringIO(html))
        
        if not tables:
            raise ValueError("No tables found on page")
        
        # Find the largest table (most columns/rows) 
        largest_table = max(tables, key=lambda t: len(t) * len(t.columns))
        
        # Convert to CSV string
        csv_buffer = StringIO()
        largest_table.to_csv(csv_buffer, index=False)
        csv_content = csv_buffer.getvalue()
        
        return csv_content
    
    except Exception as e:
        raise RuntimeError(f"Failed to extract table from HTML: {str(e)}")


def validate_csv(csv_content):
    """Validate that content is valid CSV and has data."""
    try:
        reader = csv.reader(StringIO(csv_content))
        rows = list(reader)
        
        if not rows:
            raise ValueError("CSV is empty")
        
        if len(rows) < 2:
            raise ValueError("CSV has no data rows (header only)")
        
        return True
    
    except Exception as e:
        raise ValueError(f"Invalid CSV format: {str(e)}")


def url_to_filename(url):
    """Convert URL to a safe filename (CamelCase)."""
    if not url:
        return "Table"
    
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "").split(".")[0]
        
        if domain:
            filename = domain[0].upper() + domain[1:].lower()
        else:
            path_parts = parsed.path.strip("/").split("/")
            tokens = []
            for part in path_parts[:3]:
                clean = "".join(c for c in part if c.isalnum())
                if clean:
                    tokens.append(clean)
            
            if tokens:
                filename = "".join(t[0].upper() + t[1:].lower() for t in tokens)
            else:
                filename = "Table"
        
        return filename[:80]
    
    except Exception:
        return "Table"


def get_data_root():
    """Get the root directory for storing data."""
    env_root = os.environ.get("OPENCLAW_OUTPUT_ROOT")
    if env_root:
        return env_root
    
    home_dir = Path.home()
    default_root = home_dir / ".openclaw" / "data"
    
    return str(default_root)


def write_csv_file(data_root, url, csv_content):
    """Write CSV data to file in structured directory."""
    if not url:
        raise ValueError("URL cannot be empty")
    
    now = dt.datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    day = now.strftime("%d")
    
    filename = url_to_filename(url)
    
    csv_dir = os.path.join(data_root, "datastore", year, month, day)
    
    try:
        os.makedirs(csv_dir, exist_ok=True)
    except Exception as e:
        raise RuntimeError(f"Failed to create csv directory: {str(e)}")
    
    csv_file = os.path.join(csv_dir, f"{filename}_table.csv")
    
    try:
        with open(csv_file, "w", encoding="utf-8", newline="") as f:
            f.write(csv_content)
    
    except Exception as e:
        raise RuntimeError(f"Failed to write csv file: {str(e)}")
    
    return csv_file


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Fetch a web page, extract the main data table, save as CSV"
    )
    parser.add_argument("--url", required=True, help="URL to fetch (required)")
    parser.add_argument("--timeout-ms", type=int, default=15000,
                        help="Network timeout in milliseconds (default 15000)")
    
    try:
        args = parser.parse_args()
    except SystemExit:
        return 1
    
    timeout_seconds = max(1, args.timeout_ms / 1000.0)
    
    try:
        url = validate_url(args.url)
    except ValueError as e:
        error_response = {
            "url": args.url,
            "error": f"Invalid URL: {str(e)}",
            "csv_path": "",
            "rows": 0,
            "status": "error"
        }
        print(json.dumps(error_response, ensure_ascii=False))
        return 1
    
    data_root = get_data_root()
    
    try:
        # Fetch the page
        html, resolved_url = fetch_page(url, timeout_seconds)
        
        # Extract table as CSV
        csv_content = extract_table_as_csv(html)
        
        # Validate CSV
        validate_csv(csv_content)
        
        # Count rows
        reader = csv.reader(StringIO(csv_content))
        rows = list(reader)
        row_count = len(rows) - 1  # Exclude header
        
        # Write to file
        csv_path = write_csv_file(data_root, resolved_url, csv_content)
        
        # Return success response
        response = {
            "url": resolved_url,
            "csv_path": csv_path,
            "rows": row_count,
            "status": "ok"
        }
        print(json.dumps(response, ensure_ascii=False))
        return 0
    
    except Exception as e:
        error_response = {
            "url": url,
            "error": str(e),
            "csv_path": "",
            "rows": 0,
            "status": "error"
        }
        print(json.dumps(error_response, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
