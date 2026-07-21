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
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Server-wide optional AI config (keys, models path). Not per-user.
AI_SETTINGS_PATH = Path("user_data") / "ai_settings.json"

_SETTINGS_CACHE: Optional[Dict[str, Any]] = None

# Built-in local service (Ollama under the hood; keep UI wording generic).
# hold_count: concurrent Refine/Ask ops share one started process; stop only
# when the last op finishes. _started_by_app: only stop what we started.
_builtin_lock = threading.Lock()
_builtin_hold_count = 0
_builtin_started_by_app = False


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


def study_aid_mode() -> str:
    """Student-facing mode: built_in (local service) or api_key (cloud)."""
    apply_ai_settings_to_env()
    pref = (_env("LLM_PROVIDER", "auto") or "auto").lower()
    if pref == "ollama":
        return "built_in"
    if pref in ("openai", "anthropic"):
        return "api_key"
    # auto: prefer built-in when a local model is configured, else API keys.
    if _env("OLLAMA_MODEL") or load_ai_settings().get("ollama_model"):
        return "built_in"
    if _env("OPENAI_API_KEY") or _env("ANTHROPIC_API_KEY"):
        return "api_key"
    if load_ai_settings().get("openai_api_key") or load_ai_settings().get("anthropic_api_key"):
        return "api_key"
    return "built_in"


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
        "settings_write_allowed": ai_settings_write_allowed(),
        "study_aid_mode": study_aid_mode(),
        "settings_path": str(_settings_path()),
    }


def ollama_control_allowed() -> bool:
    """Whether the app may start/stop the built-in local service (default: yes)."""
    flag = _env("AI_ALLOW_OLLAMA_CONTROL", "true").lower()
    return flag not in ("0", "false", "no", "off")


def ai_settings_write_allowed() -> bool:
    """Whether authenticated users may POST /api/ai/settings (default: yes).

    Set AI_ALLOW_SETTINGS_WRITE=false on multi-user shared hosts so students
    cannot change server-wide keys; configure via env / ai_settings.json only.
    """
    flag = _env("AI_ALLOW_SETTINGS_WRITE", "true").lower()
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
    # Built-in: model may be filled after the local service starts (first installed tag).
    has_ollama = bool(_env("OLLAMA_MODEL") or load_ai_settings().get("ollama_model"))
    has_openai = bool(_env("OPENAI_API_KEY"))
    has_anthropic = bool(_env("ANTHROPIC_API_KEY"))
    if pref in ("ollama", "openai", "anthropic"):
        if pref == "ollama":
            # Built-in mode is selected even before a model tag is known — ensure
            # will pick the first installed model after the service starts.
            return "ollama" if (has_ollama or ollama_control_allowed()) else None
        if pref == "openai" and has_openai:
            return "openai"
        if pref == "anthropic" and has_anthropic:
            return "anthropic"
        return None
    # auto: only claim ollama when a model is configured (or file has one).
    if has_ollama:
        return "ollama"
    if has_openai:
        return "openai"
    if has_anthropic:
        return "anthropic"
    return None


def is_configured() -> bool:
    return provider() is not None


def _ensure_ollama_model_env() -> Optional[str]:
    """Return a usable model tag, preferring env/settings, else first installed."""
    apply_ai_settings_to_env()
    model = _env("OLLAMA_MODEL") or str(load_ai_settings().get("ollama_model") or "").strip()
    if model:
        os.environ["OLLAMA_MODEL"] = model
        return model
    models = list_ollama_models()
    if models:
        os.environ["OLLAMA_MODEL"] = models[0]
        return models[0]
    return None


def ensure_builtin_service() -> Tuple[bool, str]:
    """Start the built-in local study aid if needed and take a hold.

    Used by run_with_ephemeral_builtin for Refine/Ask (start → work → release).
    Concurrent ops share one process via hold_count; we only stop what we started.
    """
    global _builtin_hold_count, _builtin_started_by_app
    if provider() != "ollama":
        return True, "Using cloud API study aid."
    if not ollama_control_allowed() and not ollama_running(force=True):
        return False, (
            "Built-in study aid is not available on this server. "
            "Ask a teacher to enable it, or switch to API key mode on Account."
        )
    with _builtin_lock:
        was_running = ollama_running(force=True)
        if not was_running:
            if not ollama_control_allowed():
                return False, (
                    "Built-in study aid is stopped and this server cannot start it. "
                    "Use API key mode on Account, or ask a teacher for help."
                )
            ok, msg = start_ollama()
            if not ok:
                friendly = msg
                low = msg.lower()
                if "not found" in low or "path" in low:
                    friendly = (
                        "Built-in study aid is not installed on this computer. "
                        "Use API key mode on Account, or ask a teacher."
                    )
                elif "disabled" in low:
                    friendly = (
                        "Built-in study aid is disabled on this server. "
                        "Use API key mode on Account."
                    )
                return False, friendly
            _builtin_started_by_app = True
        model = _ensure_ollama_model_env()
        if not model:
            return False, (
                "Built-in study aid has no model installed yet. "
                "Ask a teacher to install a model, or use API key mode."
            )
        _builtin_hold_count += 1
        return True, "Built-in study aid ready."


def release_builtin_service() -> Tuple[bool, str]:
    """Drop a hold; stop the local service when no holds remain and we started it."""
    global _builtin_hold_count, _builtin_started_by_app
    with _builtin_lock:
        _builtin_hold_count = max(0, _builtin_hold_count - 1)
        if _builtin_hold_count > 0:
            return True, "Study aid still in use."
        if not _builtin_started_by_app:
            return True, "Study aid left as it was (not started by this app)."
        if not ollama_control_allowed():
            _builtin_started_by_app = False
            return True, "Study aid hold released."
        ok, msg = stop_ollama()
        _builtin_started_by_app = False
        return ok, (
            "Built-in study aid stopped."
            if ok
            else (msg or "Could not stop built-in study aid.")
        )


def run_with_ephemeral_builtin(fn: Callable[[], Any]) -> Any:
    """Start built-in if needed, run fn, then release (stops when last op finishes)."""
    if provider() != "ollama":
        return fn()
    ok, msg = ensure_builtin_service()
    if not ok:
        raise LLMUnavailable(msg)
    try:
        return fn()
    finally:
        release_builtin_service()


def _timeout() -> float:
    try:
        return float(_env("LLM_TIMEOUT_SECONDS", "120") or "120")
    except ValueError:
        return 120.0


# One /api/tags request answers both "running?" and "which models?". Cached
# briefly so a status() call (or rapid Account refreshes) probes once instead
# of three times — and a down service costs one timeout, not several.
OLLAMA_PROBE_TTL_SECONDS = 3.0
_probe_lock = threading.Lock()
_probe_cache: Dict[str, Any] = {"at": 0.0, "host": None, "running": False, "models": []}


def _probe_ollama(force: bool = False) -> Tuple[bool, List[str]]:
    """Probe Ollama via HTTP /api/tags (no CLI — avoids hang).

    Returns (running, model_tags). Control-flow decisions (start/stop waits,
    ephemeral auto-start) must pass force=True; the cache is for UI status.
    """
    host = _env("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    with _probe_lock:
        fresh = (
            _probe_cache["host"] == host
            and time.monotonic() - _probe_cache["at"] < OLLAMA_PROBE_TTL_SECONDS
        )
        if fresh and not force:
            return _probe_cache["running"], list(_probe_cache["models"])
    try:
        import httpx

        r = httpx.get(f"{host}/api/tags", timeout=2.0)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", []) if m.get("name")]
        running = True
    except Exception:
        running, models = False, []
    with _probe_lock:
        _probe_cache.update(
            {"at": time.monotonic(), "host": host, "running": running, "models": models}
        )
    return running, models


def list_ollama_models() -> List[str]:
    """Installed model tags (cached probe; see _probe_ollama)."""
    return _probe_ollama()[1]


def ollama_running(force: bool = False) -> bool:
    return _probe_ollama(force)[0]


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
    if ollama_running(force=True):
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
        if ollama_running(force=True):
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
        if a.returncode == 0 or not ollama_running(force=True):
            # Give the process a moment to die
            time.sleep(0.4)
            if ollama_running(force=True):
                return False, "Ollama still responds — stop it from the system tray/service."
            return True, "Ollama stopped."
        return False, "Ollama wasn't running."
    except Exception as exc:
        return False, str(exc)


def status() -> Dict[str, Any]:
    """Honest multi-provider status for the UI (student copy avoids engine names)."""
    apply_ai_settings_to_env()
    selected = provider()
    ollama_on, models = _probe_ollama()
    mode = study_aid_mode()
    base = {
        "provider": selected,
        "study_aid_mode": mode,
        "ollama_running": ollama_on,
        "builtin_running": ollama_on,
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
                "No AI study aid configured. On Account, choose Built-in study aid "
                "or add a cloud API key."
            ),
        })
        return base
    if selected == "ollama":
        model = _env("OLLAMA_MODEL") or str(load_ai_settings().get("ollama_model") or "")
        available = any(
            n == model or n.split(":")[0] == (model.split(":")[0] if model else "")
            for n in models
        ) if (ollama_on and model) else False
        if mode == "built_in":
            if not ollama_control_allowed() and not ollama_on:
                detail = "Built-in study aid is unavailable on this server."
            elif not model and not models:
                detail = (
                    "Built-in study aid is selected — it starts when you Refine or Ask "
                    "(a model must be installed on the server), then stops."
                )
            else:
                detail = (
                    "Built-in study aid is selected. It starts for each Refine or Ask "
                    "on Search, then stops when that request finishes."
                )
        else:
            detail = "Local study aid selected."
        base.update({
            "model": model or None,
            "reachable": ollama_on,
            "model_available": available or bool(model) or ollama_control_allowed(),
            "detail": detail,
        })
        return base
    if selected == "openai":
        model = _env("OPENAI_MODEL", "gpt-4o-mini")
        base.update({
            "model": model,
            "reachable": True,
            "model_available": True,
            "detail": f"Cloud API study aid ready ({model}).",
        })
        return base
    # anthropic
    model = _env("LLM_MODEL", "claude-sonnet-4-6")
    base.update({
        "model": model,
        "reachable": True,
        "model_available": True,
        "detail": f"Cloud API study aid ready ({model}).",
    })
    return base


_REFINE_SYSTEM = (
    "You are a careful classroom study aid for high school and early college "
    "students using a literature research app.\n\n"
    "CONTEXT / ROLE:\n"
    "- The student selected ONE paper from their personal library in this app.\n"
    "- You are given that paper's title and abstract only (not the full PDF or "
    "paywalled text). Treat that supplied text as your entire knowledge of the paper.\n"
    "- Your job is to help them understand and take notes on this selected paper: "
    "a plain-language summary, honest limitations, and short key points.\n\n"
    "RULES:\n"
    "- Use ONLY the title and abstract provided in the user message. Never invent "
    "results, numbers, populations, methods, or claims that are not there.\n"
    "- If the abstract is vague, say so; do not fill gaps with outside knowledge.\n"
    "- Write clear language suitable for high school. Be concise.\n"
    "- Do NOT invent a study design grade, clinical evidence level (A–D), or "
    "quality score.\n"
    "- Do NOT give medical, legal, or professional advice.\n"
    "- Respond with JSON matching the requested schema only (no markdown fences)."
)

_ASK_SYSTEM = (
    "You are a careful classroom study aid for high school and early college "
    "students using a literature research app.\n\n"
    "CONTEXT / ROLE:\n"
    "- The student selected ONE paper from their personal library and typed a question.\n"
    "- You are given that paper's title and abstract only (not the full PDF).\n"
    "- Answer only from that supplied text.\n\n"
    "RULES:\n"
    "- Use ONLY the title and abstract in the user message. Never invent facts.\n"
    "- Quote 1–3 short verbatim snippets from the abstract when they support the answer.\n"
    "- If the abstract does not address the question, say so plainly.\n"
    "- No outside knowledge, no speculation, no medical/legal/professional advice.\n"
    "- No evidence grades (A–D) or quality scores.\n"
    "- Respond with JSON matching the requested schema only (no markdown fences)."
)


def refine_article(
    title: str,
    abstract: str,
    existing_key_points: Optional[List[str]] = None,
    *,
    source: str = "",
    article_id: str = "",
) -> Dict[str, Any]:
    abstract = (abstract or "").strip()
    if len(abstract) < 40:
        raise LLMError("Abstract is too short to refine with AI.")
    kp_block = ""
    if existing_key_points:
        kp_block = (
            "\nExisting extractive key points from the app (improve if useful, "
            "still abstract-only; do not invent beyond the abstract):\n"
            + "\n".join(f"- {b}" for b in existing_key_points[:8])
            + "\n"
        )
    loc = ""
    if source or article_id:
        loc = f"Library record: source={source or 'unknown'}, id={article_id or 'unknown'}\n"
    prompt = (
        "TASK: The student clicked “Refine with AI” on the paper below. "
        "Help them understand THIS selected paper only.\n\n"
        f"{loc}"
        f"SELECTED PAPER TITLE:\n{title or 'Untitled'}\n\n"
        f"SELECTED PAPER ABSTRACT (sole evidence — do not go beyond this text):\n"
        f"{abstract}\n"
        f"{kp_block}\n"
        "OUTPUT REQUIREMENTS:\n"
        "- summary: 2–4 plain-language sentences of what the paper did and found "
        "(only if stated in the abstract).\n"
        "- limitations: 1–2 sentences on limits or missing info, hedged honestly.\n"
        "- key_points: 3–6 short bullets a student could paste into notes.\n"
        "Stay faithful to the abstract. If something is unclear, say so."
    )
    parsed: RefinedArticle = _structured_call(_REFINE_SYSTEM, prompt, RefinedArticle)
    return {
        "summary": parsed.summary.strip(),
        "limitations": (parsed.limitations or "").strip(),
        "key_points": [p.strip() for p in parsed.key_points if p.strip()][:8],
        "method": "rules+llm",
        "provider": provider(),
    }


def ask_article(
    question: str,
    title: str,
    abstract: str,
    *,
    source: str = "",
    article_id: str = "",
) -> Dict[str, Any]:
    question = (question or "").strip()
    abstract = (abstract or "").strip()
    if len(question) < 3:
        raise LLMError("Ask a longer question.")
    if len(abstract) < 40:
        raise LLMError("Abstract is too short for AI Q&A.")
    loc = ""
    if source or article_id:
        loc = f"Library record: source={source or 'unknown'}, id={article_id or 'unknown'}\n"
    prompt = (
        "TASK: The student clicked “Ask about this paper” and typed the question below. "
        "Answer using ONLY the selected paper’s title and abstract.\n\n"
        f"{loc}"
        f"SELECTED PAPER TITLE:\n{title or 'Untitled'}\n\n"
        f"SELECTED PAPER ABSTRACT (sole evidence):\n{abstract}\n\n"
        f"STUDENT QUESTION:\n{question}\n\n"
        "OUTPUT: plain-language answer + up to 3 short verbatim quotes from the abstract "
        "(empty quotes list if nothing supports the answer)."
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
            "No LLM provider configured. Choose Built-in or Cloud API key on Account."
        )
    if selected == "ollama":
        # Fail fast with 503 when the local service is down (ephemeral start should
        # have warmed it; this catches races / control-disabled cases).
        if not ollama_running(force=True):
            raise LLMUnavailable(
                "Built-in study aid is not running. Try Refine/Ask again, "
                "or switch to Cloud API key on Account."
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
