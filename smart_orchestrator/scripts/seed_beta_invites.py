from __future__ import annotations

import argparse
import asyncio
import os

import httpx


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed root NeuralMesh beta invite codes.")
    parser.add_argument("--api-base", default=os.getenv("API_BASE", "http://localhost:8000"))
    parser.add_argument("--admin-secret", default=os.getenv("ADMIN_SECRET", "change-me-in-prod"))
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{args.api_base.rstrip('/')}/api/admin/seed-invites",
            headers={"X-Admin-Secret": args.admin_secret},
            json={"count": args.count, "created_by": "launch-admin"},
        )
    response.raise_for_status()
    for invite in response.json()["invites"]:
        print(invite["code"])


if __name__ == "__main__":
    asyncio.run(main())

