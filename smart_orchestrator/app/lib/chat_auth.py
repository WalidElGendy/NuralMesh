from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class ChatUser:
    user_id: str
    email: str
    tier: str = "beta"


def _is_production() -> bool:
    return os.getenv("NM_ENV", os.getenv("NM_ENVIRONMENT", "")).lower() in {"prod", "production"}


async def BetaChatUserDep(
    authorization: str | None = Header(default=None),
    x_beta_user_id: str | None = Header(default=None),
) -> ChatUser:
    """Resolve the temporary Sprint C chat user.

    TODO(Sprint-E): Replace this with Supabase session/JWT validation from
    Authorization: Bearer <session token>.
    """

    if x_beta_user_id:
        if _is_production():
            raise HTTPException(status_code=403, detail="Temporary beta auth is disabled")
        try:
            user_id = str(UUID(x_beta_user_id))
        except ValueError as error:
            raise HTTPException(status_code=401, detail="Invalid beta user id") from error
        return ChatUser(user_id=user_id, email="beta.user@neuralmesh.test")

    if authorization and authorization.startswith("Bearer "):
        # TODO(Sprint-E): Validate the bearer session token and load the real user.
        raise HTTPException(status_code=501, detail="Session auth is not available until Sprint E")

    raise HTTPException(status_code=401, detail="Missing Authorization bearer token")
