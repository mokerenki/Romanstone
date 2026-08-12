# backend/app/services/captcha_solver.py

import asyncio
import base64
import os
import structlog
from typing import Optional, Dict, Any
import httpx
from playwright.async_api import Page

logger = structlog.get_logger("synthai.services.captcha")

# ─── Configuration ──────────────────────────────────────────────

CAPTCHA_PROVIDER = os.getenv("CAPTCHA_PROVIDER", "2captcha")  # 2captcha, anticaptcha, human
CAPTCHA_API_KEY = os.getenv("CAPTCHA_API_KEY", "")
CAPTCHA_TIMEOUT = int(os.getenv("CAPTCHA_TIMEOUT", "120"))


class CaptchaSolver:
    """
    Solves captchas using various providers.
    Supports 2Captcha, AntiCaptcha, and human-in-the-loop.
    """
    
    def __init__(self, provider: str = CAPTCHA_PROVIDER):
        self.provider = provider
        self.api_key = CAPTCHA_API_KEY
        self.timeout = CAPTCHA_TIMEOUT
        self._pending_solutions: Dict[str, asyncio.Event] = {}
        self._solutions: Dict[str, str] = {}
    
    async def solve_image_captcha(
        self,
        image_base64: str,
        captcha_type: str = "image",
        page: Optional[Page] = None
    ) -> Optional[str]:
        """
        Solve an image-based captcha.
        
        Args:
            image_base64: Base64 encoded image
            captcha_type: Type of captcha (image, recaptcha, hcaptcha)
            page: Optional Playwright page for automated solving
        
        Returns:
            Solved captcha text or None
        """
        logger.info("captcha.solving", provider=self.provider, type=captcha_type)
        
        if self.provider == "2captcha":
            return await self._solve_2captcha(image_base64, captcha_type)
        elif self.provider == "anticaptcha":
            return await self._solve_anticaptcha(image_base64, captcha_type)
        elif self.provider == "human":
            return await self._solve_human(image_base64, captcha_type, page)
        else:
            logger.error("captcha.unknown_provider", provider=self.provider)
            return None
    
    async def _solve_2captcha(self, image_base64: str, captcha_type: str) -> Optional[str]:
        """Solve captcha using 2Captcha API."""
        if not self.api_key:
            logger.error("captcha.no_api_key", provider="2captcha")
            return None
        
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                # Step 1: Upload captcha
                upload_data = {
                    "key": self.api_key,
                    "method": "base64",
                    "body": image_base64,
                    "json": 1,
                }
                
                response = await client.post(
                    "https://api.2captcha.com/upload",
                    data=upload_data
                )
                
                if response.status_code != 200:
                    logger.error("captcha.upload_failed", status=response.status_code)
                    return None
                
                result = response.json()
                if result.get("status") != 1:
                    logger.error("captcha.upload_error", error=result.get("error"))
                    return None
                
                captcha_id = result.get("captcha_id")
                if not captcha_id:
                    return None
                
                # Step 2: Wait for solution
                start_time = asyncio.get_event_loop().time()
                while True:
                    if asyncio.get_event_loop().time() - start_time > self.timeout:
                        logger.warning("captcha.timeout", captcha_id=captcha_id)
                        return None
                    
                    result_response = await client.get(
                        f"https://api.2captcha.com/res/{captcha_id}",
                        params={"key": self.api_key, "action": "get", "json": 1}
                    )
                    
                    if result_response.status_code != 200:
                        await asyncio.sleep(2)
                        continue
                    
                    data = result_response.json()
                    if data.get("status") == 1:
                        solution = data.get("text")
                        if solution:
                            logger.info("captcha.solved", captcha_id=captcha_id)
                            return solution
                    elif data.get("status") == 0 and data.get("error") == "CAPCHA_NOT_READY":
                        await asyncio.sleep(2)
                        continue
                    else:
                        logger.error("captcha.solve_error", error=data.get("error"))
                        return None
                        
            except Exception as e:
                logger.exception("captcha.2captcha_error", error=str(e))
                return None
    
    async def _solve_anticaptcha(self, image_base64: str, captcha_type: str) -> Optional[str]:
        """Solve captcha using AntiCaptcha API."""
        if not self.api_key:
            logger.error("captcha.no_api_key", provider="anticaptcha")
            return None
        
        # Similar implementation for AntiCaptcha
        # ... (would be implemented similarly)
        return None
    
    async def _solve_human(
        self,
        image_base64: str,
        captcha_type: str,
        page: Optional[Page]
    ) -> Optional[str]:
        """
        Human-in-the-loop captcha solving.
        Sends captcha to UI for user to solve.
        """
        captcha_id = f"captcha_{id(image_base64)}"
        
        # Store the captcha for UI to display
        # This would be shown in the frontend
        # For now, we'll log it and wait
        logger.info("captcha.human_waiting", captcha_id=captcha_id)
        
        # Create event to wait for solution
        event = asyncio.Event()
        self._pending_solutions[captcha_id] = event
        
        # Store the image for retrieval
        self._solutions[captcha_id] = image_base64
        
        # Wait for human to solve (up to timeout)
        try:
            await asyncio.wait_for(event.wait(), timeout=self.timeout)
            solution = self._solutions.get(f"{captcha_id}_solution")
            if solution:
                return solution
        except asyncio.TimeoutError:
            logger.warning("captcha.human_timeout", captcha_id=captcha_id)
        finally:
            self._pending_solutions.pop(captcha_id, None)
            self._solutions.pop(captcha_id, None)
        
        return None
    
    def submit_human_solution(self, captcha_id: str, solution: str) -> bool:
        """Submit a human-provided captcha solution."""
        if captcha_id in self._pending_solutions:
            self._solutions[f"{captcha_id}_solution"] = solution
            self._pending_solutions[captcha_id].set()
            return True
        return False
    
    async def solve_recaptcha(
        self,
        site_key: str,
        page_url: str,
        page: Optional[Page] = None
    ) -> Optional[str]:
        """
        Solve reCAPTCHA v2.
        """
        logger.info("captcha.solving_recaptcha", site_key=site_key)
        
        if self.provider == "2captcha":
            # Special method for reCAPTCHA
            async with httpx.AsyncClient(timeout=30) as client:
                try:
                    # Submit reCAPTCHA task
                    data = {
                        "key": self.api_key,
                        "method": "userrecaptcha",
                        "googlekey": site_key,
                        "pageurl": page_url,
                        "json": 1,
                    }
                    
                    response = await client.post(
                        "https://api.2captcha.com/upload",
                        data=data
                    )
                    
                    if response.status_code != 200:
                        return None
                    
                    result = response.json()
                    if result.get("status") != 1:
                        return None
                    
                    captcha_id = result.get("captcha_id")
                    
                    # Wait for solution
                    start_time = asyncio.get_event_loop().time()
                    while True:
                        if asyncio.get_event_loop().time() - start_time > self.timeout:
                            return None
                        
                        result_response = await client.get(
                            f"https://api.2captcha.com/res/{captcha_id}",
                            params={"key": self.api_key, "action": "get", "json": 1}
                        )
                        
                        if result_response.status_code != 200:
                            await asyncio.sleep(2)
                            continue
                        
                        data = result_response.json()
                        if data.get("status") == 1:
                            return data.get("text")
                        elif data.get("status") == 0 and data.get("error") == "CAPCHA_NOT_READY":
                            await asyncio.sleep(2)
                            continue
                        else:
                            return None
                            
                except Exception as e:
                    logger.exception("captcha.recaptcha_error", error=str(e))
                    return None
        
        return None


# ─── Global instance ─────────────────────────────────────────────

captcha_solver = CaptchaSolver()