# backend/app/api/sandbox_api.py

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, Response
from typing import Optional, List, Dict, Any
import structlog
import json

from app.sandbox.persistent_manager import persistent_sandbox_manager

logger = structlog.get_logger("synthai.api.sandbox")
router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


# ─── Sandbox Status ──────────────────────────────────────────────

@router.get("/status")
async def get_sandbox_status(user_id: str = Query("default")) -> Dict[str, Any]:
    """Get the status of a user's sandbox."""
    try:
        await persistent_sandbox_manager.initialize()
        status = await persistent_sandbox_manager.get_sandbox_status(user_id)
        return status
    except Exception as e:
        logger.exception("sandbox.status_failed", user_id=user_id, error=str(e))
        raise HTTPException(500, f"Failed to get sandbox status: {str(e)}")


# ─── Execute Code ─────────────────────────────────────────────────

@router.post("/execute")
async def execute_code(
    user_id: str = Query("default"),
    code: str = Form(...),
    timeout: int = Form(30)
) -> Dict[str, Any]:
    """Execute code in the user's persistent sandbox."""
    try:
        await persistent_sandbox_manager.initialize()
        result = await persistent_sandbox_manager.execute_in_sandbox(
            user_id=user_id,
            command=code,
            timeout=timeout
        )
        return result
    except Exception as e:
        logger.exception("sandbox.execute_failed", user_id=user_id, error=str(e))
        raise HTTPException(500, f"Failed to execute code: {str(e)}")


# ─── File System Operations ──────────────────────────────────────

@router.get("/files/list")
async def list_files(
    user_id: str = Query("default"),
    path: str = Query("/workspace")
) -> Dict[str, Any]:
    """List files in the user's sandbox."""
    try:
        await persistent_sandbox_manager.initialize()
        files = await persistent_sandbox_manager.list_files(user_id, path)
        return {
            "path": path,
            "files": files,
            "count": len(files),
        }
    except Exception as e:
        logger.exception("sandbox.list_files_failed", user_id=user_id, path=path, error=str(e))
        raise HTTPException(500, f"Failed to list files: {str(e)}")


@router.get("/files/read")
async def read_file(
    user_id: str = Query("default"),
    path: str = Query(...)
) -> Dict[str, Any]:
    """Read a file from the user's sandbox."""
    try:
        await persistent_sandbox_manager.initialize()
        result = await persistent_sandbox_manager.read_file(user_id, path)
        if result.get("status") == "error":
            raise HTTPException(404, result.get("error", "File not found"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("sandbox.read_file_failed", user_id=user_id, path=path, error=str(e))
        raise HTTPException(500, f"Failed to read file: {str(e)}")


@router.post("/files/write")
async def write_file(
    user_id: str = Query("default"),
    path: str = Form(...),
    content: str = Form(...)
) -> Dict[str, Any]:
    """Write a file to the user's sandbox."""
    try:
        await persistent_sandbox_manager.initialize()
        result = await persistent_sandbox_manager.write_file(user_id, path, content)
        if result.get("status") == "error":
            raise HTTPException(400, result.get("error", "Failed to write file"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("sandbox.write_file_failed", user_id=user_id, path=path, error=str(e))
        raise HTTPException(500, f"Failed to write file: {str(e)}")


@router.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    user_id: str = Form("default"),
    path: str = Form("/workspace")
) -> Dict[str, Any]:
    """Upload a file to the user's sandbox."""
    try:
        await persistent_sandbox_manager.initialize()
        
        content = await file.read()
        full_path = f"{path}/{file.filename}" if path != "/" else f"/{file.filename}"
        
        result = await persistent_sandbox_manager.upload_file(
            user_id=user_id,
            path=full_path,
            content_bytes=content
        )
        
        if result.get("status") == "error":
            raise HTTPException(400, result.get("error", "Failed to upload file"))
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("sandbox.upload_file_failed", user_id=user_id, path=path, error=str(e))
        raise HTTPException(500, f"Failed to upload file: {str(e)}")


@router.delete("/files/delete")
async def delete_file(
    user_id: str = Query("default"),
    path: str = Query(...)
) -> Dict[str, Any]:
    """Delete a file from the user's sandbox."""
    try:
        await persistent_sandbox_manager.initialize()
        result = await persistent_sandbox_manager.delete_file(user_id, path)
        if result.get("status") == "error":
            raise HTTPException(404, result.get("error", "File not found"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("sandbox.delete_file_failed", user_id=user_id, path=path, error=str(e))
        raise HTTPException(500, f"Failed to delete file: {str(e)}")


@router.get("/files/download")
async def download_file(
    user_id: str = Query("default"),
    path: str = Query(...)
) -> Response:
    """Download a file from the user's sandbox."""
    try:
        await persistent_sandbox_manager.initialize()
        result = await persistent_sandbox_manager.read_file(user_id, path)
        
        if result.get("status") == "error":
            raise HTTPException(404, result.get("error", "File not found"))
        
        content = result.get("content", "")
        filename = path.split("/")[-1]
        
        return Response(
            content=content.encode('utf-8'),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("sandbox.download_file_failed", user_id=user_id, path=path, error=str(e))
        raise HTTPException(500, f"Failed to download file: {str(e)}")


# ─── Sandbox Management ──────────────────────────────────────────

@router.post("/destroy")
async def destroy_sandbox(user_id: str = Query("default")) -> Dict[str, Any]:
    """Destroy a user's sandbox."""
    try:
        await persistent_sandbox_manager.initialize()
        result = await persistent_sandbox_manager.destroy_sandbox(user_id)
        return {"status": "destroyed", "user_id": user_id, "success": result}
    except Exception as e:
        logger.exception("sandbox.destroy_failed", user_id=user_id, error=str(e))
        raise HTTPException(500, f"Failed to destroy sandbox: {str(e)}")


@router.get("/stats")
async def get_sandbox_stats() -> Dict[str, Any]:
    """Get sandbox statistics."""
    try:
        await persistent_sandbox_manager.initialize()
        sandboxes = persistent_sandbox_manager._sandboxes
        
        return {
            "active_sandboxes": len(sandboxes),
            "users": list(sandboxes.keys()),
            "details": [
                {
                    "user_id": user_id,
                    "sandbox_id": data.get("sandbox_id"),
                    "created_at": data.get("created_at"),
                    "last_used": data.get("last_used"),
                }
                for user_id, data in sandboxes.items()
            ]
        }
    except Exception as e:
        logger.exception("sandbox.stats_failed", error=str(e))
        raise HTTPException(500, f"Failed to get stats: {str(e)}")


# ─── Terminal Session ────────────────────────────────────────────

@router.post("/terminal")
async def run_terminal_command(
    user_id: str = Query("default"),
    command: str = Form(...)
) -> Dict[str, Any]:
    """Run a terminal command in the user's sandbox."""
    try:
        await persistent_sandbox_manager.initialize()
        result = await persistent_sandbox_manager.execute_in_sandbox(
            user_id=user_id,
            command=command,
            timeout=60
        )
        return {
            "command": command,
            "output": result.get("output", ""),
            "exit_code": result.get("exit_code", 1),
            "error": result.get("error"),
        }
    except Exception as e:
        logger.exception("sandbox.terminal_failed", user_id=user_id, command=command, error=str(e))
        raise HTTPException(500, f"Failed to run command: {str(e)}")