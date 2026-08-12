# backend/app/api/connectors.py

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
import structlog
import json
import os
import httpx
import secrets
from datetime import datetime, timezone, timedelta
import base64
from cryptography.fernet import Fernet

from app.core.context import synthai

logger = structlog.get_logger("synthai.api.connectors")
router = APIRouter(prefix="/api/connectors", tags=["connectors"])

# ─── Encryption for credentials ─────────────────────────────────

ENCRYPTION_KEY = os.getenv("CONNECTOR_ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = base64.urlsafe_b64encode(os.urandom(32)).decode()
    logger.warning("connectors.using_generated_key")

cipher = Fernet(ENCRYPTION_KEY.encode())

# ─── OAuth Configurations ───────────────────────────────────────

OAUTH_CONFIGS = {
    "outlook": {
        "client_id": os.getenv("OUTLOOK_CLIENT_ID"),
        "client_secret": os.getenv("OUTLOOK_CLIENT_SECRET"),
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": ["offline_access", "Mail.Read", "Mail.ReadWrite", "Mail.Send", "User.Read"],
        "redirect_uri": os.getenv("OAUTH_REDIRECT_URI", "http://localhost/api/connectors/oauth/callback"),
    },
    "gmail": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send"
        ],
        "redirect_uri": os.getenv("OAUTH_REDIRECT_URI", "http://localhost/api/connectors/oauth/callback"),
    },
    "slack": {
        "client_id": os.getenv("SLACK_CLIENT_ID"),
        "client_secret": os.getenv("SLACK_CLIENT_SECRET"),
        "auth_url": "https://slack.com/oauth/v2/authorize",
        "token_url": "https://slack.com/api/oauth.v2.access",
        "scopes": ["chat:write", "channels:read", "channels:history"],
        "redirect_uri": os.getenv("OAUTH_REDIRECT_URI", "http://localhost/api/connectors/oauth/callback"),
    },
    "github": {
        "client_id": os.getenv("GITHUB_CLIENT_ID"),
        "client_secret": os.getenv("GITHUB_CLIENT_SECRET"),
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scopes": ["repo", "workflow"],
        "redirect_uri": os.getenv("OAUTH_REDIRECT_URI", "http://localhost/api/connectors/oauth/callback"),
    },
    "salesforce": {
        "client_id": os.getenv("SALESFORCE_CLIENT_ID"),
        "client_secret": os.getenv("SALESFORCE_CLIENT_SECRET"),
        "auth_url": "https://login.salesforce.com/services/oauth2/authorize",
        "token_url": "https://login.salesforce.com/services/oauth2/token",
        "scopes": ["api", "refresh_token"],
        "redirect_uri": os.getenv("OAUTH_REDIRECT_URI", "http://localhost/api/connectors/oauth/callback"),
    },
}

# ─── Helper Functions ───────────────────────────────────────────

def _get_connector_key(connector_id: str, user_id: str) -> str:
    return f"synthai:connector:{user_id}:{connector_id}"

async def _get_stored_credentials(connector_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    ctx = synthai
    key = _get_connector_key(connector_id, user_id)
    data = await ctx.redis_client.get(key)
    if data:
        try:
            encrypted = json.loads(data)
            decrypted = cipher.decrypt(encrypted["data"].encode())
            return json.loads(decrypted)
        except Exception:
            return None
    return None

async def _store_credentials(connector_id: str, user_id: str, credentials: Dict[str, Any]) -> None:
    ctx = synthai
    key = _get_connector_key(connector_id, user_id)
    encrypted = cipher.encrypt(json.dumps(credentials).encode())
    await ctx.redis_client.setex(
        key,
        86400 * 30,
        json.dumps({"data": encrypted.decode()})
    )

async def _delete_credentials(connector_id: str, user_id: str) -> None:
    ctx = synthai
    key = _get_connector_key(connector_id, user_id)
    await ctx.redis_client.delete(key)

# ─── API Endpoints ──────────────────────────────────────────────

@router.get("/status")
async def get_connector_status(user_id: str = Query("default")):
    """Get status of all connectors for a user."""
    ctx = synthai
    pattern = f"synthai:connector:{user_id}:*"
    keys = await ctx.redis_client.keys(pattern)
    
    connected = []
    for key in keys:
        key_str = key.decode() if isinstance(key, bytes) else key
        connector_id = key_str.split(":")[-1]
        connected.append(connector_id)
    
    return {"connected": connected}

@router.get("/{connector_id}/auth-url")
async def get_auth_url(connector_id: str, user_id: str = Query("default")):
    """Get OAuth URL for a connector."""
    config = OAUTH_CONFIGS.get(connector_id)
    if not config:
        raise HTTPException(404, f"Connector {connector_id} not found")
    
    if not config.get("client_id"):
        raise HTTPException(400, f"Connector {connector_id} is not configured")
    
    state = secrets.token_urlsafe(32)
    
    ctx = synthai
    await ctx.redis_client.setex(
        f"synthai:oauth:state:{user_id}:{state}",
        600,
        connector_id
    )
    
    import urllib.parse
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "state": state,
        "scope": " ".join(config.get("scopes", [])),
        "access_type": "offline",
        "prompt": "select_account",
    }
    
    url = config["auth_url"] + "?" + urllib.parse.urlencode(params)
    return {"url": url, "state": state}

@router.get("/oauth/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    user_id: str = Query("default"),
):
    """OAuth callback handler."""
    ctx = synthai
    
    state_key = f"synthai:oauth:state:{user_id}:{state}"
    connector_id = await ctx.redis_client.get(state_key)
    if not connector_id:
        return JSONResponse(status_code=400, content={"error": "Invalid state"})
    
    connector_id = connector_id.decode() if isinstance(connector_id, bytes) else connector_id
    config = OAUTH_CONFIGS.get(connector_id)
    
    if not config:
        return JSONResponse(status_code=400, content={"error": "Connector not found"})
    
    try:
        async with httpx.AsyncClient() as client:
            token_data = {
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "code": code,
                "redirect_uri": config["redirect_uri"],
                "grant_type": "authorization_code",
            }
            
            response = await client.post(config["token_url"], data=token_data)
            response.raise_for_status()
            tokens = response.json()
        
        credentials = {
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))).isoformat(),
        }
        
        await _store_credentials(connector_id, user_id, credentials)
        await ctx.redis_client.delete(state_key)
        
        return """
        <html>
            <body>
                <script>
                    window.opener.postMessage({type: 'oauth_success', connector: '%s'}, '*');
                    window.close();
                </script>
                <p>Connection successful! You can close this window.</p>
            </body>
        </html>
        """ % connector_id
        
    except Exception as e:
        logger.exception("oauth_callback_failed", connector_id=connector_id, error=str(e))
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/{connector_id}/connect")
async def connect_connector(
    connector_id: str,
    request: Request,
    user_id: str = Query("default"),
):
    """Connect a connector (API key auth)."""
    data = await request.json()
    api_key = data.get("api_key")
    
    if not api_key:
        raise HTTPException(400, "API key is required")
    
    await _store_credentials(connector_id, user_id, {"api_key": api_key})
    return {"status": "connected", "connector_id": connector_id}

@router.post("/{connector_id}/disconnect")
async def disconnect_connector(connector_id: str, user_id: str = Query("default")):
    """Disconnect a connector."""
    await _delete_credentials(connector_id, user_id)
    return {"status": "disconnected", "connector_id": connector_id}