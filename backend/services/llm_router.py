"""
LLM Router — single source of truth for all Ollama interactions.

Responsibilities:
  1. Enforce the blueprint §3 model routing rules
  2. Track deepseek-r1 call count (max 10/hour)
  3. Manage model swap — never load two 7B models simultaneously
  4. Wrap all inference in timeout + fallback
  5. Expose a clean `infer(prompt, task)` interface to agents

Blueprint routing rules (§3 UPDATE):
  - qwen2.5:7b  → DEFAULT for all standard operations
  - deepseek-r1:7b → ALL HIGH/CRITICAL severity cases (for auditability)
  - llama3.2:3b  → FALLBACK on error, timeout, or LOW severity log entries
"""
import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from core.config import settings
from core.constants import ModelName, Severity, AgentName

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# CALL COUNTER  (in-memory, resets each hour)
# ═══════════════════════════════════════════════════════════════════════════
_deepseek_calls: dict[str, int] = defaultdict(int)


def _current_hour_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H")


def deepseek_calls_this_hour() -> int:
    return _deepseek_calls[_current_hour_key()]


def _increment_deepseek_counter() -> None:
    _deepseek_calls[_current_hour_key()] += 1


def deepseek_budget_remaining() -> int:
    return max(0, settings.MAX_DEEPSEEK_CALLS_PER_HOUR - deepseek_calls_this_hour())


# ═══════════════════════════════════════════════════════════════════════════
# MODEL STATE TRACKER
# ═══════════════════════════════════════════════════════════════════════════
_currently_loaded: Optional[ModelName] = None


async def _ensure_model_loaded(model: ModelName) -> None:
    """
    Unload the currently loaded 7B model and load the requested one.
    llama3.2:3b stays loaded as permanent fallback (only 2.5GB).
    Blueprint §3: Never load two 7B models simultaneously.
    """
    global _currently_loaded

    if model == ModelName.LLAMA:
        return  # 3B always available, no swap needed

    if _currently_loaded == model:
        return  # Already loaded

    if _currently_loaded is not None and _currently_loaded != ModelName.LLAMA:
        logger.info("Model swap: unloading %s", _currently_loaded.value)
        await _ollama_unload(_currently_loaded)

    logger.info("Model swap: loading %s", model.value)
    _currently_loaded = model


async def _ollama_unload(model: ModelName) -> None:
    """Tell Ollama to release the model from memory via keep_alive=0."""
    import asyncio
    
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{settings.OLLAMA_HOST}/api/generate",
                    json={"model": model.value, "keep_alive": 0},
                )
                if response.status_code == 200:
                    return  # Success, exit early
                logger.warning("Unload attempt %d for %s returned status %d", 
                             attempt + 1, model.value, response.status_code)
        except Exception as e:
            logger.warning("Unload attempt %d for %s failed: %s", 
                         attempt + 1, model.value, e)
        
        if attempt < 2:  # Don't sleep after last attempt
            await asyncio.sleep(2)
    
    logger.warning("Failed to unload %s after 3 attempts", model.value)


# ═══════════════════════════════════════════════════════════════════════════
# ROUTING LOGIC  (blueprint §3 decision tree)
# ═══════════════════════════════════════════════════════════════════════════
def select_model(
    severity: Optional[Severity] = None,
    error_state: bool = False,
    is_trivial: bool = False,
) -> ModelName:
    """
    Pure routing function — returns which model to use.

    Decision tree (from blueprint §3 pseudocode + UPDATE note):
      1. Error state OR trivial/LOW task → llama3.2:3b
      2. HIGH or CRITICAL severity       → deepseek-r1:7b (budget permitting)
      3. Default                         → qwen2.5:7b
    """
    if error_state or is_trivial or severity == Severity.LOW:
        return ModelName.LLAMA

    if severity in (Severity.HIGH, Severity.CRITICAL):
        if deepseek_calls_this_hour() < settings.MAX_DEEPSEEK_CALLS_PER_HOUR:
            return ModelName.DEEPSEEK
        else:
            logger.warning(
                "DeepSeek hourly budget exhausted (%d/%d) — falling back to qwen2.5",
                deepseek_calls_this_hour(),
                settings.MAX_DEEPSEEK_CALLS_PER_HOUR,
            )
            return ModelName.QWEN

    return ModelName.QWEN


# ═══════════════════════════════════════════════════════════════════════════
# INFERENCE
# ═══════════════════════════════════════════════════════════════════════════
async def infer(
    prompt: str,
    *,
    severity: Optional[Severity] = None,
    error_state: bool = False,
    is_trivial: bool = False,
    system_prompt: Optional[str] = None,
    expect_json: bool = False,
    agent: Optional[AgentName] = None,
) -> tuple[str, ModelName]:
    """
    Main inference entry point.

    Returns (response_text, model_used).
    Falls back to llama3.2:3b on timeout or any error.

    Args:
        prompt:        The user/task prompt.
        severity:      Anomaly severity — drives model routing.
        error_state:   True if called from error recovery path.
        is_trivial:    True for simple log/format tasks.
        system_prompt: Optional system prompt override.
        expect_json:   If True, parse and validate JSON output.
        agent:         Caller agent name for logging.
    """
    model = select_model(severity=severity, error_state=error_state, is_trivial=is_trivial)
    caller = agent.value if agent else "unknown"

    logger.debug("[%s] routing to %s (severity=%s)", caller, model.value, severity)

    try:
        await _ensure_model_loaded(model)
        text = await _call_ollama_with_timeout(prompt, model, system_prompt)

        if model == ModelName.DEEPSEEK:
            _increment_deepseek_counter()
            logger.info(
                "[%s] deepseek-r1 call #%d this hour",
                caller, deepseek_calls_this_hour()
            )

        if expect_json:
            text = _extract_json(text)

        return text, model

    except asyncio.TimeoutError:
        logger.warning(
            "[%s] %s timed out after %dms — falling back to llama3.2:3b",
            caller, model.value, settings.FALLBACK_TIMEOUT_MS,
        )
        return await _fallback_infer(prompt, system_prompt, caller)

    except Exception as exc:
        logger.error("[%s] inference error on %s: %s", caller, model.value, exc)
        return await _fallback_infer(prompt, system_prompt, caller)


async def _call_ollama_with_timeout(
    prompt: str,
    model: ModelName,
    system_prompt: Optional[str],
) -> str:
    timeout_s = settings.FALLBACK_TIMEOUT_MS / 1000

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=30.0)
    ) as client:
        t0 = time.perf_counter()
        resp = await asyncio.wait_for(
            client.post(
                f"{settings.OLLAMA_HOST}/api/chat",
                json={
                    "model": model.value,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "num_ctx": settings.OLLAMA_CONTEXT_WINDOW,
                        "temperature": 0.1,   # low temperature for deterministic financial decisions
                    },
                },
            ),
            timeout=timeout_s,
        )
        elapsed = (time.perf_counter() - t0) * 1000
        resp.raise_for_status()
        data = resp.json()
        text = data["message"]["content"]
        logger.debug("  → %s responded in %.0fms (%d chars)", model.value, elapsed, len(text))
        return text


async def _fallback_infer(
    prompt: str,
    system_prompt: Optional[str],
    caller: str,
) -> tuple[str, ModelName]:
    """Last-resort inference on llama3.2:3b — no timeout escalation."""
    logger.info("[%s] using llama3.2:3b fallback", caller)
    try:
        text = await _call_ollama_with_timeout(prompt, ModelName.LLAMA, system_prompt)
        return text, ModelName.LLAMA
    except Exception as exc:
        logger.error("[%s] fallback also failed: %s", caller, exc)
        return f"[LLM unavailable: {exc}]", ModelName.LLAMA


def _extract_json(text: str) -> str:
    """
    Strip markdown fences and extract the first valid JSON block.
    deepseek-r1 sometimes wraps output in ```json ... ```.
    """
    # Remove <think>...</think> tags from deepseek-r1 chain-of-thought
    import re
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Strip ```json fences
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())

    # Try to find the first {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        candidate = match.group(0)
        try:
            json.loads(candidate)  # validate
            return candidate
        except json.JSONDecodeError:
            pass

    return text  # return as-is and let caller handle parse failure


# ═══════════════════════════════════════════════════════════════════════════
# STARTUP / PREWARM
# ═══════════════════════════════════════════════════════════════════════════
async def prewarm_models() -> None:
    """
    Pre-warm qwen2.5:7b and llama3.2:3b on startup.
    Blueprint §12: 'Pre-warm models on startup.'
    """
    global _currently_loaded

    logger.info("Pre-warming qwen2.5:7b (primary model)...")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            await client.post(
                f"{settings.OLLAMA_HOST}/api/generate",
                json={"model": ModelName.QWEN.value, "prompt": "ping", "stream": False},
            )
        _currently_loaded = ModelName.QWEN
        logger.info("  ✓ qwen2.5:7b warmed")
    except Exception as e:
        logger.warning("  ✗ qwen2.5:7b prewarm failed: %s", e)

    logger.info("Pre-warming llama3.2:3b (fallback model)...")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            await client.post(
                f"{settings.OLLAMA_HOST}/api/generate",
                json={"model": ModelName.LLAMA.value, "prompt": "ping", "stream": False},
            )
        logger.info("  ✓ llama3.2:3b warmed")
    except Exception as e:
        logger.warning("  ✗ llama3.2:3b prewarm failed: %s", e)


async def get_loaded_models() -> list[dict]:
    """Query Ollama for currently loaded models (for the dashboard status endpoint)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.OLLAMA_HOST}/api/ps")
            resp.raise_for_status()
            return resp.json().get("models", [])
    except Exception:
        return []


async def list_available_models() -> list[str]:
    """List all models pulled in this Ollama instance."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.OLLAMA_HOST}/api/tags")
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        return []