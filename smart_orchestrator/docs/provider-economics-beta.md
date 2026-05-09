# Provider Economics Beta

## Rule

Providers earn **1 beta credit per 1,000 tokens served** on sovereign node jobs.

Credits accrue only when `served_by` is a sovereign node (`node:<node_id>`).
Groq-served jobs are platform-paid fallback traffic and do not credit any
provider.

## Accounting

- Node agents report `latency_ms`, `prompt_tokens`, `completion_tokens`, and
  `total_tokens` when completing jobs.
- The orchestrator settlement stage accrues credits for non-external node
  responses with token counts.
- Groq usage is logged separately in `groq_usage` for platform cost analysis.

## Beta caveat

Legacy payout endpoints still expose USD-shaped fields for dashboard
compatibility. During beta those values mirror credits and are not Stripe
payout commitments.
