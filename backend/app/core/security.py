"""Security — Phase 2 (SCAFFOLD)

JWT authentication and RBAC middleware.
TODO: Implement JWT token creation/validation, role-based access control.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """TODO: Validate JWT token, return user dict."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                        detail="JWT authentication not yet implemented (Phase 2)")

async def require_role(role: str):
    """TODO: RBAC middleware factory."""
    async def role_checker(user=Depends(get_current_user)):
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                            detail=f"RBAC not yet implemented (Phase 2): required role {role}")
    return role_checker
