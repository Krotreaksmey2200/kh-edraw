"""Gemini model discovery helpers."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

GEMINI_MODELS_API_VERSION = "v1beta"
GENERATE_CONTENT_METHOD = "generateContent"


@dataclass(frozen=True, slots=True)
class GeminiModel:
    """Represents a single Gemini model returned by the API."""

    id: str
    name: str
    display_name: str
    description: str
    input_token_limit: int | None
    output_token_limit: int | None
    methods: tuple[str, ...]


def fetch_gemini_generate_models(
    api_key: str,
    *,
    api_version: str = GEMINI_MODELS_API_VERSION,
    timeout: int = 30,
) -> list[GeminiModel]:
    """Return Gemini models that can be used with ``generateContent``."""
    key = (api_key or "").strip()
    if not key:
        raise ValueError("Missing Gemini API key.")

    models: list[GeminiModel] = []
    page_token: str | None = None

    while True:
        params: dict[str, str] = {"key": key}
        if page_token:
            params["pageToken"] = page_token

        url = (
            f"https://generativelanguage.googleapis.com/{api_version}/models"
            f"?{urllib.parse.urlencode(params)}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "eDraw/1.0"})

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(_format_http_error(exc)) from exc

        for raw in body.get("models", []):
            model = normalize_gemini_model(raw)
            if model is not None:
                models.append(model)

        page_token = body.get("nextPageToken")
        if not page_token:
            break

    return models


def normalize_gemini_model(raw_model: dict[str, Any]) -> GeminiModel | None:
    """Normalise a raw model dict into a ``GeminiModel`` (or ``None``)."""
    name = str(raw_model.get("name", "")).strip()
    if not name:
        return None

    model_id = name.removeprefix("models/")

    display_name = str(raw_model.get("displayName", "")).strip() or model_id

    methods = tuple(
        raw_model.get("supportedGenerationMethods", [])
    )

    description = str(raw_model.get("description", "")).strip()

    return GeminiModel(
        id=model_id,
        name=name,
        display_name=display_name,
        description=description,
        input_token_limit=_as_int(raw_model.get("inputTokenLimit")),
        output_token_limit=_as_int(raw_model.get("outputTokenLimit")),
        methods=methods,
    )


def model_sort_key(model: GeminiModel) -> tuple:
    """Return a sort key that puts the most useful models first."""
    model_id = model.id
    display_name = model.display_name
    version_score = extract_version_score(model_id, display_name)
    date_score = extract_date_score(model_id, display_name)
    text = f"{model_id} {display_name}".lower()
    is_preview = "preview" in text
    is_latest = "latest" in text
    return (
        version_score,
        date_score,
        0 if is_preview else 1,
        0 if is_latest else 1,
        display_name.lower(),
    )


def extract_version_score(model_id: str, display_name: str) -> int:
    """Extract a numeric version score for sorting."""
    text = f"{model_id} {display_name}".lower()
    if "latest" in text:
        return -1
    match = re.search(r"(\d+)\.(\d+)", text)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2))
        return major * 100 + minor
    match = re.search(r"(?:gemini|gemma|lyria)-(\d+)", text)
    if match:
        major = int(match.group(1))
        return major * 100
    return 0


def extract_date_score(model_id: str, display_name: str) -> int:
    """Extract a date-based score for sorting."""
    text = f"{model_id} {display_name}".lower()
    # Pattern: MM-YYYY
    match = re.search(r"(\d{2})-(\d{4})", text)
    if match:
        month = int(match.group(1))
        year = int(match.group(2))
        return year * 100 + month
    # Pattern: mon-YY-YYYY or mon-YYYY
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4,
        "may": 5, "jun": 6, "jul": 7, "aug": 8,
        "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    match = re.search(
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)-\d{1,2}-(\d{4})",
        text,
    )
    if match:
        month = month_map[match.group(1)]
        year = int(match.group(2))
        return year * 100 + month
    return 0


def format_model_label(model: GeminiModel) -> str:
    """Return a human-readable label for *model*."""
    if model.display_name.lower() == model.id.lower():
        return model.id
    return f"{model.display_name} ({model.id})"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_http_error(exc: urllib.error.HTTPError) -> str:
    message = f"HTTP {exc.code}"
    try:
        body = exc.read().decode("utf-8", errors="replace")
        data = json.loads(body)
        api_message = data.get("error", {}).get("message")
        if api_message:
            message = f"{message}: {api_message}"
    except Exception:
        pass
    return message


# ---------------------------------------------------------------------------
# Fallback and Resilience Helpers
# ---------------------------------------------------------------------------

FALLBACK_GEMINI_MODELS = (
    "gemini-pro-latest",
    "gemini-3.1-pro-preview",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
)


def get_candidate_models(primary_model: str | None = None) -> list[str]:
    """Return an ordered list of Gemini models to try, starting with primary_model."""
    candidates: list[str] = []
    if primary_model:
        clean = primary_model.strip().removeprefix("models/")
        # Map deprecated models to modern equivalents
        if clean in ("gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash", "gemini-2.0-pro", "gemini-2.5-pro", "gemini-2.5-flash"):
            clean = "gemini-pro-latest"
        if clean:
            candidates.append(clean)
    for fb in FALLBACK_GEMINI_MODELS:
        if fb not in candidates:
            candidates.append(fb)
    return candidates


def ensure_png_bytes(obj: Any) -> bytes | None:
    """Convert QPixmap, QImage, PIL.Image, or bytes into valid PNG bytes."""
    if obj is None:
        return None
    if isinstance(obj, (bytes, bytearray)):
        return bytes(obj) if len(obj) > 0 else None
    if hasattr(obj, "save"):
        from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        obj.save(buf, "PNG")
        data = bytes(ba.data())
        return data if len(data) > 0 else None
    if hasattr(obj, "tobytes"):
        import io
        buf = io.BytesIO()
        obj.save(buf, format="PNG")
        data = buf.getvalue()
        return data if len(data) > 0 else None
    return None


def is_fallback_error(exc: Exception) -> bool:
    """Check if the exception is due to high demand (503), deprecation (404), or quota (429)."""
    err_str = str(exc).lower()
    return any(keyword in err_str for keyword in (
        "503", "unavailable", "high demand", "spikes in demand",
        "404", "not_found", "no longer available",
        "429", "resource_exhausted", "quota", "rate limit",
        "overloaded", "temporarily unavailable", "deadline exceeded",
    ))


def call_gemini_generate_with_fallback(
    api_key: str,
    model: str,
    contents: Any,
    config: Any = None,
    log_fn: Any = None,
    timeout_ms: int = 60000,
) -> tuple[str, str]:
    """Call Gemini generate_content with automatic model failover on 503/404/429.
    
    Returns (response_text, model_used).
    """
    import time
    from google import genai
    from google.genai import types

    if log_fn is None:
        log_fn = lambda msg: None

    candidates = get_candidate_models(model)
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms))
    last_err: Exception | None = None

    for m_idx, m in enumerate(candidates):
        is_last_model = (m_idx == len(candidates) - 1)
        max_attempts = 1 if not is_last_model else 2
        for attempt in range(1, max_attempts + 1):
            try:
                log_fn(f"Calling Gemini ({m})...")
                kwargs = {"model": m, "contents": contents}
                if config is not None:
                    kwargs["config"] = config
                resp = client.models.generate_content(**kwargs)
                text = (resp.text or "").strip()
                return text, m
            except Exception as exc:
                last_err = exc
                err_msg = str(exc)
                log_fn(f"Gemini {m} error: {err_msg[:120]}")
                if is_fallback_error(exc) and not is_last_model:
                    next_model = candidates[m_idx + 1]
                    log_fn(f"Switching to fallback model: {next_model}...")
                    break
                time.sleep(1.0)

    if last_err:
        raise last_err
    raise RuntimeError("Gemini failed to generate content.")

