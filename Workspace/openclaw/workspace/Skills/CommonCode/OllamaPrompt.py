#!/usr/bin/env python3
import json
import shutil
import subprocess
import sys
import time
from typing import List, Optional
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_TAGS_URL = f"{OLLAMA_BASE_URL}/api/tags"
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"


def http_get_json(url: str, timeout: int) -> dict:
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def http_post_json(url: str, payload: dict, timeout: int) -> dict:
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def get_installed_models(timeout: int) -> List[str]:
    data = http_get_json(OLLAMA_TAGS_URL, timeout=timeout)
    models = data.get("models", [])
    return [entry.get("name", "") for entry in models if entry.get("name")]


def ollama_is_running(timeout: int = 2) -> bool:
    try:
        get_installed_models(timeout)
        return True
    except Exception:
        return False


def start_ollama_if_needed(wait_seconds: int) -> None:
    if ollama_is_running():
        return

    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        raise RuntimeError("`ollama` command not found on PATH")

    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    subprocess.Popen(
        [ollama_bin, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if ollama_is_running(timeout=2):
            return
        time.sleep(0.5)

    raise RuntimeError(
        "Ollama did not become ready in time. Start manually with `ollama serve`."
    )


def pull_model(model: str) -> None:
    result = subprocess.run(["ollama", "pull", model], capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "unknown pull error").strip()
        raise RuntimeError(f"Failed to pull model `{model}`: {message}")


def select_model(
    requested_model: Optional[str],
    installed_models: List[str],
    preferred_models: List[str],
    auto_pull: bool,
) -> str:
    if requested_model:
        if requested_model in installed_models:
            return requested_model
        if auto_pull:
            pull_model(requested_model)
            return requested_model
        raise RuntimeError(
            f"Requested model `{requested_model}` is not installed. "
            "Use --auto-pull to download it."
        )

    for model in preferred_models:
        if model in installed_models:
            return model

    if installed_models:
        return installed_models[0]

    if auto_pull and preferred_models:
        pull_model(preferred_models[0])
        return preferred_models[0]

    raise RuntimeError(
        "No installed models found. Set --model or use --auto-pull with preferred models."
    )


def run_generation(model: str, prompt: str, timeout: int, temperature: float) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    data = http_post_json(OLLAMA_GENERATE_URL, payload, timeout=timeout)
    response = (data.get("response") or "").strip()
    if not response:
        raise RuntimeError("Ollama returned an empty response")
    return response


def parse_preferred_models(raw: str) -> List[str]:
    return [value.strip() for value in raw.split(",") if value.strip()]


def generate_with_ollama(
    prompt: str,
    requested_model: Optional[str] = None,
    preferred_models: Optional[List[str]] = None,
    auto_pull: bool = False,
    temperature: float = 0.2,
    timeout: int = 120,
    startup_wait: int = 20,
) -> dict:
    if preferred_models is None:
        preferred_models = ["gpt-oss:120b", "gpt-oss:20b", "qwen3-coder-next:q8_0", "llama3.1:8b"]

    start_ollama_if_needed(startup_wait)
    installed_models = get_installed_models(timeout=timeout)
    model = select_model(
        requested_model=requested_model,
        installed_models=installed_models,
        preferred_models=preferred_models,
        auto_pull=auto_pull,
    )
    response = run_generation(
        model=model,
        prompt=prompt,
        timeout=timeout,
        temperature=temperature,
    )
    return {
        "model": model,
        "response": response,
        "base_url": OLLAMA_BASE_URL,
    }


__all__ = [
    "generate_with_ollama",
    "get_installed_models",
    "parse_preferred_models",
    "start_ollama_if_needed",
    "select_model",
    "OLLAMA_BASE_URL",
    "URLError",
    "HTTPError",
]
