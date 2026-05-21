"""DesktopAgent — Phase 2 (SCAFFOLD)

Observe → Propose → Act loop for GUI automation via VNC.
Inspired by Agent-S2 and vnc-use.

TODO: Implement VNC framebuffer capture, visual grounding with Kimi K2/UI-TARS,
      human-in-the-loop gating, session recording to S3/MinIO.
"""

from typing import Any, Dict

class DesktopAgent:
    """SCAFFOLD — Phase 2 implementation pending."""

    async def observe(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """TODO: Capture VNC screenshot, analyze UI state."""
        raise NotImplementedError("DesktopAgent.observe() — Phase 2")

    async def propose(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """TODO: Generate action proposal from visual state."""
        raise NotImplementedError("DesktopAgent.propose() — Phase 2")

    async def act(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        """TODO: Execute PyAutoGUI/xdotool action, gated by HITL."""
        raise NotImplementedError("DesktopAgent.act() — Phase 2")
