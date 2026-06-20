import os
import structlog
from typing import List, Dict, Any, Optional
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_community.chat_models import ChatDeepSeek
from langchain_community.chat_models import ChatMoonshot
import httpx

logger = structlog.get_logger("aether.core.model_router_kimi_deepseek" )

class KimiDeepSeekRouter:
    """
    Routes LLM requests to Kimi K2.6 (reasoning) or DeepSeek-Chat (general).
    
    Kimi K2.6: Best for complex reasoning, legal analysis, multi-step planning.
    DeepSeek-Chat: Best for general conversation, quick responses, summaries.
    """
    ROLE_PLANNING = "planning"
    ROLE_VERIFICATION = "verification"
    ROLE_FALLBACK = "fallback"


    def __init__(self):
        self.kimi_base_url = os.environ.get("KIMI_BASE_URL", "https://api.moonshot.ai/v1" )
        self.kimi_api_key = os.environ.get("KIMI_API_KEY")
        self.kimi_model = os.environ.get("KIMI_MODEL", "kimi-k2.6")
        
        self.deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY")
        self.deepseek_model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        self.deepseek_base_url = "https://api.deepseek.com/v1"
        
        self.http_client = httpx.AsyncClient(timeout=60.0 )
        logger.info("model_router_kimi_deepseek.initialized")

    async def route(self, purpose: str, messages: List[BaseMessage], model: Optional[str] = None) -> AIMessage:
        """
        Main routing function. Automatically selects the best model based on purpose.
        
        Args:
            purpose: Task purpose (e.g., "legal_analysis", "briefing_synthesis", "general_chat")
            messages: List of conversation messages
            model: Optional override ("kimi" or "deepseek")
        
        Returns:
            AIMessage with the response
        """
        if model is None:
            model = self._select_model(purpose)
        
        logger.info("model_router.routing", purpose=purpose, selected_model=model)
        
        if model == "kimi":
            return await self._route_kimi(purpose, messages)
        elif model == "deepseek":
            return await self._route_deepseek(purpose, messages)
        else:
            raise ValueError(f"Unknown model: {model}")

    def _select_model(self, purpose: str) -> str:
        """
        Intelligently select the best model for the given purpose.
        
        Kimi K2.6 is used for:
        - legal_analysis, case_review, statute_interpretation
        - planning, strategy, complex_reasoning
        - verification, quality_check
        
        DeepSeek-Chat is used for:
        - general_chat, summarization, briefing_synthesis
        - quick_response, creative_writing
        """
        kimi_purposes = {
            "legal_analysis", "case_review", "statute_interpretation",
            "planning", "strategy", "complex_reasoning",
            "verification", "quality_check", "self_correction",
            "procurement_analysis", "healthcare_analysis"
        }
        
        if purpose in kimi_purposes:
            return "kimi"
        else:
            return "deepseek"

    async def _route_kimi(self, purpose: str, messages: List[BaseMessage]) -> AIMessage:
        """
        Route to Kimi K2.6 for complex reasoning tasks.
        """
        if not self.kimi_api_key:
            raise RuntimeError("KIMI_API_KEY not configured")

        try:
            # Convert LangChain messages to Kimi API format
            kimi_messages = self._convert_to_kimi_format(messages)
            
            headers = {
                "Authorization": f"Bearer {self.kimi_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self.kimi_model,
                "messages": kimi_messages,
                "temperature": 0.7,
                "max_tokens": 4096
            }
            
            response = await self.http_client.post(
                f"{self.kimi_base_url}/chat/completions",
                json=payload,
                headers=headers
             )
            
            response.raise_for_status()
            result = response.json()
            
            content = result["choices"][0]["message"]["content"]
            logger.info("model_router.kimi_success", purpose=purpose, tokens=result.get("usage", {}).get("total_tokens"))
            
            return AIMessage(content=content)

        except Exception as e:
            logger.error("model_router.kimi_failed", error=str(e), exc_info=True)
            raise

    async def _route_deepseek(self, purpose: str, messages: List[BaseMessage]) -> AIMessage:
        """
        Route to DeepSeek-Chat for general tasks.
        """
        if not self.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not configured")

        try:
            # Convert LangChain messages to DeepSeek API format
            deepseek_messages = self._convert_to_deepseek_format(messages)
            
            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self.deepseek_model,
                "messages": deepseek_messages,
                "temperature": 0.7,
                "max_tokens": 4096
            }
            
            response = await self.http_client.post(
                f"{self.deepseek_base_url}/chat/completions",
                json=payload,
                headers=headers
             )
            
            response.raise_for_status()
            result = response.json()
            
            content = result["choices"][0]["message"]["content"]
            logger.info("model_router.deepseek_success", purpose=purpose, tokens=result.get("usage", {}).get("total_tokens"))
            
            return AIMessage(content=content)

        except Exception as e:
            logger.error("model_router.deepseek_failed", error=str(e), exc_info=True)
            raise

    def _convert_to_kimi_format(self, messages: List[BaseMessage]) -> List[Dict]:
        """Convert LangChain messages to Kimi API format."""
        kimi_messages = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                kimi_messages.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                kimi_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                kimi_messages.append({"role": "assistant", "content": msg.content})
        return kimi_messages

    def _convert_to_deepseek_format(self, messages: List[BaseMessage]) -> List[Dict]:
        """Convert LangChain messages to DeepSeek API format."""
        deepseek_messages = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                deepseek_messages.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                deepseek_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                deepseek_messages.append({"role": "assistant", "content": msg.content})
        return deepseek_messages

    async def close(self):
        """
        Close the HTTP client.
        """
        await self.http_client.aclose( )
