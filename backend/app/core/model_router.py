"""
ModelRouter — Phase 0 (COMPLETE)

Routes planning to Kimi K2.6, verification to DeepSeek.
All calls traced via Opik with cost attribution.

Kimi model: kimi-k2.6 (OpenAI-compatible endpoint)
Base URL:   https://api.moonshot.cn/v1   (default from config)
DeepSeek:   unchanged
"""

import dataclasses
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
import structlog
from opik import track

from app.core.config import CONFIG, ModelConfig

logger = structlog.get_logger("aether.model_router")

# ------------------------------------------------------------------
# Pricing constants (USD per 1M tokens) – update if needed
# These are for the kimi-k2.6 model via Moonshot official API.
# ------------------------------------------------------------------
KIMI_K26_INPUT_PRICE  = 0.95
KIMI_K26_OUTPUT_PRICE = 4.00
DEEPSEEK_INPUT_PRICE  = 0.14   # V4-Flash
DEEPSEEK_OUTPUT_PRICE = 0.28

# ------------------------------------------------------------------
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
        headers = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        self._client = httpx.AsyncClient(
            base_url=config.base_url or "",
            timeout=httpx.Timeout(config.timeout),
            headers=headers,
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
    @track(project_name="aether", name="kimi_k26_chat")
    async def chat(self, messages, system_prompt=None, temperature=None, max_tokens=None):
        start = time.perf_counter()
        # Use a copy to avoid mutating the original messages list
        payload_messages = list(messages)
        if system_prompt:
            payload_messages.insert(0, {"role": "system", "content": system_prompt})

        payload = {
            # IMPORTANT: model is taken from config (set to "kimi-k2.6" in .env)
            "model": self.config.model,
            "messages": payload_messages,
            "stream": False,
        }

        # Only include parameters if they are explicitly set to avoid 400 Bad Request
        temp = temperature if temperature is not None else self.config.temperature
        if temp is not None:
            payload["temperature"] = temp
        max_t = max_tokens if max_tokens is not None else self.config.max_tokens
        if max_t is not None:
            payload["max_tokens"] = max_t

        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        usage = self._parse_usage(data)
        latency = (time.perf_counter() - start) * 1000

        logger.info("kimi_k26.complete", model=payload["model"],
                    input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                    latency_ms=round(latency, 2))

        return ModelResponse(
            content=data["choices"][0]["message"]["content"],
            model=payload["model"], provider="kimi",
            usage=usage, latency_ms=latency, raw=data,
        )


class DeepSeekClient(BaseModelClient):
    @track(project_name="aether", name="deepseek_chat")
    async def chat(self, messages, system_prompt=None, temperature=None, max_tokens=None):
        start = time.perf_counter()
        payload_messages = list(messages)
        if system_prompt:
            payload_messages.insert(0, {"role": "system", "content": system_prompt})

        payload = {
            "model": self.config.model,
            "messages": payload_messages,
            "stream": False,
        }

        temp = temperature if temperature is not None else self.config.temperature
        if temp is not None:
            payload["temperature"] = temp
        max_t = max_tokens if max_tokens is not None else self.config.max_tokens
        if max_t is not None:
            payload["max_tokens"] = max_t

        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        usage = self._parse_usage(data)
        latency = (time.perf_counter() - start) * 1000

        logger.info("deepseek.complete", model=payload["model"],
                    input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                    latency_ms=round(latency, 2))

        return ModelResponse(
            content=data["choices"][0]["message"]["content"],
            model=payload["model"], provider="deepseek",
            usage=usage, latency_ms=latency, raw=data,
        )


class ModelRouter:
    ROLE_PLANNING = "planning"
    ROLE_VERIFICATION = "verification"
    ROLE_FALLBACK = "fallback"

    def __init__(self):
        # -------------------------------------------------------
        # Ensure the Kimi model is set to kimi-k2.6.
        # You can override via environment: KIMI_K2_MODEL=kimi-k2.6
        # -------------------------------------------------------
        kimi_cfg = CONFIG.kimi_k2
        if not kimi_cfg.model or kimi_cfg.model.startswith("kimi-k2-"):
            # Automatically upgrade old model names to k2.6
            logger.info("model_router.upgrading_kimi_model", old=kimi_cfg.model, new="kimi-k2.6")
            kimi_cfg = dataclasses.replace(kimi_cfg, model="kimi-k2.6")

        self._kimi = KimiK2Client(kimi_cfg)
        logger.info("model_router.kimi_config",
                    model=kimi_cfg.model,
                    base_url=kimi_cfg.base_url,
                    api_key_preview=kimi_cfg.api_key[:8] + "..." if kimi_cfg.api_key else "<empty>")
        self._deepseek = DeepSeekClient(CONFIG.deepseek)
        
        ds_cfg = CONFIG.deepseek
        if not ds_cfg.model or "flash" in ds_cfg.model.lower():
            logger.info("model_router.fixing_deepseek_model", old=ds_cfg.model, new="deepseek-chat")
            ds_cfg = dataclasses.replace(ds_cfg, model="deepseek-chat")
            
        self._deepseek = DeepSeekClient(ds_cfg)
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
                logger.warning("model_router.fallback: %s", e)
                return await self._deepseek.chat(messages, system_prompt, temperature, max_tokens)
            raise

    async def close(self):
        await self._kimi.close()
        await self._deepseek.close()