import structlog
import json
from typing import Dict, Any, Optional
from langchain_core.messages import HumanMessage, SystemMessage  # type: ignore[import-not-found]
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter
from app.mcp_clients import MCPRegistry

logger = structlog.get_logger("aether.agents.router")

class DomainRouter:
    """
    Routes user tasks to the appropriate domain agent.
    Uses a lightweight LLM (DeepSeek) for classification.
    """

    DOMAINS = ["sales", "marketing", "finance", "executive", "healthcare", "product"]

    def __init__(self, model_router: KimiDeepSeekRouter, mcp_registry: MCPRegistry):
        self.model_router = model_router
        self.mcp_registry = mcp_registry
        logger.info("domain_router.initialized")

    async def route(self, user_message: str, user_id: str = "anonymous", thread_id: str = "default") -> Dict[str, Any]:
        """
        Route the user message to the appropriate domain.

        Returns:
            Dict with keys: domain, context, system_prompt
        """
        # Use LLM to classify the domain
        classification_prompt = SystemMessage(content=f"""
        You are a domain classifier. Classify the user's request into one of these domains:
        {', '.join(self.DOMAINS)}

        Guidelines:
        - sales: Anything about leads, opportunities, pipeline, CRM, closing deals
        - marketing: Campaigns, content, social media, lead generation, branding
        - finance: Budgeting, expenses, invoices, financial analysis, modeling
        - executive: Strategic decisions, KPIs, goals, projects, high-level planning
        - healthcare: Claims, insurance, scheduling, patient admin
        - product: Product management, roadmaps, features, user feedback, product strategy
        - general: Anything else that doesn't fit the above

        Respond with ONLY the domain name.
        """)

        try:
            # Use DeepSeek for classification (fast and cheap)
            response = await self.model_router.route(
                "classification",
                [classification_prompt, HumanMessage(content=user_message)],
                model="deepseek"
            )

            domain = response.content.strip().lower()
            if domain not in self.DOMAINS:
                domain = "general"

            logger.info("domain_router.classified", domain=domain, user_message=user_message[:50])

            # Get domain context and prompt from MCP registry
            context = await self.mcp_registry.get_domain_context(domain, user_id, thread_id)
            system_prompt = self.mcp_registry.get_domain_prompt(domain)

            return {
                "domain": domain,
                "context": context,
                "system_prompt": system_prompt
            }

        except Exception as e:
            logger.error("domain_router.classification_failed", error=str(e))
            return {
                "domain": "general",
                "context": {},
                "system_prompt": "You are a helpful assistant."
            }