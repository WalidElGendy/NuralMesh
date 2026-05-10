"""In-memory ledger writer for Sprint 1 settlement records."""

from __future__ import annotations

from typing import Any

from app.models.schemas import BillingLedgerEntry, ComputeUnitEntry, ExternalCostEntry, JobRecord, PipelineContext


class InMemoryLedger:
    """Store settlement records in process memory for mocked Sprint 1 runs.

    Args:
        None.

    Returns:
        Ledger writer instance.

    Cost/quality target:
        Zero external database cost while preserving table-shaped records that
        can be replaced with PostgreSQL writes later.
    """

    def __init__(self) -> None:
        self.jobs: list[JobRecord] = []
        self.compute_units: list[ComputeUnitEntry] = []
        self.external_costs: list[ExternalCostEntry] = []
        self.billing_ledger: list[BillingLedgerEntry] = []

    async def write_settlement(self, context: PipelineContext) -> None:
        """Persist job, compute, external cost, and billing ledger records.

        Args:
            context: Pipeline context containing routing and result metadata.

        Returns:
            None.

        Cost/quality target:
            Keep settlement under 1ms in mocked mode and mirror the future
            PostgreSQL schema boundaries.
        """

        self.jobs.append(
            JobRecord(
                job_id=context.job_id,
                subscriber_id=context.request.subscriber_id,
                domain=context.classification.domain if context.classification else "chat",
                status="complete" if context.final_answer else "error",
                low_confidence=context.low_confidence,
                classify_tokens=context.classify_tokens,
                cache_hit=context.cache_result.hit if context.cache_result else False,
                cache_source=context.cache_result.source if context.cache_result else "miss",
                route_model=context.route_result.model_used if context.route_result else None,
                route_tokens=context.route_tokens,
                served_by=context.selected_response.served_by if context.selected_response else None,
                escalation_count=context.route_result.escalation_count if context.route_result else 0,
                prune_tokens_saved=context.prune_result.tokens_saved if context.prune_result else 0,
            )
        )
        for response in context.providers_touched:
            self.compute_units.append(
                ComputeUnitEntry(
                    job_id=context.job_id,
                    provider_id=response.provider_id,
                    model=response.model,
                    latency_ms=response.latency_ms,
                    tokens=response.prompt_tokens + response.completion_tokens,
                    proof_of_compute=response.proof_of_compute,
                    confidence=response.confidence,
                )
            )
        for external in context.external_costs:
            self.external_costs.append(external)
        self.billing_ledger.append(
            BillingLedgerEntry(
                job_id=context.job_id,
                subscriber_id=context.request.subscriber_id,
                amount_usd=context.cost_usd,
                providers_paid_usd=context.providers_paid,
            )
        )

    def snapshot(self) -> dict[str, list[Any]]:
        """Return all ledger tables for tests and diagnostics.

        Args:
            None.

        Returns:
            Dict keyed by logical table name.

        Cost/quality target:
            Provide transparent inspection without connecting to PostgreSQL.
        """

        return {
            "jobs": self.jobs,
            "compute_units": self.compute_units,
            "external_costs": self.external_costs,
            "billing_ledger": self.billing_ledger,
        }


ledger = InMemoryLedger()
