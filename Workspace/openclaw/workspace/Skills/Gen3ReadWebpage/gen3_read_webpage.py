#!/usr/bin/env python3
import argparse
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_ROOT = SCRIPT_DIR.parent
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from CommonCode.FolderNavigator import FolderNavigator
from CommonCode.OllamaPrompt import generate_with_ollama


class MarkdownExtractor(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "form", "button", "input"}
    STRONG_SKIP_TAGS = {"nav", "aside", "footer"}
    SKIP_HINTS = {
        "nav",
        "menu",
        "sidebar",
        "footer",
        "cookie",
        "consent",
        "promo",
        "advert",
        "breadcrumb",
        "share",
        "social",
        "newsletter",
    }
    SKIP_ROLES = {"navigation", "banner", "contentinfo", "complementary"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._parts = []
        self._list_stack = []
        self._in_link = False
        self._link_href = ""
        self._link_text = []

    def _attr_map(self, attrs):
        return {key.lower(): value or "" for key, value in attrs}

    def _should_skip(self, tag, attrs):
        if tag in self.STRONG_SKIP_TAGS or tag in self.SKIP_TAGS:
            return True

        attr_map = self._attr_map(attrs)
        role = attr_map.get("role", "").lower()
        if role in self.SKIP_ROLES:
            return True

        marker_text = " ".join(
            [
                attr_map.get("class", ""),
                attr_map.get("id", ""),
                attr_map.get("aria-label", ""),
            ]
        ).lower()
        return any(hint in marker_text for hint in self.SKIP_HINTS)

    def _append(self, text):
        if self._skip_depth == 0:
            self._parts.append(text)

    def handle_starttag(self, tag, attrs):
        if self._skip_depth > 0:
            self._skip_depth += 1
            return

        if self._should_skip(tag, attrs):
            self._skip_depth = 1
            return

        if tag in {"article", "section", "div", "p", "br"}:
            self._append("\n\n")
            return

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag[1])
            self._append(f"\n\n{'#' * level} ")
            return

        if tag == "ul":
            self._list_stack.append({"type": "ul", "index": 0})
            self._append("\n")
            return

        if tag == "ol":
            self._list_stack.append({"type": "ol", "index": 0})
            self._append("\n")
            return

        if tag == "li":
            indent = "  " * max(len(self._list_stack) - 1, 0)
            if self._list_stack and self._list_stack[-1]["type"] == "ol":
                self._list_stack[-1]["index"] += 1
                marker = f"{self._list_stack[-1]['index']}. "
            else:
                marker = "- "
            self._append(f"\n{indent}{marker}")
            return

        if tag == "a":
            attr_map = self._attr_map(attrs)
            self._in_link = True
            self._link_href = attr_map.get("href", "").strip()
            self._link_text = []

    def handle_endtag(self, tag):
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return

        if tag in {"p", "li", "article", "section", "div"}:
            self._append("\n")
            return

        if tag in {"ul", "ol"}:
            if self._list_stack:
                self._list_stack.pop()
            self._append("\n")
            return

        if tag == "a" and self._in_link:
            text = "".join(self._link_text).strip()
            if text and self._link_href:
                self._append(f"[{text}]({self._link_href})")
            elif text:
                self._append(text)
            self._in_link = False
            self._link_href = ""
            self._link_text = []

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        if self._in_link:
            self._link_text.append(data)
        else:
            self._parts.append(data)

    def get_markdown(self):
        text = "".join(self._parts)
        text = html.unescape(text)
        text = re.sub(r"\r\n?", "\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"\n\s+", "\n", text)
        return text.strip() + "\n"


def fetch_html(url: str, timeout: int) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; OpenClaw-WebpageToTxt/1.0)"
        },
    )
    with urlopen(req, timeout=timeout) as response:
        raw = response.read()
        content_type = response.headers.get_content_charset() or "utf-8"
    return raw.decode(content_type, errors="replace")


def build_amp_url(url: str) -> str:
    if "output=amp" in url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}output=amp"


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

    def walk(node, source_hint: str = ""):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "text" and isinstance(value, str):
                    cleaned = re.sub(r"\s+", " ", value).strip()
                    if len(cleaned) >= 20:
                        text_candidates.append((cleaned, source_hint))
                else:
                    walk(value, source_hint)
        elif isinstance(node, list):
            for item in node:
                walk(item, source_hint)

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
                title = metadata.get("title", {})
                if isinstance(title, dict) and not headline:
                    headline = str(title.get("short") or title.get("full") or "").strip()
            walk(article, "stores.article")

    data_root = payload.get("data", {}) if isinstance(payload, dict) else {}
    if isinstance(data_root, dict):
        for key, value in data_root.items():
            if not (isinstance(key, str) and key.startswith("article?")):
                continue
            if not isinstance(value, dict):
                continue

            article_data = value.get("data", value)
            walk(article_data, f"data.{key}")

    seen = set()
    paragraphs = []
    for candidate, source_hint in text_candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        if headline and candidate == headline:
            continue

        lowered = candidate.lower()
        if "copyright" in lowered and "bbc" in lowered:
            continue
        if "accessibility help" in lowered:
            continue
        if "sign up for our" in lowered and "newsletter" in lowered:
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


def extract_markdown_from_script_strings(html_text: str) -> str:
    script_blocks = re.findall(
        r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not script_blocks:
        return ""

    noise_hints = {
        "cookie",
        "consent",
        "privacy policy",
        "sign in",
        "log in",
        "subscribe",
        "newsletter",
        "advert",
        "sponsor",
        "enable javascript",
    }

    candidates = []
    seen = set()

    for block in script_blocks:
        if len(block) < 200:
            continue

        for match in re.finditer(r'"((?:\\.|[^"\\]){80,})"', block):
            raw = match.group(1)
            try:
                decoded = bytes(raw, "utf-8").decode("unicode_escape")
            except Exception:
                decoded = raw

            text = html.unescape(decoded)
            text = re.sub(r"\\[nrt]", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            lowered = text.lower()

            if len(text.split()) < 8:
                continue
            if any(hint in lowered for hint in noise_hints):
                continue
            if lowered in seen:
                continue
            seen.add(lowered)
            candidates.append(text)

    if not candidates:
        return ""

    title = extract_page_title(html_text)
    parts = [f"# {title}"] if title else []
    parts.extend(candidates[:50])

    markdown = "\n\n".join(parts).strip()
    if not markdown:
        return ""
    return markdown + "\n"


def looks_like_overlay_or_stub(text: str) -> bool:
    cleaned = (text or "").strip().lower()
    if len(cleaned) < 600:
        return True

    overlay_hints = [
        "cookie",
        "consent",
        "sign in",
        "log in",
        "subscribe",
        "privacy policy",
        "accept all",
    ]
    return any(hint in cleaned for hint in overlay_hints)


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
    return cleaned + "\n"


def sanitize_filename_stem(value: str, max_len: int = 120) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    if not cleaned:
        cleaned = "webpage"
    return cleaned[:max_len]


def extract_page_title(html_text: str) -> str:
    title_patterns = [
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\'](.*?)["\']',
        r'<title[^>]*>(.*?)</title>',
    ]

    for pattern in title_patterns:
        match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        candidate = html.unescape(match.group(1) or "")
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if candidate:
            return candidate

    return ""


def webpage_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    last_segment = unquote(parsed.path.rstrip("/").split("/")[-1]).strip()
    if last_segment:
        candidate = Path(last_segment).stem
    else:
        candidate = parsed.netloc or "webpage"

    return sanitize_filename_stem(candidate, max_len=120)


def build_output_stem(url: str, html_text: str) -> str:
    title = extract_page_title(html_text)
    if title:
        return sanitize_filename_stem(title, max_len=32)
    return webpage_name_from_url(url)


def main():
    parser = argparse.ArgumentParser(description="Fetch a webpage and save cleaned Markdown into datastore3")
    parser.add_argument("--url", required=True, help="Web page URL")
    parser.add_argument("--domain", required=True, help="Domain folder name under datastore3")
    parser.add_argument("--area", default="mine", help="FolderNavigator area alias (default: mine)")
    parser.add_argument("--timeout", type=int, default=20, help="Request timeout in seconds")
    parser.add_argument("--llm-model", default="gpt-oss:20b", help="Local Ollama model name")
    parser.add_argument(
        "--llm-prompt",
        default=(
            "Extract the main webpage content into a markdown file. "
            "Ensure sidebar and navigation text is not included. "
            "The output text needs to read as a singular article."
        ),
        help="Instruction prompt sent to the LLM",
    )
    parser.add_argument(
        "--llm-max-chars",
        type=int,
        default=12000,
        help="Maximum input characters sent to the LLM",
    )
    args = parser.parse_args()

    try:
        nav = FolderNavigator.from_fixed_point()
        target_dir = nav.get_today_path(area=args.area, domain=args.domain, create=True)
        html_text = fetch_html(args.url, args.timeout)
        output_path = target_dir / f"{build_output_stem(args.url, html_text)}.md"
        extractor = MarkdownExtractor()
        extractor.feed(html_text)
        text = extractor.get_markdown()
        used_jsonld_fallback = False

        if len(text.strip()) < 300:
            try:
                amp_html = fetch_html(build_amp_url(args.url), args.timeout)
                amp_extractor = MarkdownExtractor()
                amp_extractor.feed(amp_html)
                amp_text = amp_extractor.get_markdown()
                if len(amp_text.strip()) >= 300:
                    text = amp_text
                    used_jsonld_fallback = True
            except Exception:
                pass

        if len(text.strip()) < 300 or looks_like_overlay_or_stub(text):
            fallback_markdown = extract_markdown_from_json_ld(html_text)
            if fallback_markdown:
                text = fallback_markdown
                used_jsonld_fallback = True

        if len(text.strip()) < 300 or looks_like_overlay_or_stub(text):
            fallback_markdown = extract_markdown_from_embedded_state(html_text)
            if fallback_markdown:
                text = fallback_markdown
                used_jsonld_fallback = True

        if len(text.strip()) < 300 or looks_like_overlay_or_stub(text):
            fallback_markdown = extract_markdown_from_script_strings(html_text)
            if fallback_markdown:
                text = fallback_markdown
                used_jsonld_fallback = True

        text = run_ollama_cleanup(
            text=text,
            model=args.llm_model,
            prompt=args.llm_prompt,
            timeout=args.timeout,
            max_chars=args.llm_max_chars,
        )

        output_path.write_text(text, encoding="utf-8")

        print(f"Saved markdown to: {output_path}")
        print(f"Source URL: {args.url}")
        print(f"Domain: {args.domain}")
        print(f"Area: {args.area}")
        if used_jsonld_fallback:
            print("Extraction mode: metadata/state fallback")
        print(f"LLM cleanup: required ({args.llm_model})")
    except Exception as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
