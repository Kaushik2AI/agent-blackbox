"""Builds the real-model adapter from settings (OpenAI-compatible endpoint, Qwen by
default). Everything model-specific stays in agent_harness.llm."""

from __future__ import annotations

from urllib.parse import urlparse

from agent_harness.llm import LLMConfig, OpenAICompatModel

from app.config import Settings, get_settings


def llm_available(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(settings.llm_api_key and settings.llm_model and settings.llm_base_url)


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_status_cache: dict[str, tuple[float, tuple[str, str, str]]] = {}


def _is_local(settings: Settings) -> bool:
    return urlparse(settings.llm_base_url).hostname in _LOCAL_HOSTS


def _probe(settings: Settings) -> tuple[str, str, str]:
    """(state, label, model id) of a model server on this machine (`make qwen-setup`):
    it may still be loading weights, or not be running at all."""
    import time

    import httpx

    base = settings.llm_base_url.rstrip("/")
    now = time.monotonic()
    cached = _status_cache.get(base)
    if cached and now - cached[0] < 3.0:
        return cached[1]
    root = base[: -len("/v1")] if base.endswith("/v1") else base
    label, model = settings.llm_label or settings.llm_model, settings.llm_model
    try:
        body = httpx.get(root + "/health", timeout=1.5).json()
        state = {"ready": "ready", "loading": "loading"}.get(body.get("status"), "offline")
        label = body.get("label") or label
        model = body.get("model") or model
    except (httpx.HTTPError, ValueError):
        state = "offline"
    result = (state, label, model)
    _status_cache[base] = (now, result)
    return result


def llm_status(settings: Settings | None = None) -> tuple[str, str]:
    """(state, label) for the live page. state: "ready", "loading", "offline" or "none".
    A hosted API is assumed ready when a key is set."""
    settings = settings or get_settings()
    if not llm_available(settings):
        return "none", settings.llm_label or settings.llm_model
    if not _is_local(settings):
        return "ready", settings.llm_label or settings.llm_model
    state, label, _ = _probe(settings)
    return state, label


def _model_id(settings: Settings) -> str:
    # A local server reports the model it actually loaded (QWEN_MODEL=auto picks one by
    # hardware), so traces and replay checks name the real model.
    if _is_local(settings):
        state, _, model = _probe(settings)
        if state == "ready":
            return model
    return settings.llm_model


def llm_model_name(settings: Settings | None = None) -> str:
    return f"llm:{_model_id(settings or get_settings())}"


def build_llm(settings: Settings | None = None) -> OpenAICompatModel:
    settings = settings or get_settings()
    if not llm_available(settings):
        raise RuntimeError("no model API key configured (set LLM_API_KEY)")
    headers = {}
    if "openrouter.ai" in settings.llm_base_url:
        # Optional attribution headers OpenRouter documents for app listings.
        headers = {"X-Title": "Agent BlackBox demo"}
    return OpenAICompatModel(
        LLMConfig(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=_model_id(settings),
            label=settings.llm_label,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout_s=settings.llm_timeout_s,
            extra_headers=headers,
        )
    )


def llm_hosts(settings: Settings | None = None) -> list[tuple[str, int]]:
    """Network destinations a real-model replay may reach: the model API and, if the
    process must go through an HTTPS proxy, that proxy. Nothing else."""
    import os

    settings = settings or get_settings()
    hosts = []
    url = urlparse(settings.llm_base_url)
    if url.hostname:
        hosts.append((url.hostname, url.port or (443 if url.scheme == "https" else 80)))
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        p = urlparse(proxy)
        if p.hostname:
            hosts.append((p.hostname, p.port or 80))
    return hosts
