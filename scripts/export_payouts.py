#!/usr/bin/env python3
"""Export manual beta provider payouts to CSV."""
from __future__ import annotations

import argparse
import csv
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from supabase import create_client


DEFAULT_CREDIT_USD = float(os.environ.get("BETA_CREDIT_USD", "0.0025"))


def previous_month(now: datetime) -> str:
    first_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_previous_month = first_this_month - timedelta(days=1)
    return last_previous_month.strftime("%Y-%m")


def period_bounds(period: str) -> tuple[str, str]:
    start = datetime.strptime(period, "%Y-%m").replace(tzinfo=UTC)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY are required.")
    return create_client(url, key)


def payout_method_label(provider: dict[str, Any]) -> str:
    method = provider.get("payout_method") or {}
    if not isinstance(method, dict):
        return str(method)
    if method.get("paypal_email"):
        return f"paypal:{method['paypal_email']}"
    if method.get("btc_address"):
        return f"btc:{method['btc_address']}"
    if method.get("wire_details"):
        return "wire:on_file"
    return "not_configured"


def export(period: str, output: Path, credit_usd: float) -> Path:
    supabase = get_supabase()
    start, end = period_bounds(period)
    providers = supabase.table("providers").select("id,email,payout_method").execute().data or []
    jobs = (
        supabase.table("provider_jobs")
        .select("provider_id,credits")
        .gte("created_at", start)
        .lt("created_at", end)
        .eq("status", "success")
        .execute()
        .data
        or []
    )

    credits_by_provider: dict[str, float] = {}
    for job in jobs:
        provider_id = job["provider_id"]
        credits_by_provider[provider_id] = credits_by_provider.get(provider_id, 0.0) + float(
            job.get("credits") or 0
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "provider_id",
                "email",
                "payout_method",
                "credits",
                "USD equivalent",
                "period",
            ],
        )
        writer.writeheader()
        for provider in providers:
            credits = round(credits_by_provider.get(provider["id"], 0.0), 4)
            if credits <= 0:
                continue
            writer.writerow(
                {
                    "provider_id": provider["id"],
                    "email": provider["email"],
                    "payout_method": payout_method_label(provider),
                    "credits": f"{credits:.4f}",
                    "USD equivalent": f"{credits * credit_usd:.2f}",
                    "period": period,
                }
            )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Export manual beta provider payouts.")
    parser.add_argument("--period", default=previous_month(datetime.now(UTC)), help="YYYY-MM period")
    parser.add_argument("--credit-usd", type=float, default=DEFAULT_CREDIT_USD)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    output = Path(args.output or f"provider_payouts_{args.period}.csv")
    written = export(args.period, output, args.credit_usd)
    print(f"Wrote {written}")


if __name__ == "__main__":
    main()
