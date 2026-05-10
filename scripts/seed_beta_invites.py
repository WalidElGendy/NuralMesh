#!/usr/bin/env python3
"""Seed unclaimed beta invite codes into Supabase."""

from __future__ import annotations

import argparse
import os
import secrets
from typing import Any

from supabase import create_client


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed NeuralMesh beta invite codes.")
    parser.add_argument("--count", type=int, required=True, help="Number of invite codes to create.")
    parser.add_argument("--notes", default="Initial beta invite seed", help="Notes stored on each invite.")
    return parser.parse_args()


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def build_invites(count: int, notes: str) -> list[dict[str, Any]]:
    if count < 1:
        raise SystemExit("--count must be greater than zero")

    return [
        {
            "code": f"beta-{secrets.token_hex(6)}",
            "notes": notes,
        }
        for _ in range(count)
    ]


def main() -> None:
    args = parse_args()
    supabase = create_client(
        require_env("SUPABASE_URL"),
        require_env("SUPABASE_SERVICE_ROLE_KEY"),
    )
    invites = build_invites(args.count, args.notes)
    result = supabase.table("invites").insert(invites).execute()
    inserted = len(result.data or [])
    print(f"Seeded {inserted} beta invites.")


if __name__ == "__main__":
    main()
