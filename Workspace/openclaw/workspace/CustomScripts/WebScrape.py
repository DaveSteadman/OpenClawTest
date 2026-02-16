import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

def _venv_python_path():
    script_dir = Path(__file__).resolve().parent
    venv_python = script_dir.parent / ".venv" / "Scripts" / "python.exe"
    return venv_python if venv_python.exists() else None

def _ensure_venv():
    if sys.prefix != sys.base_prefix:
        return

    venv_python = _venv_python_path()
    if not venv_python:
        return

    result = subprocess.run([str(venv_python), __file__, *sys.argv[1:]], check=False)
    sys.exit(result.returncode)

def _ensure_dependencies():
    try:
        import requests  # noqa: F401
        from bs4 import BeautifulSoup  # noqa: F401
        return
    except Exception:
        pass

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "requests", "beautifulsoup4"],
        check=True,
    )

_ensure_venv()
_ensure_dependencies()

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (text-scraper)"
}

def fetch_text(url, timeout=10):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()

        content_type = r.headers.get("content-type", "")
        if "text/html" not in content_type:
            return "", []

        soup = BeautifulSoup(r.text, "html.parser")

        # remove script/style
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)

        links = []
        for a in soup.find_all("a", href=True):
            abs_url = urljoin(url, a["href"])
            parsed = urlparse(abs_url)
            if parsed.scheme in ("http", "https"):
                links.append(abs_url)

        return text, links

    except Exception:
        return "", []

def crawl_one_hop(start_url, max_links=20):
    results = {}

    root_text, links = fetch_text(start_url)
    results[start_url] = root_text

    seen = set([start_url])
    count = 0

    for link in links:
        if link in seen:
            continue
        if count >= max_links:
            break

        text, _ = fetch_text(link)
        if text:
            results[link] = text
            seen.add(link)
            count += 1

    return results

if __name__ == "__main__":
    url = "https://www.bbc.co.uk/news"
    data = crawl_one_hop(url)

    for u, text in data.items():
        print(f"\n===== {u} =====\n")
        print(text[:2000])  # truncate preview
