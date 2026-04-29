from collections.abc import Awaitable, Callable

from app.models.schemas import ChatRequest, ChatResponse, PipelineContext, StageEvent
from app.stages.cache import semantic_cache_stage
from app.stages.classify import classify_prompt
from app.stages.compress import compress_prompt
from app.stages.prune import prune_history
from app.stages.route import route_request
from app.stages.settle import settle
from app.stages.verify import verify_response

Emit = Callable[[StageEvent], Awaitable[None]]


async def _emit(emit: Emit | None, event: StageEvent) -> None:
    if emit:
        await emit(event)


async def run_pipeline(request: ChatRequest, emit: Emit | None = None) -> ChatResponse:
    """Run all seven orchestrator stages and return a final response.

    Args:
        request: Validated chat request.
        emit: Optional async callback for stage events.
    Returns:
        Chat response with job, answer, cost, and confidence metadata.
    Cost/quality target:
        Prefer cache and cheap mesh providers before escalating to frontier APIs.
    """
    context = PipelineContext.from_request(request)

    await _emit(emit, StageEvent(type="stage", stage="classify", message="started"))
    await classify_prompt(context)
    await _emit(
        emit,
        StageEvent(
            type="stage",
            stage="classify",
            message="done",
            data={"classification": context.classification.model_dump() if context.classification else {}},
        ),
    )

    await _emit(emit, StageEvent(type="stage", stage="cache", message="started"))
    await semantic_cache_stage(context)
    await _emit(
        emit,
        StageEvent(
            type="stage",
            stage="cache",
            message="hit" if context.cache_hit else "miss",
        ),
    )

    if not context.cache_hit:
        await _emit(emit, StageEvent(type="stage", stage="prune", message="started"))
        await prune_history(context)
        await _emit(
            emit,
            StageEvent(
                type="stage",
                stage="prune",
                message="done",
                data={"tokens_saved": context.prune_tokens_saved},
            ),
        )

        await _emit(emit, StageEvent(type="stage", stage="compress", message="started"))
        await compress_prompt(context)
        await _emit(emit, StageEvent(type="stage", stage="compress", message="done"))

        await _emit(emit, StageEvent(type="stage", stage="route", message="started"))
        await route_request(context)
        await _emit(
            emit,
            StageEvent(
                type="stage",
                stage="route",
                message="done",
                data={
                    "model": context.selected_response.model if context.selected_response else None,
                    "low_confidence": context.low_confidence,
                },
            ),
        )

        await _emit(emit, StageEvent(type="stage", stage="verify", message="started"))
        await verify_response(context)
        await _emit(emit, StageEvent(type="stage", stage="verify", message="done"))
    else:
        context.final_answer = context.cache_hit.answer

    await _emit(emit, StageEvent(type="stage", stage="settle", message="started"))
    await settle(context)
    await _emit(emit, StageEvent(type="stage", stage="settle", message="done"))

    return ChatResponse(
        job_id=context.job_id,
        answer=context.answer,
        cost_usd=round(context.cost_usd, 6),
        providers_paid=round(context.providers_paid, 6),
        low_confidence=context.low_confidence,
        cache_source=context.cache_result.source if context.cache_result else "miss",
        classify_tokens=context.classify_tokens,
        route_model=context.route_result.model_used if context.route_result else None,
        route_tokens=context.route_tokens,
        escalation_count=context.escalations,
        prune_tokens_saved=context.prune_tokens_saved,
        sensitive_override=context.route_result.sensitive_override if context.route_result else False,
    )
