from __future__ import annotations

from app.models.schemas import PipelineContext


TARGET_RATIOS = {
    "trivial": 3.0,
    "simple": 3.0,
    "medium": 2.0,
    "hard": 1.3,
}


async def compress_prompt(ctx: PipelineContext) -> PipelineContext:
    """Compress long user prompts while preserving system instructions.

    Args:
        ctx: Pipeline context after pruning.

    Returns:
        Context with compressed prompt text when applicable.

    Cost/quality target:
        Reduces downstream token cost for long prompts while skipping short prompts
        and never compressing the system prompt.
    """
    token_count = ctx.prompt_token_estimate
    if token_count < 200 or ctx.classification is None:
        ctx.add_event("compress.skip", reason="prompt_too_short")
        return ctx

    ratio = TARGET_RATIOS[ctx.classification.complexity]
    try:
        from llmlingua import PromptCompressor  # type: ignore

        compressor = PromptCompressor()
        compressed = compressor.compress_prompt(ctx.prompt, rate=1 / ratio)
        ctx.compressed_prompt = compressed.get("compressed_prompt", ctx.prompt)
        engine = "llmlingua"
    except Exception:
        words = ctx.prompt.split()
        keep = max(80, int(len(words) / ratio))
        ctx.compressed_prompt = " ".join(words[:keep])
        engine = "mock-llmlingua"

    ctx.add_event("compress.complete", ratio=ratio, engine=engine)
    return ctx


run = compress_prompt
compress_context = compress_prompt
