# backend/app/services/persistent_browser.py

import asyncio
import json
import structlog
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from app.core.context import synthai

logger = structlog.get_logger("synthai.services.persistent_browser")


class PersistentBrowserService:
    """
    Manages persistent browser sessions per user.
    Cookies, localStorage, and sessions persist across tasks.
    """
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._sessions: Dict[str, Dict[str, Any]] = {}  # user_id -> session data
        self._playwright = None
        self._initialized = False
        
    async def initialize(self):
        """Initialize the browser service."""
        if self._initialized:
            return
        
        self._playwright = await async_playwright().start()
        self._initialized = True
        logger.info("persistent_browser.initialized")
    
    async def _get_browser_context(self, user_id: str) -> BrowserContext:
        """Get or create a browser context for a user."""
        await self.initialize()
        
        # Check if we already have a context for this user
        if user_id in self._sessions:
            session = self._sessions[user_id]
            context = session.get("context")
            
            # Check if context is still valid
            if context:
                try:
                    # Test if context is alive
                    await context.pages
                    session["last_used"] = datetime.now(timezone.utc).isoformat()
                    return context
                except Exception:
                    # Context is dead, recreate
                    await self._close_session(user_id)
        
        # Create new context with persistent storage
        context = await self._create_context(user_id)
        
        self._sessions[user_id] = {
            "context": context,
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_used": datetime.now(timezone.utc).isoformat(),
            "pages": [],
        }
        
        logger.info("persistent_browser.context_created", user_id=user_id)
        return context
    
    async def _create_context(self, user_id: str) -> BrowserContext:
        """Create a new browser context with persistent storage."""
        browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-setuid-sandbox',
            ]
        )
        
        # Use persistent storage path for this user
        storage_path = f"/tmp/browser_data/{user_id}"
        
        context = await browser.new_context(
            user_data_dir=storage_path,
            storage_state=f"/tmp/browser_state/{user_id}.json",
            viewport={"width": 1280, "height": 720},
        )
        
        # Load saved storage state if exists
        try:
            await context.storage_state()
        except Exception:
            pass
        
        return context
    
    async def get_page(self, user_id: str) -> Page:
        """Get or create a page for the user."""
        context = await self._get_browser_context(user_id)
        
        session = self._sessions.get(user_id)
        if session and session.get("pages"):
            # Reuse last page
            page = session["pages"][-1]
            if not page.is_closed():
                return page
        
        # Create new page
        page = await context.new_page()
        if session:
            session["pages"].append(page)
            session["last_used"] = datetime.now(timezone.utc).isoformat()
        
        return page
    
    async def navigate(self, user_id: str, url: str) -> Dict[str, Any]:
        """Navigate to a URL in the user's browser."""
        try:
            page = await self.get_page(user_id)
            await page.goto(url, timeout=30000)
            
            return {
                "status": "ok",
                "url": page.url,
                "title": await page.title(),
            }
        except Exception as e:
            logger.exception("browser.navigate_failed", user_id=user_id, url=url, error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def click(self, user_id: str, selector: str) -> Dict[str, Any]:
        """Click an element in the user's browser."""
        try:
            page = await self.get_page(user_id)
            await page.click(selector, timeout=30000)
            return {"status": "ok", "selector": selector}
        except Exception as e:
            logger.exception("browser.click_failed", user_id=user_id, selector=selector, error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def fill(self, user_id: str, selector: str, text: str) -> Dict[str, Any]:
        """Fill a form field in the user's browser."""
        try:
            page = await self.get_page(user_id)
            await page.fill(selector, text, timeout=30000)
            return {"status": "ok", "selector": selector}
        except Exception as e:
            logger.exception("browser.fill_failed", user_id=user_id, selector=selector, error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def get_content(self, user_id: str) -> Dict[str, Any]:
        """Get the page content."""
        try:
            page = await self.get_page(user_id)
            content = await page.content()
            return {
                "status": "ok",
                "content": content,
                "url": page.url,
            }
        except Exception as e:
            logger.exception("browser.get_content_failed", user_id=user_id, error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def screenshot(self, user_id: str) -> Dict[str, Any]:
        """Take a screenshot of the user's browser."""
        try:
            page = await self.get_page(user_id)
            screenshot_bytes = await page.screenshot()
            import base64
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            return {
                "status": "ok",
                "screenshot_base64": screenshot_b64,
                "size": len(screenshot_bytes),
            }
        except Exception as e:
            logger.exception("browser.screenshot_failed", user_id=user_id, error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def evaluate(self, user_id: str, script: str) -> Dict[str, Any]:
        """Evaluate JavaScript in the user's browser."""
        try:
            page = await self.get_page(user_id)
            result = await page.evaluate(script)
            return {"status": "ok", "result": result}
        except Exception as e:
            logger.exception("browser.evaluate_failed", user_id=user_id, error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def get_cookies(self, user_id: str) -> Dict[str, Any]:
        """Get cookies from the user's browser."""
        try:
            context = await self._get_browser_context(user_id)
            cookies = await context.cookies()
            return {"status": "ok", "cookies": cookies}
        except Exception as e:
            logger.exception("browser.get_cookies_failed", user_id=user_id, error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def set_cookies(self, user_id: str, cookies: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Set cookies in the user's browser."""
        try:
            context = await self._get_browser_context(user_id)
            await context.add_cookies(cookies)
            return {"status": "ok", "cookies_set": len(cookies)}
        except Exception as e:
            logger.exception("browser.set_cookies_failed", user_id=user_id, error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def close_session(self, user_id: str) -> None:
        """Close a user's browser session."""
        await self._close_session(user_id)
    
    async def _close_session(self, user_id: str) -> None:
        """Internal method to close a session."""
        if user_id in self._sessions:
            session = self._sessions.pop(user_id)
            context = session.get("context")
            if context:
                try:
                    # Save storage state before closing
                    try:
                        storage = await context.storage_state()
                        # Save to disk
                        import os
                        os.makedirs("/tmp/browser_state", exist_ok=True)
                        with open(f"/tmp/browser_state/{user_id}.json", "w") as f:
                            json.dump(storage, f)
                    except Exception:
                        pass
                    
                    await context.close()
                except Exception as e:
                    logger.warning("browser.context_close_failed", user_id=user_id, error=str(e))
            
            logger.info("persistent_browser.session_closed", user_id=user_id)
    
    async def shutdown(self):
        """Shutdown all browser sessions."""
        for user_id in list(self._sessions.keys()):
            await self._close_session(user_id)
        
        if self._playwright:
            await self._playwright.stop()
        
        logger.info("persistent_browser.shutdown")


# ─── Global Instance ─────────────────────────────────────────────

persistent_browser = PersistentBrowserService(headless=True)