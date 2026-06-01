"""
ModelRouter — Phase 0 (COMPLETE)

Routes planning to Kimi (latest), verification to DeepSeek.
All calls traced via Opik with cost attribution.

Kimi model: kimi-latest (OpenAI-compatible endpoint)
Base URL:   https://api.moonshot.ai/v1   (default from config)
DeepSeek:   unchanged
"""

import asyncio
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
    #@track(project_name="aether", name="kimi_k26_chat")
    async def chat(self, messages, system_prompt=None, temperature=None, max_tokens=None):
        start = time.perf_counter()
        
        # Build messages list - ensure proper format
        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": str(system_prompt)})
        for msg in messages:
            payload_messages.append({
                "role": str(msg.get("role", "user")),
                "content": str(msg.get("content", ""))
            })

        # Build payload with correct parameter names and types
        payload = {
            "model": str(self.config.model),
            "messages": payload_messages,
            "stream": False,
        }

        # Add temperature if set (must be between 0 and 2 for Kimi API)
        temp = temperature if temperature is not None else self.config.temperature
        if temp is not None:
            payload["temperature"] = float(max(0.0, min(2.0, temp)))
        
        # Add max_tokens if set (must be positive integer)
        max_t = max_tokens if max_tokens is not None else self.config.max_tokens
        if max_t is not None:
            payload["max_tokens"] = int(max(1, min(8192, max_t)))

        # Retry logic with exponential backoff
        max_retries = 3
        base_delay = 1.0
        last_error = None
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.info("kimi_k26.retry", attempt=attempt, delay=delay, model=payload["model"])
                    await asyncio.sleep(delay)
                
                resp = await self._client.post("/chat/completions", json=payload)
                
                # Log full request for debugging
                if resp.status_code >= 400:
                    error_body = resp.text
                    logger.error("kimi_k26.error", 
                                status_code=resp.status_code, 
                                error_body=error_body,
                                model=payload["model"],
                                attempt=attempt,
                                payload_sample=str(payload)[:500])
                
                # Handle specific error codes
                if resp.status_code == 401:
                    logger.error("kimi_k26.auth_error", 
                                error_body=resp.text,
                                api_key_preview=self.config.api_key[:8] + "..." if self.config.api_key else "<empty>")
                    resp.raise_for_status()
                elif resp.status_code == 429:
                    # Rate limit - retry with longer delay
                    if attempt < max_retries - 1:
                        continue
                    resp.raise_for_status()
                elif resp.status_code >= 400:
                    resp.raise_for_status()
                
                data = resp.json()
                break
                
            except Exception as e:
                last_error = e
                if attempt == max_retries - 1:
                    logger.error("kimi_k26.max_retries_exceeded", 
                                error=str(e), 
                                model=payload["model"],
                                attempts=max_retries)
                    raise
                continue

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
    #@track(project_name="aether", name="deepseek_chat")
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
        # Kimi model configuration - uses kimi-latest by default.
        # You can override via environment: KIMI_MODEL=kimi-latest
        # -------------------------------------------------------
        kimi_cfg = CONFIG.kimi_k2
        if not kimi_cfg.model:
            logger.info("model_router.using_default_kimi_model", model="kimi-latest")
            kimi_cfg = dataclasses.replace(kimi_cfg, model="kimi-latest")

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