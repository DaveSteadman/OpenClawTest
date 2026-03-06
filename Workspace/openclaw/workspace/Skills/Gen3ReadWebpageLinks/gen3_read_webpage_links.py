#!/usr/bin/env python3
import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_ROOT = SCRIPT_DIR.parent
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from CommonCode.FolderNavigator import FolderNavigator
from CommonCode.OllamaPrompt import generate_with_ollama

GEN3_READ_FILE = SKILLS_ROOT / "Gen3ReadWebpage" / "gen3_read_webpage.py"
spec = importlib.util.spec_from_file_location("gen3_read_webpage", GEN3_READ_FILE)
if spec is None or spec.loader is None:
    raise RuntimeError("Could not load Gen3ReadWebpage module")
readpage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readpage)

HREF_PATTERN = re.compile(r'href=["\'](.*?)["\']', flags=re.IGNORECASE)
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
WHITESPACE_PATTERN = re.compile(r"\s+")

BLOCKED_SCHEMES = ("mailto:", "javascript:", "tel:", "data:", "#")
BLOCKED_SUFFIXES = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".css", ".js", ".json", ".xml", ".pdf", ".zip", ".mp4", ".mp3",
)
BLOCKED_HINTS = (
    "doubleclick", "googlesyndication", "googleadservices", "taboola", "outbrain",
    "/ads", "adserver", "sponsor", "utm_medium=", "utm_campaign=",
    "/login", "/signin", "/sign-in", "/register", "/account", "/subscribe",
    "/newsletters", "/privacy", "/cookie", "/cookies", "/terms",
)


def normalize_url(base_url: str, href: str) -> str:
    href = (href or "").strip()
    if not href or href.lower().startswith(BLOCKED_SCHEMES):
        return ""

    full = urljoin(base_url, href)
    parsed = urlparse(full)
    if parsed.scheme not in ("http", "https"):
        return ""

    if parsed.path.lower().endswith(BLOCKED_SUFFIXES):
        return ""

    lowered = full.lower()
    if any(hint in lowered for hint in BLOCKED_HINTS):
        return ""

    normalized = parsed._replace(fragment="")
    return urlunparse(normalized)


def canonical_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    path = parsed.path.rstrip("/")
    normalized = parsed._replace(path=path, fragment="")
    return urlunparse(normalized)


def extract_candidate_links(page_url: str, html_text: str, max_candidates: int = 150) -> list[str]:
    found = []
    seen = set()

    for match in HREF_PATTERN.finditer(html_text):
        normalized = normalize_url(page_url, match.group(1))
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        found.append(normalized)
        if len(found) >= max_candidates:
            break

    return found


def extract_candidate_links_from_markdown(page_url: str, markdown_text: str, max_candidates: int = 150) -> list[str]:
    found = []
    seen = set()

    for match in MARKDOWN_LINK_PATTERN.finditer(markdown_text or ""):
        normalized = normalize_url(page_url, match.group(1))
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        found.append(normalized)
        if len(found) >= max_candidates:
            break

    return found


def extract_json_payload(text: str):
    payload = (text or "").strip()
    if not payload:
        return None

    try:
        return json.loads(payload)
    except Exception:
        pass

    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", payload, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except Exception:
            pass

    obj_match = re.search(r"\{.*\}", payload, flags=re.DOTALL)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except Exception:
            pass

    arr_match = re.search(r"\[.*\]", payload, flags=re.DOTALL)
    if arr_match:
        try:
            return json.loads(arr_match.group(0))
        except Exception:
            pass

    return None


def select_links_with_llm(
    source_url: str,
    page_text: str,
    candidate_links: list[str],
    candidate_source: str,
    llm_model: str,
    timeout: int,
    count: int,
    selector_prompt: str,
) -> list[str]:
    candidate_lines = "\n".join(f"- {url}" for url in candidate_links)
    prompt = (
        f"{selector_prompt}\n\n"
        f"Source page URL: {source_url}\n"
        f"Target number of links: {count}\n\n"
        f"Candidate source: {candidate_source}\n"
        "Select links from CANDIDATE_LINKS only.\n"
        "Rules:\n"
        "- Most relevant to the MAIN ARTICLE CONTENT of the source page\n"
        "- Never choose top navigation/category/home/footer/header links unless directly cited in the main content\n"
        "- No adverts, sponsors, tracking, subscription, login, or generic nav pages\n"
        "- Prefer substantive article or source pages\n"
        "- Return exactly JSON only\n"
        "- JSON schema: {\"links\": [\"https://...\"]}\n\n"
        f"SOURCE_PAGE_TEXT:\n{page_text[:8000]}\n\n"
        f"CANDIDATE_LINKS:\n{candidate_lines}"
    )

    result = generate_with_ollama(
        prompt=prompt,
        requested_model=llm_model,
        preferred_models=[llm_model, "gpt-oss:120b", "gpt-oss:20b", "qwen3-coder-next:q8_0"],
        auto_pull=False,
        temperature=0.1,
        timeout=timeout,
        startup_wait=20,
    )

    payload = extract_json_payload(result.get("response") or "")
    selected: list[str] = []

    if isinstance(payload, dict):
        links = payload.get("links", [])
    elif isinstance(payload, list):
        links = payload
    else:
        links = []

    source_canonical = canonical_url(source_url)
    allowed = {
        candidate
        for candidate in candidate_links
        if canonical_url(candidate) != source_canonical and urlparse(candidate).path not in ("", "/")
    }
    for value in links:
        if not isinstance(value, str):
            continue
        normalized = normalize_url(source_url, value)
        if not normalized:
            continue
        if normalized not in allowed:
            continue
        if normalized in selected:
            continue
        selected.append(normalized)
        if len(selected) >= count:
            break

    if len(selected) < count:
        for candidate in candidate_links:
            if candidate not in allowed:
                continue
            if candidate not in selected:
                selected.append(candidate)
            if len(selected) >= count:
                break

    return selected[:count]


def build_source_page_markdown(page_url: str, html_text: str, timeout: int) -> str:
    extractor = readpage.MarkdownExtractor()
    extractor.feed(html_text)
    text = extractor.get_markdown()

    if len(text.strip()) < 300:
        try:
            amp_html = readpage.fetch_html(readpage.build_amp_url(page_url), timeout)
            amp_extractor = readpage.MarkdownExtractor()
            amp_extractor.feed(amp_html)
            amp_text = amp_extractor.get_markdown()
            if len(amp_text.strip()) >= 300:
                text = amp_text
        except Exception:
            pass

    if len(text.strip()) < 300:
        fallback = readpage.extract_markdown_from_json_ld(html_text)
        if fallback:
            text = fallback

    if len(text.strip()) < 300:
        fallback = readpage.extract_markdown_from_embedded_state(html_text)
        if fallback:
            text = fallback

    return text


def unique_output_path(base_path: Path) -> Path:
    if not base_path.exists():
        return base_path

    stem = base_path.stem
    suffix = base_path.suffix
    parent = base_path.parent

    for index in range(2, 1000):
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate

    raise RuntimeError("Could not create unique output filename")


def extract_read_text_for_url(url: str, timeout: int) -> tuple[str, str]:
    html_text = readpage.fetch_html(url, timeout)
    extractor = readpage.MarkdownExtractor()
    extractor.feed(html_text)
    text = extractor.get_markdown()
    extraction_mode = "html_markdown_extractor"

    if len(text.strip()) < 300:
        try:
            amp_html = readpage.fetch_html(readpage.build_amp_url(url), timeout)
            amp_extractor = readpage.MarkdownExtractor()
            amp_extractor.feed(amp_html)
            amp_text = amp_extractor.get_markdown()
            if len(amp_text.strip()) >= 300:
                text = amp_text
                extraction_mode = "amp_markdown_extractor"
        except Exception:
            pass

    if len(text.strip()) < 300:
        fallback = readpage.extract_markdown_from_json_ld(html_text)
        if fallback:
            text = fallback
            extraction_mode = "jsonld_fallback"

    if len(text.strip()) < 300:
        fallback = readpage.extract_markdown_from_embedded_state(html_text)
        if fallback:
            text = fallback
            extraction_mode = "embedded_state_fallback"

    if len(text.strip()) < 300 or readpage.looks_like_overlay_or_stub(text):
        fallback = readpage.extract_markdown_from_script_strings(html_text)
        if fallback:
            text = fallback
            extraction_mode = "script_strings_fallback"

    return text, extraction_mode


def write_attempt_log(log_dir: Path, source_url: str, selected_links: list[str], results: list[dict]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    source_stem = readpage.webpage_name_from_url(source_url)
    log_path = unique_output_path(log_dir / f"{source_stem}-link-attempts-{timestamp}.txt")

    result_by_url = {entry.get("url", ""): entry for entry in results}
    lines = [
        f"SourceURL: {source_url}",
        f"Timestamp: {datetime.now().isoformat(timespec='seconds')}",
        f"AttemptedCount: {len(selected_links)}",
        "",
    ]

    for index, link in enumerate(selected_links, start=1):
        result = result_by_url.get(link, {})
        lines.append(f"{index}. URL: {link}")
        lines.append(f"   Status: {result.get('status', 'unknown')}")
        lines.append(f"   OutputMD: {result.get('output_path', '')}")
        lines.append(f"   ReadTXT: {result.get('read_text_path', '')}")
        lines.append(f"   ReadChars: {result.get('read_char_count', 0)}")
        lines.append(f"   ExtractionMode: {result.get('extraction_mode', '')}")
        lines.append("")

    log_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return log_path


def run_gen3_read_for_url(url: str, domain: str, area: str, timeout: int, llm_model: str, llm_prompt: str, llm_max_chars: int) -> dict:
    nav = FolderNavigator.from_fixed_point()
    target_dir = nav.get_today_path(area=area, domain=domain, create=True)

    html_text = readpage.fetch_html(url, timeout)
    output_path = target_dir / f"{readpage.build_output_stem(url, html_text)}.md"
    output_path = unique_output_path(output_path)

    text, extraction_mode = extract_read_text_for_url(url=url, timeout=timeout)
    read_text_path = unique_output_path(output_path.with_suffix(".txt"))
    read_text_path.write_text(text, encoding="utf-8")
    text_for_llm = read_text_path.read_text(encoding="utf-8")

    try:
        cleaned = readpage.run_ollama_cleanup(
            text=text_for_llm,
            model=llm_model,
            prompt=llm_prompt,
            timeout=timeout,
            max_chars=llm_max_chars,
        )
        output_path.write_text(cleaned, encoding="utf-8")
        return {
            "url": url,
            "output_path": str(output_path),
            "read_text_path": str(read_text_path),
            "read_char_count": len(text_for_llm),
            "extraction_mode": extraction_mode,
            "status": "ok",
        }
    except Exception as exc:
        return {
            "url": url,
            "output_path": "",
            "read_text_path": str(read_text_path),
            "read_char_count": len(text_for_llm),
            "extraction_mode": extraction_mode,
            "status": f"error: {exc}",
        }


def main():
    parser = argparse.ArgumentParser(
        description="Select 10 relevant page links with LLM, then run Gen3ReadWebpage flow for each selected link"
    )
    parser.add_argument("--url", required=True, help="Source webpage URL")
    parser.add_argument("--domain", required=True, help="Domain folder name under datastore3")
    parser.add_argument("--area", default="mine", help="FolderNavigator area alias (default: mine)")
    parser.add_argument("--count", type=int, default=10, help="Number of links to select and process")
    parser.add_argument("--timeout", type=int, default=30, help="Request and LLM timeout in seconds")
    parser.add_argument("--llm-model", default="gpt-oss:20b", help="Local Ollama model name")
    parser.add_argument(
        "--selector-prompt",
        default="Identify the best related editorial links from the main content of this page.",
        help="Prompt for selecting relevant links",
    )
    parser.add_argument(
        "--llm-prompt",
        default=(
            "Convert the provided extracted webpage text into a clear markdown article. "
            "Preserve the main facts and structure, keep meaningful headings, and avoid hallucinations. "
            "Do not include navigation or boilerplate labels."
        ),
        help="Instruction prompt sent to the LLM for each selected linked page",
    )
    parser.add_argument(
        "--llm-max-chars",
        type=int,
        default=12000,
        help="Maximum input characters sent to the LLM per selected link",
    )
    args = parser.parse_args()

    try:
        nav = FolderNavigator.from_fixed_point()
        nav.validate_domain(args.domain)

        requested_count = max(1, min(args.count, 20))
        timeout = max(10, min(args.timeout, 180))

        source_html = readpage.fetch_html(args.url, timeout)
        source_markdown = build_source_page_markdown(args.url, source_html, timeout)
        source_text = WHITESPACE_PATTERN.sub(" ", source_markdown).strip()

        candidates_from_main = extract_candidate_links_from_markdown(args.url, source_markdown)
        candidates = list(candidates_from_main)
        candidate_source = "main_content_markdown"

        if len(candidates) < requested_count:
            fallback_candidates = extract_candidate_links(args.url, source_html)
            for candidate in fallback_candidates:
                if candidate not in candidates:
                    candidates.append(candidate)
                if len(candidates) >= 150:
                    break
            candidate_source = "main_content_markdown+html_fallback"

        if not candidates:
            raise RuntimeError("No candidate links found on source page")

        selected_links = select_links_with_llm(
            source_url=args.url,
            page_text=source_text,
            candidate_links=candidates,
            candidate_source=candidate_source,
            llm_model=args.llm_model,
            timeout=timeout,
            count=requested_count,
            selector_prompt=args.selector_prompt,
        )

        results = []
        for link in selected_links:
            result = run_gen3_read_for_url(
                url=link,
                domain=args.domain,
                area=args.area,
                timeout=timeout,
                llm_model=args.llm_model,
                llm_prompt=args.llm_prompt,
                llm_max_chars=args.llm_max_chars,
            )
            results.append(result)

        mine_dir = nav.get_today_path(area=args.area, domain=args.domain, create=True)
        attempts_log_path = write_attempt_log(
            log_dir=mine_dir,
            source_url=args.url,
            selected_links=selected_links,
            results=results,
        )

        response = {
            "source_url": args.url,
            "domain": args.domain,
            "area": args.area,
            "selected_count": len(selected_links),
            "selected_links": selected_links,
            "processed": results,
            "attempts_log_path": str(attempts_log_path),
            "status": "ok",
        }
        print(json.dumps(response, ensure_ascii=True))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "source_url": args.url if hasattr(args, "url") else "",
                    "domain": args.domain if hasattr(args, "domain") else "",
                    "error": str(exc),
                    "selected_links": [],
                    "processed": [],
                    "status": "error",
                },
                ensure_ascii=True,
            )
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
