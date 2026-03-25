"""
OpenRouter — Roteamento inteligente de LLMs por tarefa.

Modelos baratos (Flash/Haiku) para ideacao e brainstorm.
Modelos robustos (Sonnet/GPT-4o) para compliance e copy final.

Uso:
    router = OpenRouterClient(api_key="sk-or-...")
    result = await router.complete("briefing", "Gere um briefing para LEV no Instagram")
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Modelos e roteamento por tarefa
# ------------------------------------------------------------------

@dataclass
class ModelConfig:
    model_id: str
    display_name: str
    cost_per_1k_input: float  # USD
    cost_per_1k_output: float  # USD
    max_tokens: int = 4096
    temperature: float = 0.7


# Catalogo de modelos disponíveis via OpenRouter
MODELS = {
    "flash": ModelConfig(
        model_id="google/gemini-2.0-flash-001",
        display_name="Gemini 2.0 Flash",
        cost_per_1k_input=0.0001,
        cost_per_1k_output=0.0004,
        max_tokens=8192,
        temperature=0.8,
    ),
    "haiku": ModelConfig(
        model_id="anthropic/claude-3.5-haiku",
        display_name="Claude 3.5 Haiku",
        cost_per_1k_input=0.0008,
        cost_per_1k_output=0.004,
        max_tokens=4096,
        temperature=0.7,
    ),
    "sonnet": ModelConfig(
        model_id="anthropic/claude-sonnet-4-20250514",
        display_name="Claude Sonnet 4",
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
        max_tokens=4096,
        temperature=0.3,
    ),
    "gpt4o-mini": ModelConfig(
        model_id="openai/gpt-4o-mini",
        display_name="GPT-4o Mini",
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.0006,
        max_tokens=4096,
        temperature=0.7,
    ),
}

# Roteamento: tarefa → modelo
TASK_ROUTING = {
    # Ideacao e brainstorm (barato)
    "briefing": "flash",
    "brainstorm": "flash",
    "hashtags": "flash",
    "calendar": "flash",
    "atomize": "flash",

    # Copy e conteudo (intermediario)
    "copy": "haiku",
    "headline": "haiku",
    "cta": "haiku",
    "caption": "haiku",
    "narration": "haiku",

    # Compliance e qualidade (robusto)
    "compliance": "sonnet",
    "review": "sonnet",
    "critique": "sonnet",
    "persona_test": "sonnet",

    # Fallback
    "default": "flash",
}


@dataclass
class LLMUsage:
    """Registro de uso de uma chamada LLM."""
    task: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    elapsed_ms: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "elapsed_ms": self.elapsed_ms,
            "timestamp": self.timestamp,
        }


class OpenRouterClient:
    """Cliente para OpenRouter API com roteamento inteligente."""

    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        budget_tracker: Optional[object] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.budget_tracker = budget_tracker
        self._usage_log: list[LLMUsage] = []

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def get_model_for_task(self, task: str) -> ModelConfig:
        """Retorna o modelo ideal para a tarefa."""
        model_key = TASK_ROUTING.get(task, TASK_ROUTING["default"])
        return MODELS[model_key]

    async def complete(
        self,
        task: str,
        prompt: str,
        system_prompt: str = "",
        model_override: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> dict:
        """
        Executa completion com roteamento inteligente.

        Args:
            task: Tipo de tarefa (briefing, copy, compliance, etc.)
            prompt: Prompt do usuario
            system_prompt: System prompt opcional
            model_override: Forcar modelo especifico (key do MODELS)
            max_tokens: Override de max tokens
            temperature: Override de temperatura

        Returns:
            dict com text, model, usage, cost
        """
        if not self.configured:
            return {
                "text": f"[OpenRouter nao configurado — OPENROUTER_API_KEY ausente]\nTask: {task}\nPrompt: {prompt[:200]}...",
                "model": "preview",
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "cost_usd": 0,
                "preview_mode": True,
            }

        model_config = MODELS.get(model_override) if model_override else self.get_model_for_task(task)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        start = time.monotonic()

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "HTTP-Referer": "https://studio.salk.com",
                    "X-Title": "Salk Content Studio",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_config.model_id,
                    "messages": messages,
                    "max_tokens": max_tokens or model_config.max_tokens,
                    "temperature": temperature if temperature is not None else model_config.temperature,
                },
            )
            response.raise_for_status()
            data = response.json()

        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Extrair resultado
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        # Calcular custo
        cost = (
            (input_tokens / 1000) * model_config.cost_per_1k_input
            + (output_tokens / 1000) * model_config.cost_per_1k_output
        )

        # Registrar uso
        llm_usage = LLMUsage(
            task=task,
            model=model_config.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            elapsed_ms=elapsed_ms,
        )
        self._usage_log.append(llm_usage)

        # Notificar budget tracker
        if self.budget_tracker and hasattr(self.budget_tracker, "record"):
            self.budget_tracker.record("llm", cost, {
                "model": model_config.model_id,
                "task": task,
                "tokens": input_tokens + output_tokens,
            })

        return {
            "text": text,
            "model": model_config.display_name,
            "model_id": model_config.model_id,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            "cost_usd": round(cost, 6),
            "elapsed_ms": elapsed_ms,
        }

    def get_usage_summary(self) -> dict:
        """Resumo de uso acumulado."""
        if not self._usage_log:
            return {"total_calls": 0, "total_cost_usd": 0, "by_task": {}, "by_model": {}}

        by_task: dict[str, dict] = {}
        by_model: dict[str, dict] = {}

        for u in self._usage_log:
            # Por tarefa
            if u.task not in by_task:
                by_task[u.task] = {"calls": 0, "cost_usd": 0, "tokens": 0}
            by_task[u.task]["calls"] += 1
            by_task[u.task]["cost_usd"] += u.cost_usd
            by_task[u.task]["tokens"] += u.input_tokens + u.output_tokens

            # Por modelo
            if u.model not in by_model:
                by_model[u.model] = {"calls": 0, "cost_usd": 0, "tokens": 0}
            by_model[u.model]["calls"] += 1
            by_model[u.model]["cost_usd"] += u.cost_usd
            by_model[u.model]["tokens"] += u.input_tokens + u.output_tokens

        return {
            "total_calls": len(self._usage_log),
            "total_cost_usd": round(sum(u.cost_usd for u in self._usage_log), 4),
            "total_tokens": sum(u.input_tokens + u.output_tokens for u in self._usage_log),
            "by_task": {k: {**v, "cost_usd": round(v["cost_usd"], 4)} for k, v in by_task.items()},
            "by_model": {k: {**v, "cost_usd": round(v["cost_usd"], 4)} for k, v in by_model.items()},
        }

    def get_available_models(self) -> list[dict]:
        """Lista modelos disponiveis para o frontend."""
        return [
            {
                "key": key,
                "model_id": m.model_id,
                "display_name": m.display_name,
                "cost_input": m.cost_per_1k_input,
                "cost_output": m.cost_per_1k_output,
                "tasks": [t for t, mk in TASK_ROUTING.items() if mk == key],
            }
            for key, m in MODELS.items()
        ]
