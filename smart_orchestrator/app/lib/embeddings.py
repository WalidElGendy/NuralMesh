import hashlib
import random


async def embed_text(text: str) -> list[float]:
    """Create a mocked bge-large 1024-d embedding.

    Args:
        text: Input text to embed.

    Returns:
        Deterministic 1024-dimensional vector suitable for cache tests.

    Cost/quality target:
        Zero-cost local mock with stable similarity behavior until real BAAI/bge-large-en-v1.5 is wired.
    """
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(1024)]


async def embed_prompt(text: str) -> list[float]:
    """Create a mocked prompt embedding.

    Args:
        text: Prompt text to embed.

    Returns:
        1024-dimensional deterministic vector.

    Cost/quality target:
        Mirrors the bge-large semantic-cache interface at zero external cost.
    """
    return await embed_text(text)
