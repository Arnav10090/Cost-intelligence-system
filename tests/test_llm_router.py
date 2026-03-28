"""
Tests for LLM Router — model selection, call counter, fallback logic.

All tests are pure unit tests — no real Ollama calls made.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from core.constants import ModelName, Severity, AgentName


# ═══════════════════════════════════════════════════════════════════════════
# select_model() — routing decision tree
# ═══════════════════════════════════════════════════════════════════════════
class TestSelectModel:
    def setup_method(self):
        """Reset the deepseek call counter before each test."""
        import services.llm_router as router
        router._deepseek_calls.clear()

    def test_default_returns_qwen(self):
        from services.llm_router import select_model
        assert select_model() == ModelName.QWEN

    def test_low_severity_returns_llama(self):
        from services.llm_router import select_model
        assert select_model(severity=Severity.LOW) == ModelName.LLAMA

    def test_error_state_returns_llama(self):
        from services.llm_router import select_model
        assert select_model(error_state=True) == ModelName.LLAMA

    def test_trivial_returns_llama(self):
        from services.llm_router import select_model
        assert select_model(is_trivial=True) == ModelName.LLAMA

    def test_high_severity_returns_deepseek(self):
        from services.llm_router import select_model
        assert select_model(severity=Severity.HIGH) == ModelName.DEEPSEEK

    def test_critical_severity_returns_deepseek(self):
        from services.llm_router import select_model
        assert select_model(severity=Severity.CRITICAL) == ModelName.DEEPSEEK

    def test_medium_severity_returns_qwen(self):
        from services.llm_router import select_model
        assert select_model(severity=Severity.MEDIUM) == ModelName.QWEN

    def test_high_severity_budget_exhausted_falls_to_qwen(self):
        """When deepseek hourly budget is exhausted, fall back to qwen2.5."""
        import services.llm_router as router
        from services.llm_router import select_model, _current_hour_key
        from core.config import settings

        # Exhaust the budget
        router._deepseek_calls[_current_hour_key()] = settings.MAX_DEEPSEEK_CALLS_PER_HOUR

        result = select_model(severity=Severity.HIGH)
        assert result == ModelName.QWEN, (
            "Should fall back to qwen when deepseek budget is exhausted"
        )

    def test_error_state_overrides_severity(self):
        """Error state always wins — even HIGH severity goes to llama fallback."""
        from services.llm_router import select_model
        assert select_model(severity=Severity.HIGH, error_state=True) == ModelName.LLAMA


# ═══════════════════════════════════════════════════════════════════════════
# deepseek call counter
# ═══════════════════════════════════════════════════════════════════════════
class TestDeepSeekCallCounter:
    def setup_method(self):
        import services.llm_router as router
        router._deepseek_calls.clear()

    def test_starts_at_zero(self):
        from services.llm_router import deepseek_calls_this_hour
        assert deepseek_calls_this_hour() == 0

    def test_increments_on_call(self):
        import services.llm_router as router
        from services.llm_router import (
            deepseek_calls_this_hour, _increment_deepseek_counter,
        )
        _increment_deepseek_counter()
        _increment_deepseek_counter()
        assert deepseek_calls_this_hour() == 2

    def test_budget_remaining_decrements(self):
        from services.llm_router import (
            deepseek_budget_remaining, _increment_deepseek_counter,
        )
        from core.config import settings
        initial = deepseek_budget_remaining()
        _increment_deepseek_counter()
        assert deepseek_budget_remaining() == initial - 1

    def test_budget_never_goes_negative(self):
        import services.llm_router as router
        from services.llm_router import (
            deepseek_budget_remaining, _current_hour_key,
        )
        from core.config import settings
        # Set calls way over budget
        router._deepseek_calls[_current_hour_key()] = 100
        assert deepseek_budget_remaining() == 0


# ═══════════════════════════════════════════════════════════════════════════
# Severity enum helpers
# ═══════════════════════════════════════════════════════════════════════════
class TestSeverityEnum:
    def test_high_triggers_deepseek(self):
        assert Severity.HIGH.triggers_deepseek is True

    def test_critical_triggers_deepseek(self):
        assert Severity.CRITICAL.triggers_deepseek is True

    def test_medium_does_not_trigger_deepseek(self):
        assert Severity.MEDIUM.triggers_deepseek is False

    def test_low_does_not_trigger_deepseek(self):
        assert Severity.LOW.triggers_deepseek is False

    def test_severity_ordering(self):
        assert Severity.CRITICAL > Severity.HIGH
        assert Severity.HIGH > Severity.MEDIUM
        assert Severity.MEDIUM > Severity.LOW

    def test_weight_values(self):
        assert Severity.LOW.weight == 1
        assert Severity.MEDIUM.weight == 2
        assert Severity.HIGH.weight == 3
        assert Severity.CRITICAL.weight == 4


# ═══════════════════════════════════════════════════════════════════════════
# JSON extraction (_extract_json)
# ═══════════════════════════════════════════════════════════════════════════
class TestExtractJson:
    def test_clean_json_passthrough(self):
        from services.llm_router import _extract_json
        payload = '{"root_cause": "duplicate", "confidence": 0.97}'
        assert _extract_json(payload) == payload

    def test_strips_markdown_fences(self):
        from services.llm_router import _extract_json
        raw = '```json\n{"action": "hold_payment"}\n```'
        result = _extract_json(raw)
        assert result == '{"action": "hold_payment"}'

    def test_strips_deepseek_think_tags(self):
        from services.llm_router import _extract_json
        raw = '<think>Let me analyse this carefully...</think>\n{"confidence": 0.94}'
        result = _extract_json(raw)
        parsed = json.loads(result)
        assert parsed["confidence"] == 0.94

    def test_extracts_json_from_prose(self):
        from services.llm_router import _extract_json
        raw = 'Based on my analysis: {"action": "escalate", "urgency": "HIGH"} seems correct.'
        result = _extract_json(raw)
        parsed = json.loads(result)
        assert parsed["action"] == "escalate"

    def test_handles_no_json_gracefully(self):
        from services.llm_router import _extract_json
        raw = "I cannot determine the action from the given context."
        result = _extract_json(raw)
        assert result == raw  # returns as-is; caller handles parse failure


# ═══════════════════════════════════════════════════════════════════════════
# infer() — integration (mocked HTTP)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
class TestInferFunction:
    async def test_returns_tuple_of_text_and_model(self):
        from services.llm_router import infer
        mock_resp = {
            "message": {"content": '{"action": "hold_payment"}'},
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=mock_resp),
                raise_for_status=MagicMock(),
                status_code=200,
            )
            text, model = await infer("test prompt", severity=Severity.MEDIUM)
        assert isinstance(text, str)
        assert isinstance(model, ModelName)

    async def test_timeout_falls_back_to_llama(self):
        """TimeoutError on primary model → fallback to llama3.2:3b."""
        from services.llm_router import infer

        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError()
            return MagicMock(
                json=MagicMock(return_value={"message": {"content": "fallback response"}}),
                raise_for_status=MagicMock(),
            )

        with patch("httpx.AsyncClient.post", side_effect=mock_post):
            text, model = await infer("test", severity=Severity.MEDIUM)

        assert model == ModelName.LLAMA
        assert "fallback" in text

    async def test_high_severity_routes_to_deepseek(self):
        """HIGH severity → deepseek-r1 is selected (budget permitting)."""
        import services.llm_router as router
        router._deepseek_calls.clear()

        called_models = []

        async def mock_post(url, **kwargs):
            payload = kwargs.get("json", {})
            called_models.append(payload.get("model"))
            return MagicMock(
                json=MagicMock(return_value={"message": {"content": '{"action":"hold"}'}}),
                raise_for_status=MagicMock(),
            )

        with patch("httpx.AsyncClient.post", side_effect=mock_post):
            await infer("analyse this", severity=Severity.HIGH)

        assert ModelName.DEEPSEEK.value in called_models, (
            f"Expected deepseek call but got: {called_models}"
        )