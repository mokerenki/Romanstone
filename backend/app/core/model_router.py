"""ModelRouter — Phase 0 (COMPLETE)

Routes planning to Kimi K2, verification to DeepSeek.
All calls traced via Opik with cost attribution.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
import structlog
from opik import track

from app.core.config import CONFIG, ModelConfig

logger = structlog.get_logger("aether.model_router")


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def total_cost(self, in_cost: float, out_cost: float) -> float:
        return (self.input_tokens / 1_000_000) * in_cost + (self.output_tokens / 1_000_000) * out_cost


@dataclass(frozen=True)
class ModelResponse:
    content: str
    model: str
    provider: str
    usage: TokenUsage
    latency_ms: float
    raw: Optional[Dict[str, Any]] = None


class BaseModelClient(ABC):
    def __init__(self, config: ModelConfig):
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url or "",
            timeout=httpx.Timeout(config.timeout),
            headers={"Authorization": f"Bearer {config.api_key}"},
        )

    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None,
                   temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> ModelResponse:
        pass

    def _parse_usage(self, raw: Dict[str, Any]) -> TokenUsage:
        usage = raw.get("usage", {})
        return TokenUsage(
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    async def close(self):
        await self._client.aclose()


class KimiK2Client(BaseModelClient):
    @track(project_name="aether", name="kimi_k2_chat")
    async def chat(self, messages, system_prompt=None, temperature=None, max_tokens=None):
        start = time.perf_counter()
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature or self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            "stream": False,
        }
        if system_prompt:
            payload["messages"].insert(0, {"role": "system", "content": system_prompt})

        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        usage = self._parse_usage(data)
        latency = (time.perf_counter() - start) * 1000

        logger.info("kimi_k2.complete", model=self.config.model,
                    input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                    latency_ms=round(latency, 2))

        return ModelResponse(
            content=data["choices"][0]["message"]["content"],
            model=self.config.model, provider="kimi",
            usage=usage, latency_ms=latency, raw=data,
        )


class DeepSeekClient(BaseModelClient):
    @track(project_name="aether", name="deepseek_chat")
    async def chat(self, messages, system_prompt=None, temperature=None, max_tokens=None):
        start = time.perf_counter()
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature or self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            "stream": False,
        }
        if system_prompt:
            payload["messages"].insert(0, {"role": "system", "content": system_prompt})

        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        usage = self._parse_usage(data)
        latency = (time.perf_counter() - start) * 1000

        logger.info("deepseek.complete", model=self.config.model,
                    input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                    latency_ms=round(latency, 2))

        return ModelResponse(
            content=data["choices"][0]["message"]["content"],
            model=self.config.model, provider="deepseek",
            usage=usage, latency_ms=latency, raw=data,
        )


class ModelRouter:
    ROLE_PLANNING = "planning"
    ROLE_VERIFICATION = "verification"
    ROLE_FALLBACK = "fallback"

    def __init__(self):
        self._kimi = KimiK2Client(CONFIG.kimi_k2)
        self._deepseek = DeepSeekClient(CONFIG.deepseek)
        self._role_map = {
            self.ROLE_PLANNING: self._kimi,
            self.ROLE_VERIFICATION: self._deepseek,
            self.ROLE_FALLBACK: self._deepseek,
        }
        logger.info("model_router.initialized")

    async def route(self, role: str, messages: List[Dict[str, str]],
                    system_prompt: Optional[str] = None,
                    temperature: Optional[float] = None,
                    max_tokens: Optional[int] = None) -> ModelResponse:
        client = self._role_map.get(role)
        if not client:
            raise ValueError(f"Unknown role: {role}")

        logger.info("model_router.route", role=role, provider=client.config.provider)

        try:
            return await client.chat(messages, system_prompt, temperature, max_tokens)
        except Exception as e:
            if role == self.ROLE_PLANNING:
                logger.warning("model_router.fallback", error=str(e))
                return await self._deepseek.chat(messages, system_prompt, temperature, max_tokens)
            raise

    async def close(self):
        await self._kimi.close()
        await self._deepseek.close()
