"""
Optional LLM helpers for Literature Research Aide (opt-in study aid).

Providers (any combination; auto picks the first ready):
  • ollama     — local models (free). Can be started/stopped by the app.
  • openai     — OpenAI API or any OpenAI-compatible endpoint (OpenRouter,
                 Azure OpenAI-compatible proxies, Groq, etc.)
  • anthropic  — Claude via ANTHROPIC_API_KEY

Extractive key points (summarize.py) remain the default. LLM only rewrites
or answers from the supplied abstract — never invents findings.

Phase R5 policy (do not break without product review):
  • One article at a time (refine / ask) — no whole-library auto-summaries.
  • No AI evidence grades; no silent rewrite of stored key points without an
    explicit user save action; no paywall / full-text scraping.

Settings load from environment, then optional ``user_data/ai_settings.json``
(server-wide deploy file; never commit it).

Ollama lifecycle (start/stop) follows Local-Schedule-Assistant: detached
``ollama serve`` with optional ``OLLAMA_MODELS``, and full stop via pkill /
taskkill so the model runner frees VRAM.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Server-wide optional AI config (keys, models path). Not per-user.
AI_SETTINGS_PATH = Path("user_data") / "ai_settings.json"

_SETTINGS_CACHE: Optional[Dict[str, Any]] = None


class LLMUnavailable(RuntimeError):
    """No provider configured, or a required package is missing."""


class LLMError(RuntimeError):
    """Provider call failed or returned unusable output."""


class RefinedArticle(BaseModel):
    summary: str = Field(
        description="2-4 sentence plain-language summary of what the paper did and found."
    )
    limitations: str = Field(
        default="",
        description="1-2 sentences on main limitations, appropriately hedged.",
    )
    key_points: List[str] = Field(
        description="3-6 short at-a-glance bullet points from the abstract only."
    )


class ArticleAnswer(BaseModel):
    answer: str = Field(description="Direct plain-language answer grounded in the text.")
    quotes: List[str] = Field(
        default_factory=list,
        description="1-3 short verbatim supporting snippets from the abstract.",
    )


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _settings_path() -> Path:
    return AI_SETTINGS_PATH


def load_ai_settings(force: bool = False) -> Dict[str, Any]:
    """Load server AI settings from JSON (empty dict if missing)."""
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is not None and not force:
        return dict(_SETTINGS_CACHE)
    path = _settings_path()
    data: Dict[str, Any] = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception as exc:
            logger.warning("Could not read %s: %s", path, exc)
            data = {}
    _SETTINGS_CACHE = data
    return dict(data)


def save_ai_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Merge updates into ai_settings.json and refresh cache + process env."""
    global _SETTINGS_CACHE
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_ai_settings(force=True)
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "" and key.endswith("_api_key"):
            # Empty string clears stored key
            current.pop(key, None)
            continue
        current[key] = value
    path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    _SETTINGS_CACHE = current
    apply_ai_settings_to_env(current)
    return dict(current)


def apply_ai_settings_to_env(settings: Optional[Dict[str, Any]] = None) -> None:
    """Push file settings into os.environ when env var is unset (env wins)."""
    data = settings if settings is not None else load_ai_settings()
    mapping = {
        "llm_provider": "LLM_PROVIDER",
        "ollama_host": "OLLAMA_HOST",
        "ollama_model": "OLLAMA_MODEL",
        "ollama_models_dir": "OLLAMA_MODELS",
        "anthropic_api_key": "ANTHROPIC_API_KEY",
        "llm_model": "LLM_MODEL",
        "openai_api_key": "OPENAI_API_KEY",
        "openai_base_url": "OPENAI_BASE_URL",
        "openai_model": "OPENAI_MODEL",
        "llm_timeout_seconds": "LLM_TIMEOUT_SECONDS",
    }
    for file_key, env_key in mapping.items():
        if os.getenv(env_key):
            continue
        val = data.get(file_key)
        if val is None or val == "":
            continue
        os.environ[env_key] = str(val)


def public_ai_settings() -> Dict[str, Any]:
    """Settings safe to show in the UI (keys masked)."""
    apply_ai_settings_to_env()
    data = load_ai_settings()
    def mask(key_env: str, file_key: str) -> str:
        raw = _env(key_env) or str(data.get(file_key) or "")
        if not raw:
            return ""
        if len(raw) <= 8:
            return "••••••••"
        return raw[:4] + "…" + raw[-4:]

    return {
        "llm_provider": _env("LLM_PROVIDER", str(data.get("llm_provider") or "auto")) or "auto",
        "ollama_host": _env("OLLAMA_HOST", str(data.get("ollama_host") or "http://localhost:11434")),
        "ollama_model": _env("OLLAMA_MODEL", str(data.get("ollama_model") or "")),
        "ollama_models_dir": _env(
            "OLLAMA_MODELS",
            str(data.get("ollama_models_dir") or ""),
        ),
        "llm_model": _env("LLM_MODEL", str(data.get("llm_model") or "claude-sonnet-4-6")),
        "openai_base_url": _env(
            "OPENAI_BASE_URL",
            str(data.get("openai_base_url") or "https://api.openai.com/v1"),
        ),
        "openai_model": _env("OPENAI_MODEL", str(data.get("openai_model") or "gpt-4o-mini")),
        "anthropic_api_key_set": bool(_env("ANTHROPIC_API_KEY") or data.get("anthropic_api_key")),
        "openai_api_key_set": bool(_env("OPENAI_API_KEY") or data.get("openai_api_key")),
        "anthropic_api_key_masked": mask("ANTHROPIC_API_KEY", "anthropic_api_key"),
        "openai_api_key_masked": mask("OPENAI_API_KEY", "openai_api_key"),
        "llm_timeout_seconds": _env(
            "LLM_TIMEOUT_SECONDS", str(data.get("llm_timeout_seconds") or "120")
        ),
        "ollama_control_allowed": ollama_control_allowed(),
        "settings_path": str(_settings_path()),
    }


def ollama_control_allowed() -> bool:
    """Whether the web UI may start/stop Ollama (default: yes unless disabled)."""
    flag = _env("AI_ALLOW_OLLAMA_CONTROL", "true").lower()
    return flag not in ("0", "false", "no", "off")


# Apply file settings once at import so env-style reads work.
try:
    apply_ai_settings_to_env()
except Exception:
    pass


def provider() -> Optional[str]:
    """Pick active provider: auto prefers Ollama, then OpenAI-compatible, then Anthropic."""
    apply_ai_settings_to_env()
    pref = _env("LLM_PROVIDER", "auto").lower() or "auto"
    has_ollama = bool(_env("OLLAMA_MODEL"))
    has_openai = bool(_env("OPENAI_API_KEY"))
    has_anthropic = bool(_env("ANTHROPIC_API_KEY"))
    if pref in ("ollama", "openai", "anthropic"):
        if pref == "ollama" and has_ollama:
            return "ollama"
        if pref == "openai" and has_openai:
            return "openai"
        if pref == "anthropic" and has_anthropic:
            return "anthropic"
        return None
    # auto
    if has_ollama:
        return "ollama"
    if has_openai:
        return "openai"
    if has_anthropic:
        return "anthropic"
    return None


def is_configured() -> bool:
    return provider() is not None


def _timeout() -> float:
    try:
        return float(_env("LLM_TIMEOUT_SECONDS", "120") or "120")
    except ValueError:
        return 120.0


def list_ollama_models() -> List[str]:
    """Installed model tags via HTTP /api/tags (no CLI — avoids hang)."""
    host = _env("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        import httpx

        r = httpx.get(f"{host}/api/tags", timeout=2.0)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", []) if m.get("name")]
    except Exception:
        return []


def ollama_running() -> bool:
    host = _env("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        import httpx

        r = httpx.get(f"{host}/api/tags", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


def ollama_env_for_serve() -> Dict[str, str]:
    """Environment for `ollama serve` with optional OLLAMA_MODELS."""
    env = os.environ.copy()
    models_dir = _env("OLLAMA_MODELS") or str(load_ai_settings().get("ollama_models_dir") or "")
    models_dir = models_dir.strip()
    if models_dir:
        p = Path(models_dir).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        env["OLLAMA_MODELS"] = str(p)
    return env


def start_ollama() -> Tuple[bool, str]:
    """Launch local Ollama server detached. Returns (ok, message)."""
    if not ollama_control_allowed():
        return False, "Ollama control is disabled (AI_ALLOW_OLLAMA_CONTROL=false)."
    if ollama_running():
        return True, "Ollama is already running."
    binary = shutil.which("ollama")
    if not binary:
        return False, "Ollama not found on PATH. Install from https://ollama.com/download"
    env = ollama_env_for_serve()
    try:
        if platform.system() == "Windows":
            # DETACHED_PROCESS | CREATE_NO_WINDOW
            flags = 0x00000008 | 0x08000000
            subprocess.Popen(
                [binary, "serve"],
                env=env,
                creationflags=flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        else:
            subprocess.Popen(
                [binary, "serve"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    except Exception as exc:
        return False, f"Could not start Ollama: {exc}"

    # Brief wait for the HTTP port.
    for _ in range(20):
        time.sleep(0.25)
        if ollama_running():
            mid = env.get("OLLAMA_MODELS", "")
            msg = "Ollama started."
            if mid:
                msg += f" Models path: {mid}"
            return True, msg
    return True, "Ollama start requested (still warming up — try Refresh in a few seconds)."


def stop_ollama() -> Tuple[bool, str]:
    """Fully stop Ollama server + model runner (frees VRAM). Returns (ok, message)."""
    if not ollama_control_allowed():
        return False, "Ollama control is disabled (AI_ALLOW_OLLAMA_CONTROL=false)."
    try:
        if platform.system() == "Windows":
            flags = 0x08000000  # CREATE_NO_WINDOW
            killed = False
            for image in (
                "ollama app.exe",
                "ollama.exe",
                "llama-server.exe",
                "ollama_llama_server.exe",
            ):
                r = subprocess.run(
                    ["taskkill", "/F", "/T", "/IM", image],
                    capture_output=True,
                    text=True,
                    creationflags=flags,
                )
                if "SUCCESS" in (r.stdout or ""):
                    killed = True
            return (
                (True, "Ollama stopped.")
                if killed
                else (False, "Ollama wasn't running.")
            )
        a = subprocess.run(["pkill", "-f", "ollama serve"], capture_output=True, text=True)
        subprocess.run(["pkill", "-f", "ollama"], capture_output=True, text=True)
        subprocess.run(["pkill", "-f", "llama-server"], capture_output=True, text=True)
        # pkill returns 0 if something was signalled
        if a.returncode == 0 or not ollama_running():
            # Give the process a moment to die
            time.sleep(0.4)
            if ollama_running():
                return False, "Ollama still responds — stop it from the system tray/service."
            return True, "Ollama stopped."
        return False, "Ollama wasn't running."
    except Exception as exc:
        return False, str(exc)


def status() -> Dict[str, Any]:
    """Honest multi-provider status for the UI."""
    apply_ai_settings_to_env()
    selected = provider()
    models = list_ollama_models() if ollama_running() else []
    ollama_on = ollama_running()
    base = {
        "provider": selected,
        "ollama_running": ollama_on,
        "ollama_models": models,
        "ollama_control_allowed": ollama_control_allowed(),
        "configured": is_configured(),
        "settings": public_ai_settings(),
    }
    if selected is None:
        base.update({
            "model": None,
            "reachable": False,
            "model_available": False,
            "detail": (
                "No AI configured. Start Ollama and set a model, or add an "
                "OpenAI-compatible / Anthropic API key on the Account page."
            ),
        })
        return base
    if selected == "ollama":
        model = _env("OLLAMA_MODEL")
        available = any(
            n == model or n.split(":")[0] == model.split(":")[0]
            for n in models
        ) if ollama_on else False
        if not ollama_on:
            detail = "Ollama is not running — use Start Ollama on the Account page."
        elif not available:
            detail = f"Ollama is running but '{model}' is not installed (ollama pull {model})."
        else:
            detail = f"Local AI ready ({model})."
        base.update({
            "model": model,
            "reachable": ollama_on,
            "model_available": available,
            "detail": detail,
        })
        return base
    if selected == "openai":
        model = _env("OPENAI_MODEL", "gpt-4o-mini")
        base_url = _env("OPENAI_BASE_URL", "https://api.openai.com/v1")
        base.update({
            "model": model,
            "reachable": True,
            "model_available": True,
            "detail": f"OpenAI-compatible API ready ({model} @ {base_url}).",
        })
        return base
    # anthropic
    model = _env("LLM_MODEL", "claude-sonnet-4-6")
    base.update({
        "model": model,
        "reachable": True,
        "model_available": True,
        "detail": f"Anthropic API ({model}) configured.",
    })
    return base


_REFINE_SYSTEM = (
    "You are a careful study-aid for students reading academic abstracts. "
    "Summarize ONLY what the abstract states — never invent results, numbers, "
    "populations, or claims that are not present. Be plain-language and concise. "
    "Do NOT invent a study design grade or evidence hierarchy. Hedge appropriately. "
    "This is a study aid, not medical, legal, or professional advice. "
    "Respond with JSON matching the requested schema only."
)

_ASK_SYSTEM = (
    "You answer a student's question about ONE academic paper using ONLY the "
    "title and abstract provided. Quote 1-3 short verbatim snippets that support "
    "your answer. If the abstract does not address the question, say so plainly. "
    "Do not use outside knowledge, do not speculate, and do not give professional advice. "
    "Respond with JSON matching the requested schema only."
)


def refine_article(
    title: str,
    abstract: str,
    existing_key_points: Optional[List[str]] = None,
) -> Dict[str, Any]:
    abstract = (abstract or "").strip()
    if len(abstract) < 40:
        raise LLMError("Abstract is too short to refine with AI.")
    kp_block = ""
    if existing_key_points:
        kp_block = (
            "\nExisting extractive key points (rewrite/improve, still abstract-only):\n"
            + "\n".join(f"- {b}" for b in existing_key_points[:8])
            + "\n"
        )
    prompt = (
        f"Title: {title or 'Untitled'}\n\n"
        f"Abstract:\n{abstract}\n"
        f"{kp_block}\n"
        "Write a faithful plain-language summary, a short limitations note, "
        "and 3-6 bullet key points. Do not invent anything beyond the abstract."
    )
    parsed: RefinedArticle = _structured_call(_REFINE_SYSTEM, prompt, RefinedArticle)
    return {
        "summary": parsed.summary.strip(),
        "limitations": (parsed.limitations or "").strip(),
        "key_points": [p.strip() for p in parsed.key_points if p.strip()][:8],
        "method": "rules+llm",
        "provider": provider(),
    }


def ask_article(question: str, title: str, abstract: str) -> Dict[str, Any]:
    question = (question or "").strip()
    abstract = (abstract or "").strip()
    if len(question) < 3:
        raise LLMError("Ask a longer question.")
    if len(abstract) < 40:
        raise LLMError("Abstract is too short for AI Q&A.")
    prompt = (
        f"Article title: {title or 'Untitled'}\n\n"
        f"Abstract:\n{abstract}\n\n"
        f"Question: {question}"
    )
    parsed: ArticleAnswer = _structured_call(_ASK_SYSTEM, prompt, ArticleAnswer)
    return {
        "answer": parsed.answer.strip(),
        "quotes": [q.strip() for q in parsed.quotes if q.strip()][:3],
        "method": "rules+llm",
        "provider": provider(),
    }


def _structured_call(system: str, prompt: str, schema_model: Type[BaseModel]):
    selected = provider()
    if selected is None:
        raise LLMUnavailable(
            "No LLM provider configured. Start Ollama or set an API key."
        )
    if selected == "ollama":
        # Fail fast with 503-class unavailable when the local daemon is down.
        if not ollama_running():
            raise LLMUnavailable(
                "Ollama is not running. Start it from Account → AI study aid, "
                "or switch to an API key provider."
            )
        return _structured_ollama(system, prompt, schema_model)
    if selected == "openai":
        return _structured_openai(system, prompt, schema_model)
    return _structured_anthropic(system, prompt, schema_model)


def _is_connection_failure(exc: BaseException) -> bool:
    """True when the provider is down / unreachable (map to LLMUnavailable → 503)."""
    import httpx

    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.TimeoutException)):
        return True
    msg = str(exc).lower()
    needles = (
        "connection refused",
        "connect error",
        "connecttimeout",
        "timed out",
        "name or service not known",
        "temporary failure in name resolution",
        "network is unreachable",
        "failed to establish",
        "connection reset",
    )
    return any(n in msg for n in needles)


def _structured_ollama(system: str, prompt: str, schema_model: Type[BaseModel]):
    import httpx

    host = _env("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = _env("OLLAMA_MODEL")
    try:
        response = httpx.post(
            f"{host}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "format": schema_model.model_json_schema(),
                "stream": False,
                "options": {"temperature": 0.2},
            },
            timeout=_timeout(),
        )
        response.raise_for_status()
        content = (response.json().get("message") or {}).get("content") or ""
    except Exception as exc:
        if _is_connection_failure(exc):
            raise LLMUnavailable(
                "Ollama is not running or not reachable. "
                "Start it from Account → AI study aid, or use an API key."
            ) from exc
        raise LLMError(f"Ollama request failed: {exc}") from exc
    return _parse_schema(content, schema_model, "Ollama")


def _structured_openai(system: str, prompt: str, schema_model: Type[BaseModel]):
    """OpenAI Chat Completions API or compatible (OpenRouter, Groq, etc.)."""
    import httpx

    api_key = _env("OPENAI_API_KEY")
    if not api_key:
        raise LLMUnavailable("OPENAI_API_KEY is not set.")
    base = _env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = _env("OPENAI_MODEL", "gpt-4o-mini")
    schema = json.dumps(schema_model.model_json_schema())
    user = (
        f"{prompt}\n\n"
        f"Return ONLY a JSON object matching this schema (no markdown fences):\n{schema}"
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # OpenRouter optional branding headers (harmless elsewhere)
    if "openrouter.ai" in base:
        headers["HTTP-Referer"] = _env("OPENROUTER_SITE_URL", "http://localhost")
        headers["X-Title"] = _env("OPENROUTER_APP_NAME", "Literature Research Aide")
    body: Dict[str, Any] = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    # Prefer JSON mode when supported (OpenAI + many clones)
    body["response_format"] = {"type": "json_object"}
    try:
        response = httpx.post(
            f"{base}/chat/completions",
            headers=headers,
            json=body,
            timeout=_timeout(),
        )
        if response.status_code >= 400:
            # Retry without response_format for picky proxies
            body.pop("response_format", None)
            response = httpx.post(
                f"{base}/chat/completions",
                headers=headers,
                json=body,
                timeout=_timeout(),
            )
        response.raise_for_status()
        data = response.json()
        content = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            or ""
        )
    except Exception as exc:
        raise LLMError(f"OpenAI-compatible request failed: {exc}") from exc
    return _parse_schema(content, schema_model, "OpenAI-compatible")


def _structured_anthropic(system: str, prompt: str, schema_model: Type[BaseModel]):
    try:
        import anthropic
    except ImportError as exc:
        raise LLMUnavailable("The 'anthropic' package is not installed.") from exc

    client = anthropic.Anthropic(api_key=_env("ANTHROPIC_API_KEY"))
    model = _env("LLM_MODEL", "claude-sonnet-4-6")
    schema = json.dumps(schema_model.model_json_schema())
    user = (
        f"{prompt}\n\n"
        f"Return ONLY a JSON object matching this schema (no markdown fences):\n{schema}"
    )
    try:
        message = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc

    parts = []
    for block in message.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    content = "\n".join(parts).strip()
    return _parse_schema(content, schema_model, "Anthropic")


def _parse_schema(content: str, schema_model: Type[BaseModel], label: str):
    cleaned = _extract_json_object(content)
    try:
        return schema_model.model_validate_json(cleaned)
    except Exception as exc:
        raise LLMError(f"{label} returned no parseable output: {exc}") from exc


def _extract_json_object(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text
