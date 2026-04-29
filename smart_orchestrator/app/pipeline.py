from collections.abc import Awaitable, Callable

from app.models.schemas import ChatRequest, ChatResponse, PipelineContext, StageEvent
from app.stages.cache import semantic_cache_stage
from app.stages.classify import classify_prompt
from app.stages.compress import compress_prompt
from app.stages.prune import prune_history
from app.stages.route import route_request
from app.stages.settle import settle

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
        for stage_name, stage_func in (("prune", prune_history), ("compress", compress_prompt)):
            await _emit(emit, StageEvent(type="stage", stage=stage_name, message="started"))
            await stage_func(context)
            await _emit(emit, StageEvent(type="stage", stage=stage_name, message="done"))

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
    )
