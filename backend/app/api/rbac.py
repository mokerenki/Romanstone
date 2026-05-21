"""RBAC API — Phase 2 (SCAFFOLD)

User/role management endpoints.
TODO: Implement user CRUD, role assignment, permission checks.
"""

from fastapi import APIRouter

router = APIRouter()

@router.get("/users")
async def list_users():
    """TODO: List users with pagination."""
    return {"status": "not_implemented", "phase": "2"}

@router.post("/users")
async def create_user(user: dict):
    """TODO: Create user with role assignment."""
    return {"status": "not_implemented", "phase": "2"}

@router.get("/roles")
async def list_roles():
    """TODO: List available roles and permissions."""
    return {"status": "not_implemented", "phase": "2"}
