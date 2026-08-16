"""Server-side access to Nango Connect and Proxy.

Nango owns end-user OAuth credentials. SynthAI only stores the opaque
connection ID and provider configuration key returned after Connect succeeds.
"""

import os
from typing import Any, Dict

import httpx


class NangoError(RuntimeError):
    pass


NANGO_INTEGRATIONS = {
    "slack": "slack",
    "google_calendar": "google",
    "google_meet": "google",
    "notion": "notion",
    "salesforce": "salesforce",
}


class NangoClient:
    def __init__(self) -> None:
        self.api_url = os.getenv("NANGO_API_URL", "http://nango-server:3003").rstrip("/")
        self.secret_key = os.getenv("NANGO_SECRET_KEY", "").strip()
        self.public_url = os.getenv("NANGO_PUBLIC_URL", "http://localhost:3003").rstrip("/")
        self.connect_url = os.getenv("NANGO_CONNECT_URL", "http://localhost:3009").rstrip("/")

    def _headers(self) -> Dict[str, str]:
        if not self.secret_key:
            raise NangoError("NANGO_SECRET_KEY is not configured")
        return {"Authorization": f"Bearer {self.secret_key}", "Content-Type": "application/json"}

    async def create_connect_session(self, user_id: str, tenant_id: str, integration_id: str) -> Dict[str, str]:
        provider_config_key = NANGO_INTEGRATIONS.get(integration_id)
        if not provider_config_key:
            raise NangoError(f"Nango OAuth is not configured for {integration_id}")
        payload = {
            "end_user": {"id": user_id},
            "organization": {"id": tenant_id or user_id},
            "allowed_integrations": [provider_config_key],
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(f"{self.api_url}/connect/sessions", headers=self._headers(), json=payload)
        except httpx.HTTPError as exc:
            raise NangoError(f"Nango is unavailable: {exc}") from exc
        if response.is_error:
            raise NangoError(f"Nango API {response.status_code}: {response.text[:500]}")
        data = response.json().get("data", response.json())
        return {
            "session_token": data["token"],
            "host": self.public_url,
            "connect_url": self.connect_url,
            "provider_config_key": provider_config_key,
        }
