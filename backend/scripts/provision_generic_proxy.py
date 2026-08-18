"""Create or reuse the shared generic n8n proxy workflow."""

import asyncio

from app.services.n8n import N8nClient


if __name__ == "__main__":
    print(asyncio.run(N8nClient().ensure_generic_proxy()))
