from __future__ import annotations

import hashlib
import hmac


async def sign_proof(provider_id: str, model: str, prompt_digest: str, output_digest: str) -> str:
    """Create a deterministic mock Proof-of-Compute signature.

    Args:
        provider_id: Provider node identifier.
        model: Model executed on the provider.
        prompt_digest: SHA digest of the prompt, not the prompt body.
        output_digest: SHA digest of the generated output.

    Returns:
        Hex signature for mock verification.

    Cost/quality target:
        Free local operation; deterministic stand-in for cryptographic provider attestations.
    """
    payload = f"{provider_id}:{model}:{prompt_digest}:{output_digest}".encode()
    return hmac.new(b"neuralmesh-proof-dev-key", payload, hashlib.sha256).hexdigest()


async def digest_text(text: str) -> str:
    """Hash text for safe logging and proof payloads.

    Args:
        text: Source text.

    Returns:
        SHA-256 hex digest.

    Cost/quality target:
        Free local utility; avoids logging raw prompt bodies.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
