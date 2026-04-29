from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


Domain = Literal["code", "creative", "factual", "reasoning", "chat", "math"]
Complexity = Literal["trivial", "simple", "medium", "hard"]
Sensitivity = Literal["none", "pii", "confidential"]


class ChatMessage(BaseModel):
    """Single chat turn.

    Args:
        role: Message role.
        content: Message body.

    Returns:
        Structured chat turn for pipeline processing.

    Cost/quality target:
        Preserve only necessary chat data and avoid logging prompt bodies.
    """

    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    """Incoming /chat payload.

    Args:
        subscriber_id: Mock subscriber identifier.
        messages: Conversation turns.
        system: Optional system prompt, never compressed.
        stream: Whether SSE streaming is requested.

    Returns:
        Validated request for the orchestrator.

    Cost/quality target:
        Maintain API compatibility with streaming-first product behavior.
    """

    subscriber_id: str
    messages: list[ChatMessage]
    system: str | None = None
    stream: bool = True


class ChatResponse(BaseModel):
    """Non-stream response shape for internal tests.

    Args:
        job_id: Completed job identifier.
        answer: Final model answer.
        cost_usd: Total cost.
        providers_paid: Provider payout total.

    Returns:
        Final response summary.

    Cost/quality target:
        Expose concise deterministic results for tests.
    """

    job_id: str
    answer: str
    cost_usd: float
    providers_paid: float
    low_confidence: bool = False


class PromptClassification(BaseModel):
    """Stage 1 prompt classification.

    Args:
        domain: Prompt domain.
        complexity: Difficulty bucket.
        needs_freshness: Whether live/recent data is required.
        sensitivity: Data sensitivity.
        expected_output_tokens: Output budget estimate.

    Returns:
        Routing metadata for downstream stages.

    Cost/quality target:
        Cheap local classification to avoid unnecessary frontier calls.
    """

    domain: Domain
    complexity: Complexity
    needs_freshness: bool
    sensitivity: Sensitivity
    expected_output_tokens: int


class CachedAnswer(BaseModel):
    """Semantic cache answer.

    Args:
        cache_key: Stable cache identifier.
        prompt_hash: Hash of source prompt.
        answer: Cached final answer.
        score: Similarity score.
        domain: Cache collection domain.
        created_at: Creation timestamp.

    Returns:
        Cache hit payload.

    Cost/quality target:
        Reuse high-confidence answers only when safe.
    """

    prompt: str
    answer: str
    domain: Domain
    embedding: list[float] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float = 1.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MeshResponse(BaseModel):
    """Response from mesh or frontier provider.

    Args:
        provider_id: Provider identifier.
        model: Model name.
        content: Generated response.
        confidence: Self-reported confidence.
        self_critique: Model critique summary.
        latency_ms: Simulated or real latency.
        proof_of_compute: Signature payload.
        cost_usd: External or internal cost estimate.
        provider_paid_usd: Provider payout estimate.
        external: Whether provider is external API.

    Returns:
        Normalized model output.

    Cost/quality target:
        Compare cheap mesh calls against frontier escalation uniformly.
    """

    provider_id: str
    model: str
    content: str | None = None
    text: str | None = None
    confidence: float
    self_critique: str
    latency_ms: int
    proof_of_compute: str
    cost_usd: float = 0.0
    provider_paid_usd: float = 0.0
    external: bool = False

    @property
    def output_text(self) -> str:
        """Return response text from either accepted field.

        Args:
            None.

        Returns:
            Generated content.

        Cost/quality target:
            Compatibility accessor for stage code while keeping one canonical payload.
        """

        return self.content or self.text or ""


class DispatchResult(MeshResponse):
    """Mock dispatch result returned by provider node-client stubs."""

    compute_units: float = 0.0
    dispatch_id: str = ""
    purpose: str = "inference"


ModelCallResult = MeshResponse


class RouteAttempt(BaseModel):
    """Single route attempt metadata.

    Args:
        model: Model attempted.
        provider_id: Provider identifier.
        confidence: Provider confidence.
        verifier_passed: Whether verifier accepted the attempt.

    Returns:
        Structured audit row for routing.

    Cost/quality target:
        Records escalation decisions without prompt body logging.
    """

    model: str
    provider_id: str
    confidence: float
    verifier_passed: bool = False


class VerifierVerdict(BaseModel):
    """Hallucination verifier result.

    Args:
        grounded: Whether answer appears grounded.
        hallucination_risk: Risk score from 0 to 1.
        factual_claims: Extracted factual claims.
        pass_: Whether answer should pass.

    Returns:
        Verification verdict for route escalation.

    Cost/quality target:
        Catch weak outputs before expensive users see them.
    """

    grounded: bool
    hallucination_risk: float
    factual_claims: list[str]
    pass_: bool = Field(alias="pass")

    model_config = {"populate_by_name": True}


class StageEvent(BaseModel):
    """SSE stage event.

    Args:
        stage: Stage name.
        message: Human-readable message.
        data: Optional structured metadata.

    Returns:
        Event payload for streaming clients.

    Cost/quality target:
        Provide observability without leaking prompt bodies.
    """

    stage: str
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    status: str | None = None
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineEvent(BaseModel):
    """SSE event emitted by the pipeline.

    Args:
        event: SSE event name.
        data: JSON-serializable event payload.

    Returns:
        Event object for /chat streaming.

    Cost/quality target:
        Keeps streaming transport typed and prompt-safe.
    """

    event: Literal["stage", "token", "done"]
    data: dict[str, Any] = Field(default_factory=dict)


class PipelineContext(BaseModel):
    """Mutable state passed through every pipeline stage.

    Args:
        request: Original chat request.

    Returns:
        Context object containing stage outputs and accounting state.

    Cost/quality target:
        Keep orchestration explicit and traceable across async stages.
    """

    subscriber_id: str
    messages: list[ChatMessage]
    system: str | None = None
    job_id: str = Field(default_factory=lambda: f"job_{uuid4().hex[:16]}")
    working_messages: list[ChatMessage] = Field(default_factory=list)
    classification: PromptClassification | None = None
    cached_answer: CachedAnswer | None = None
    compressed_prompt: str | None = None
    selected_response: MeshResponse | None = None
    provider_touches: list[MeshResponse] = Field(default_factory=list)
    providers_touched: list[MeshResponse] = Field(default_factory=list)
    route_attempts: list[RouteAttempt] = Field(default_factory=list)
    external_costs: list["ExternalCostEntry"] = Field(default_factory=list)
    verifier_verdict: VerifierVerdict | None = None
    low_confidence: bool = False
    cache_hit: CachedAnswer | None = None
    cache_checked: bool = False
    cache_allowed: bool = True
    compression_ratio: float = 1.0
    escalations: int = 0
    cost_usd: float = 0.0
    providers_paid: float = 0.0
    stage_events: list[Any] = Field(default_factory=list)
    events: list[Any] = Field(default_factory=list)
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    final_answer: str | None = None

    @classmethod
    def from_request(cls, request: ChatRequest) -> "PipelineContext":
        """Build context from a /chat request.

        Args:
            request: Incoming chat request.

        Returns:
            Pipeline context initialized with request values.

        Cost/quality target:
            Keeps endpoint validation separate from stage mutation.
        """

        return cls(
            subscriber_id=request.subscriber_id,
            messages=request.messages,
            system=request.system,
            working_messages=list(request.messages),
        )

    @property
    def latest_user_prompt(self) -> str:
        """Return latest user prompt.

        Args:
            None.

        Returns:
            Last user message content or empty string.

        Cost/quality target:
            Single prompt accessor avoids accidental full-history logging.
        """

        for message in reversed(self.working_messages or self.messages):
            if message.role == "user":
                return message.content
        return ""

    @property
    def prompt_text(self) -> str:
        """Return prompt text used by stages.

        Args:
            None.

        Returns:
            Latest user prompt.

        Cost/quality target:
            Keeps Sprint 1 routing simple and deterministic.
        """

        return self.latest_user_prompt

    @property
    def prompt(self) -> str:
        """Return active prompt, preferring compressed content.

        Args:
            None.

        Returns:
            Compressed prompt or latest user prompt.

        Cost/quality target:
            Provides one prompt value to model-calling stages.
        """

        return self.compressed_prompt or self.latest_user_prompt

    @property
    def prompt_token_estimate(self) -> int:
        """Estimate prompt tokens using whitespace.

        Args:
            None.

        Returns:
            Rough token count for pruning and compression decisions.

        Cost/quality target:
            Zero-cost approximation adequate for Sprint 1 mocked routing.
        """

        return max(1, len(self.latest_user_prompt.split()))

    @property
    def request(self) -> ChatRequest:
        """Reconstruct a request view for compatibility with ledger code.

        Args:
            None.

        Returns:
            ChatRequest assembled from context fields.

        Cost/quality target:
            Keeps settlement table writing simple without duplicating state.
        """

        return ChatRequest(
            subscriber_id=self.subscriber_id,
            messages=self.messages,
            system=self.system,
            stream=True,
        )

    def emit(self, stage: str, message: str, data: dict[str, Any] | None = None) -> StageEvent:
        """Record a stage event.

        Args:
            stage: Stage name.
            message: Safe event message.
            data: Optional metadata without prompt body.

        Returns:
            StageEvent appended to the context.

        Cost/quality target:
            Enable transparent streaming telemetry at negligible cost.
        """

        event = StageEvent(stage=stage, message=message, data=data or {})
        self.events.append(event)
        return event

    def add_event(self, stage: str, **metadata: Any) -> StageEvent:
        """Append a structured stage event.

        Args:
            stage: Stage name or event key.
            metadata: Additional prompt-safe metadata.

        Returns:
            Stored StageEvent.

        Cost/quality target:
            Lightweight observability for tests and SSE without prompt bodies.
        """

        event = StageEvent(stage=stage, message=stage, metadata=metadata)
        self.stage_events.append(event)
        return event

    @property
    def answer(self) -> str:
        """Return best available answer.

        Args:
            None.

        Returns:
            Cached or final generated answer.

        Cost/quality target:
            Provide one output accessor for cache and non-cache paths.
        """

        if self.final_answer:
            return self.final_answer
        if self.cached_answer:
            return self.cached_answer.answer
        if self.selected_response:
            return self.selected_response.content
        return ""


Classification = PromptClassification
ProviderResponse = MeshResponse
Message = ChatMessage


class JobRecord(BaseModel):
    """Mock jobs table row."""

    job_id: str
    subscriber_id: str
    domain: Domain
    status: str
    low_confidence: bool


class ComputeUnitEntry(BaseModel):
    """Mock compute_units table row."""

    job_id: str
    provider_id: str
    model: str
    latency_ms: int
    proof_of_compute: str
    confidence: float


class ExternalCostEntry(BaseModel):
    """Mock external_costs table row."""

    job_id: str
    provider_id: str
    model: str
    cost_usd: float


class BillingLedgerEntry(BaseModel):
    """Mock billing_ledger table row."""

    job_id: str
    subscriber_id: str
    amount_usd: float
    providers_paid_usd: float
