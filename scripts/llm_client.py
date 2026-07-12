"""Shared text generation client for wiki LLM workflows."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Dict, Mapping, Optional

import requests


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str
    done_reason: str = ""


class LLMClientError(RuntimeError):
    """Stable, secret-safe error raised by the shared LLM boundary."""


def _clean_endpoint(value: Any) -> str:
    return str(value).strip().rstrip("/")


def _safe_error(provider: str, model: str, message: str) -> LLMClientError:
    return LLMClientError(f"{provider}/{model}: {message}")


def _options(
    cfg: Mapping[str, Any],
    *,
    temperature: Optional[float] = None,
    num_predict: Optional[int] = None,
    num_ctx: Optional[int] = None,
) -> Dict[str, Any]:
    opts: Dict[str, Any] = {}
    temp = cfg.get("temperature") if temperature is None else temperature
    predict = cfg.get("num_predict") if num_predict is None else num_predict
    ctx = cfg.get("num_ctx") if num_ctx is None else num_ctx
    if temp is not None:
        opts["temperature"] = temp
    if predict is not None:
        opts["num_predict"] = predict
    if ctx is not None:
        opts["num_ctx"] = ctx
    return opts


def _normalize_text(provider: str, model: str, text: Any) -> str:
    if not isinstance(text, str):
        raise _safe_error(provider, model, "non-text response content")
    normalized = text.strip()
    if not normalized:
        raise _safe_error(provider, model, "blank response text")
    return normalized


def _post_json(
    provider: str,
    model: str,
    url: str,
    *,
    payload: Mapping[str, Any],
    timeout: Any,
    headers: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.Timeout as exc:
        raise _safe_error(provider, model, "request timed out") from exc
    except requests.ConnectionError as exc:
        raise _safe_error(provider, model, "connection failed") from exc
    except requests.HTTPError as exc:
        raise _safe_error(provider, model, f"HTTP status {getattr(resp, 'status_code', 'unknown')}") from exc
    except Exception as exc:
        raise _safe_error(provider, model, "invalid response") from exc

    if not isinstance(data, dict):
        raise _safe_error(provider, model, "malformed response JSON")
    return data


def _generate_ollama(
    prompt: str,
    cfg: Mapping[str, Any],
    *,
    temperature: Optional[float],
    num_predict: Optional[int],
    num_ctx: Optional[int],
) -> LLMResult:
    provider = "ollama"
    model = str(cfg.get("model", "")).strip()
    url = f"{_clean_endpoint(cfg.get('host') or cfg.get('base_url') or 'http://localhost:11434')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": _options(cfg, temperature=temperature, num_predict=num_predict, num_ctx=num_ctx),
    }
    data = _post_json(provider, model, url, payload=payload, timeout=cfg.get("timeout", 180))
    text = _normalize_text(provider, model, data.get("response"))
    return LLMResult(
        text=text,
        provider=provider,
        model=model,
        done_reason=str(data.get("done_reason", "") or ""),
    )


def _generate_openrouter(
    prompt: str,
    cfg: Mapping[str, Any],
    *,
    temperature: Optional[float],
    num_predict: Optional[int],
    attribution: Optional[Mapping[str, str]],
) -> LLMResult:
    provider = "openrouter"
    model = str(cfg.get("model", "")).strip()
    api_key_env = str(cfg.get("api_key_env", "OPENROUTER_API_KEY")).strip()
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        raise _safe_error(provider, model, f"missing API key environment variable {api_key_env}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if attribution:
        if attribution.get("http_referer"):
            headers["HTTP-Referer"] = str(attribution["http_referer"])
        if attribution.get("title"):
            headers["X-Title"] = str(attribution["title"])

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    temp = cfg.get("temperature") if temperature is None else temperature
    predict = cfg.get("num_predict") if num_predict is None else num_predict
    if temp is not None:
        payload["temperature"] = temp
    if predict is not None:
        payload["max_tokens"] = predict

    url = f"{_clean_endpoint(cfg.get('base_url') or 'https://openrouter.ai/api/v1')}/chat/completions"
    data = _post_json(
        provider,
        model,
        url,
        payload=payload,
        headers=headers,
        timeout=cfg.get("timeout", 180),
    )
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise _safe_error(provider, model, "empty choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise _safe_error(provider, model, "malformed choice")
    message = first.get("message")
    if not isinstance(message, dict):
        raise _safe_error(provider, model, "malformed message")
    text = _normalize_text(provider, model, message.get("content"))
    return LLMResult(
        text=text,
        provider=provider,
        model=model,
        done_reason=str(first.get("finish_reason", "") or ""),
    )


def generate_text(
    prompt: str,
    llm_config: Mapping[str, Any],
    *,
    temperature: Optional[float] = None,
    num_predict: Optional[int] = None,
    num_ctx: Optional[int] = None,
    attribution: Optional[Mapping[str, str]] = None,
) -> LLMResult:
    """Generate text through the configured provider without fallback chaining."""
    provider = str(llm_config.get("provider", "ollama")).strip().lower()
    model = str(llm_config.get("model", "")).strip()
    if provider == "ollama":
        return _generate_ollama(
            prompt,
            llm_config,
            temperature=temperature,
            num_predict=num_predict,
            num_ctx=num_ctx,
        )
    if provider == "openrouter":
        return _generate_openrouter(
            prompt,
            llm_config,
            temperature=temperature,
            num_predict=num_predict,
            attribution=attribution,
        )
    raise _safe_error(provider or "unknown", model, "unsupported provider")
