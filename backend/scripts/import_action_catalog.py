"""Import action catalog rows from a vetted local JSON file."""

import asyncio
import json
import sys

from app.services.action_catalog import ActionCatalogEntry, upsert_actions


async def main(path: str) -> None:
    if path == "-":
        rows = json.load(sys.stdin)
    else:
        with open(path, encoding="utf-8") as source:
            rows = json.load(source)
    if not isinstance(rows, list):
        raise ValueError("Action catalog JSON must contain an array of action objects.")
    await upsert_actions([ActionCatalogEntry(**row) for row in rows])
    print(f"Imported {len(rows)} action catalog entries.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.import_action_catalog <actions.json|->")
    asyncio.run(main(sys.argv[1]))
