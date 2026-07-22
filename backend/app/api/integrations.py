from fastapi import APIRouter, Depends
from typing import Dict, Any, List
from app.core import instances

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

@router.get("/")
async def list_integrations() -> Dict[str, Any]:
    """List all MCP integrations and their status."""
    integrations = []
    mcp_registry = instances.mcp_registry
    if mcp_registry:
        for name, client in mcp_registry.clients.items():
            # Check if client is connected
            status = "connected" if client._session else "disconnected"
            integrations.append({
                "id": name,
                "name": name,
                "type": "mcp",
                "status": status,
                "config": {},
                "description": f"MCP server: {name}"
            })
    return {"integrations": integrations}

@router.post("/{integration_id}/sync")
async def sync_integration(integration_id: str) -> Dict[str, Any]:
    """Force sync tools from an MCP server."""
    mcp_registry = instances.mcp_registry
    if not mcp_registry:
        return {"error": "MCP registry not initialized"}
    client = mcp_registry.clients.get(integration_id)
    if not client:
        return {"error": "Integration not found"}
    try:
        await client.connect()
        tools = await client.list_tools()
        # Re-register tools (could be smarter)
        return {"status": "success", "tools_count": len(tools)}
    except Exception as e:
        return {"error": str(e)}