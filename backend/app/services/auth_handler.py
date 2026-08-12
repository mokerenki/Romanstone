# backend/app/services/auth_handler.py

import asyncio
import json
import os
import structlog
from typing import Dict, Any, Optional, List
from playwright.async_api import Page, BrowserContext

from app.services.persistent_browser import persistent_browser
from app.services.captcha_solver import captcha_solver

logger = structlog.get_logger("synthai.services.auth")


class AuthHandler:
    """
    Handles authentication flows with automatic login and 2FA handling.
    Supports persistent sessions across tasks.
    """
    
    def __init__(self):
        self._credentials: Dict[str, Dict[str, Any]] = {}  # user_id -> {site: creds}
        self._sessions: Dict[str, Dict[str, Any]] = {}  # user_id -> {site: session_data}
    
    async def get_credentials(self, user_id: str, site: str) -> Optional[Dict[str, Any]]:
        """Get stored credentials for a site."""
        if user_id in self._credentials:
            return self._credentials[user_id].get(site)
        return None
    
    async def store_credentials(
        self,
        user_id: str,
        site: str,
        credentials: Dict[str, Any]
    ) -> None:
        """Store credentials for a site."""
        if user_id not in self._credentials:
            self._credentials[user_id] = {}
        self._credentials[user_id][site] = credentials
        logger.info("auth.credentials_stored", user_id=user_id, site=site)
    
    async def login(
        self,
        user_id: str,
        site: str,
        url: str,
        credentials: Optional[Dict[str, Any]] = None,
        selectors: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Handle login flow for a site.
        
        Args:
            user_id: User identifier
            site: Site name (e.g., "linkedin", "salesforce")
            url: Login page URL
            credentials: Optional credentials (uses stored if not provided)
            selectors: Custom selectors for login form
        """
        # Use provided credentials or stored
        if credentials is None:
            credentials = await self.get_credentials(user_id, site)
        
        if not credentials:
            return {
                "status": "error",
                "message": f"No credentials found for {site}",
                "requires_credentials": True,
            }
        
        # Get browser page
        page = await persistent_browser.get_page(user_id)
        
        # Navigate to login page
        await page.goto(url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=10000)
        
        # Default selectors
        default_selectors = {
            "email": 'input[type="email"], input[name="email"], input[name="username"], input[id*="email"]',
            "password": 'input[type="password"]',
            "submit": 'button[type="submit"], input[type="submit"], button:has-text("Sign In"), button:has-text("Login")',
        }
        
        selectors = selectors or {}
        email_selector = selectors.get("email") or default_selectors["email"]
        password_selector = selectors.get("password") or default_selectors["password"]
        submit_selector = selectors.get("submit") or default_selectors["submit"]
        
        try:
            # Fill credentials
            await page.fill(email_selector, credentials.get("email", ""))
            await page.fill(password_selector, credentials.get("password", ""))
            
            # Handle 2FA if needed
            needs_2fa = await self._detect_2fa(page)
            if needs_2fa:
                logger.info("auth.2fa_detected", user_id=user_id, site=site)
                
                # Get 2FA code
                otp = await self._get_2fa_code(user_id, site, credentials)
                if otp:
                    otp_selector = selectors.get("otp") or 'input[name="otp"], input[name="code"], input[placeholder*="code"]'
                    await page.fill(otp_selector, otp)
                    await page.click(submit_selector)
                else:
                    return {
                        "status": "requires_2fa",
                        "message": "2FA code required",
                    }
            else:
                # Submit login
                await page.click(submit_selector)
            
            # Wait for login to complete
            await page.wait_for_load_state("networkidle", timeout=15000)
            
            # Check if login was successful
            is_logged_in = await self._verify_logged_in(page, site)
            
            if is_logged_in:
                logger.info("auth.login_success", user_id=user_id, site=site)
                return {
                    "status": "ok",
                    "message": f"Successfully logged into {site}",
                    "url": page.url,
                }
            else:
                # Check for captcha
                captcha_detected = await self._detect_captcha(page)
                if captcha_detected:
                    logger.info("auth.captcha_detected", user_id=user_id, site=site)
                    return await self._handle_captcha(page, user_id, site)
                
                return {
                    "status": "error",
                    "message": "Login failed - please check credentials",
                }
                
        except Exception as e:
            logger.exception("auth.login_failed", user_id=user_id, site=site, error=str(e))
            return {
                "status": "error",
                "message": f"Login error: {str(e)}",
            }
    
    async def _detect_2fa(self, page: Page) -> bool:
        """Detect if 2FA is required."""
        try:
            # Check for 2FA input fields
            content = await page.content()
            content_lower = content.lower()
            
            # Common 2FA indicators
            indicators = [
                "verification code",
                "two-factor",
                "2fa",
                "authenticator",
                "otp",
                "one-time password",
            ]
            
            for indicator in indicators:
                if indicator in content_lower:
                    return True
            
            # Check for specific elements
            otp_elements = await page.query_selector_all('input[name="otp"], input[name="code"], input[placeholder*="code"]')
            if otp_elements:
                return True
                
        except Exception:
            pass
        
        return False
    
    async def _detect_captcha(self, page: Page) -> bool:
        """Detect if a captcha is present."""
        try:
            content = await page.content()
            content_lower = content.lower()
            
            indicators = [
                "captcha",
                "recaptcha",
                "hcaptcha",
                "verify you are human",
                "i'm not a robot",
            ]
            
            for indicator in indicators:
                if indicator in content_lower:
                    return True
                    
        except Exception:
            pass
        
        return False
    
    async def _handle_captcha(
        self,
        page: Page,
        user_id: str,
        site: str
    ) -> Dict[str, Any]:
        """Handle captcha challenge."""
        try:
            # Try to get captcha image
            captcha_images = await page.query_selector_all('img[src*="captcha"], img[alt*="captcha"]')
            
            if captcha_images:
                # Get first captcha image
                img = captcha_images[0]
                src = await img.get_attribute("src")
                
                if src:
                    # Capture the image
                    screenshot = await img.screenshot()
                    image_b64 = base64.b64encode(screenshot).decode("utf-8")
                    
                    # Solve captcha
                    solution = await captcha_solver.solve_image_captcha(
                        image_b64,
                        "image",
                        page
                    )
                    
                    if solution:
                        # Find captcha input
                        captcha_input = await page.query_selector('input[placeholder*="captcha"], input[id*="captcha"]')
                        if captcha_input:
                            await captcha_input.fill(solution)
                            await page.click('button[type="submit"], input[type="submit"]')
                            
                            # Wait for result
                            await page.wait_for_load_state("networkidle", timeout=5000)
                            
                            # Check if solved
                            is_solved = not await self._detect_captcha(page)
                            if is_solved:
                                logger.info("auth.captcha_solved", user_id=user_id, site=site)
                                
                                # Try login again
                                return await self.login(user_id, site, page.url)
            
            return {
                "status": "captcha_required",
                "message": "Captcha needs manual solving",
            }
            
        except Exception as e:
            logger.exception("auth.captcha_handling_failed", error=str(e))
            return {
                "status": "error",
                "message": f"Captcha handling failed: {str(e)}",
            }
    
    async def _get_2fa_code(
        self,
        user_id: str,
        site: str,
        credentials: Dict[str, Any]
    ) -> Optional[str]:
        """Get 2FA code from credentials or prompt."""
        # Check if OTP is in credentials
        if "otp" in credentials:
            return credentials["otp"]
        
        # Check for OTP in stored session
        if user_id in self._sessions and site in self._sessions[user_id]:
            return self._sessions[user_id][site].get("otp")
        
        # If OTP not available, ask user
        # This would be handled via WebSocket/UI
        logger.info("auth.2fa_required", user_id=user_id, site=site)
        
        # Return None to signal 2FA required
        return None
    
    async def _verify_logged_in(self, page: Page, site: str) -> bool:
        """Verify if user is logged in."""
        try:
            content = await page.content()
            content_lower = content.lower()
            
            # Success indicators
            success_indicators = [
                "dashboard",
                "profile",
                "logout",
                "sign out",
                "my account",
            ]
            
            # Failure indicators
            failure_indicators = [
                "invalid credentials",
                "sign in",
                "log in",
                "try again",
                "incorrect password",
            ]
            
            # Check for success
            for indicator in success_indicators:
                if indicator in content_lower:
                    return True
            
            # Check for failure
            for indicator in failure_indicators:
                if indicator in content_lower:
                    return False
            
            # Check URL for known success paths
            url = page.url
            if any(x in url for x in ["/dashboard", "/home", "/app", "/logged-in"]):
                return True
                
        except Exception:
            pass
        
        # Default: check if page changed from login page
        return "login" not in page.url.lower()
    
    def submit_2fa_code(self, user_id: str, site: str, code: str) -> None:
        """Submit 2FA code for a user."""
        if user_id not in self._sessions:
            self._sessions[user_id] = {}
        if site not in self._sessions[user_id]:
            self._sessions[user_id][site] = {}
        self._sessions[user_id][site]["otp"] = code
        logger.info("auth.2fa_submitted", user_id=user_id, site=site)


# ─── Global instance ─────────────────────────────────────────────

auth_handler = AuthHandler()