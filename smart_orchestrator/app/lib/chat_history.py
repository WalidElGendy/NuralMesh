from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

import asyncpg

from app.config import get_settings


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def generate_title(message: str) -> str:
    title = " ".join(message.strip().split())
    if not title:
        return "New chat"
    return title[:57] + "..." if len(title) > 60 else title


class ChatHistoryStore(Protocol):
    async def create_conversation(self, user_id: str, title: str) -> dict[str, Any]: ...
    async def list_conversations(self, user_id: str) -> list[dict[str, Any]]: ...
    async def get_conversation(self, user_id: str, conversation_id: str) -> dict[str, Any] | None: ...
    async def rename_conversation(
        self, user_id: str, conversation_id: str, title: str
    ) -> dict[str, Any] | None: ...
    async def soft_delete_conversation(self, user_id: str, conversation_id: str) -> bool: ...
    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        served_by: str | None = None,
        tokens: int = 0,
        latency_ms: int = 0,
    ) -> dict[str, Any]: ...
    async def list_messages(self, user_id: str, conversation_id: str) -> list[dict[str, Any]]: ...


def _record_to_dict(record: Any) -> dict[str, Any]:
    data = dict(record)
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            data[key] = value.isoformat()
        else:
            data[key] = str(value) if key.endswith("_id") or key == "id" else value
    return data


class PostgresChatHistoryStore:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or get_settings().postgres_dsn
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        return self._pool

    async def create_conversation(self, user_id: str, title: str) -> dict[str, Any]:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO conversations (user_id, title)
            VALUES ($1::uuid, $2)
            RETURNING id, user_id, title, created_at, updated_at, deleted_at
            """,
            user_id,
            title,
        )
        return _record_to_dict(row)

    async def list_conversations(self, user_id: str) -> list[dict[str, Any]]:
        pool = await self._get_pool()
        rows = await pool.fetch(
            """
            SELECT id, user_id, title, created_at, updated_at, deleted_at
            FROM conversations
            WHERE user_id = $1::uuid AND deleted_at IS NULL
            ORDER BY updated_at DESC
            """,
            user_id,
        )
        return [_record_to_dict(row) for row in rows]

    async def get_conversation(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            SELECT id, user_id, title, created_at, updated_at, deleted_at
            FROM conversations
            WHERE id = $1::uuid AND user_id = $2::uuid AND deleted_at IS NULL
            """,
            conversation_id,
            user_id,
        )
        return _record_to_dict(row) if row else None

    async def rename_conversation(
        self, user_id: str, conversation_id: str, title: str
    ) -> dict[str, Any] | None:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            UPDATE conversations
            SET title = $3, updated_at = NOW()
            WHERE id = $1::uuid AND user_id = $2::uuid AND deleted_at IS NULL
            RETURNING id, user_id, title, created_at, updated_at, deleted_at
            """,
            conversation_id,
            user_id,
            title,
        )
        return _record_to_dict(row) if row else None

    async def soft_delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        pool = await self._get_pool()
        result = await pool.execute(
            """
            UPDATE conversations
            SET deleted_at = NOW(), updated_at = NOW()
            WHERE id = $1::uuid AND user_id = $2::uuid AND deleted_at IS NULL
            """,
            conversation_id,
            user_id,
        )
        return result.endswith("1")

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        served_by: str | None = None,
        tokens: int = 0,
        latency_ms: int = 0,
    ) -> dict[str, Any]:
        pool = await self._get_pool()
        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO messages (conversation_id, role, content, served_by, tokens, latency_ms)
                VALUES ($1::uuid, $2, $3, $4, $5, $6)
                RETURNING id, conversation_id, role, content, served_by, tokens, latency_ms, created_at
                """,
                conversation_id,
                role,
                content,
                served_by,
                tokens,
                latency_ms,
            )
            await conn.execute(
                "UPDATE conversations SET updated_at = NOW() WHERE id = $1::uuid",
                conversation_id,
            )
        return _record_to_dict(row)

    async def list_messages(self, user_id: str, conversation_id: str) -> list[dict[str, Any]]:
        pool = await self._get_pool()
        rows = await pool.fetch(
            """
            SELECT m.id, m.conversation_id, m.role, m.content, m.served_by,
                   m.tokens, m.latency_ms, m.created_at
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.id = $1::uuid AND c.user_id = $2::uuid AND c.deleted_at IS NULL
            ORDER BY m.created_at ASC
            """,
            conversation_id,
            user_id,
        )
        return [_record_to_dict(row) for row in rows]


class MemoryChatHistoryStore:
    def __init__(self) -> None:
        self.conversations: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, list[dict[str, Any]]] = defaultdict(list)

    async def create_conversation(self, user_id: str, title: str) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        conversation = {
            "id": str(uuid4()),
            "user_id": user_id,
            "title": title,
            "created_at": timestamp,
            "updated_at": timestamp,
            "deleted_at": None,
        }
        self.conversations[conversation["id"]] = conversation
        return dict(conversation)

    async def list_conversations(self, user_id: str) -> list[dict[str, Any]]:
        rows = [
            dict(conversation)
            for conversation in self.conversations.values()
            if conversation["user_id"] == user_id and conversation["deleted_at"] is None
        ]
        return sorted(rows, key=lambda row: row["updated_at"], reverse=True)

    async def get_conversation(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        conversation = self.conversations.get(conversation_id)
        if not conversation or conversation["user_id"] != user_id or conversation["deleted_at"]:
            return None
        return dict(conversation)

    async def rename_conversation(
        self, user_id: str, conversation_id: str, title: str
    ) -> dict[str, Any] | None:
        conversation = await self.get_conversation(user_id, conversation_id)
        if conversation is None:
            return None
        self.conversations[conversation_id]["title"] = title
        self.conversations[conversation_id]["updated_at"] = now_utc().isoformat()
        return dict(self.conversations[conversation_id])

    async def soft_delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        conversation = await self.get_conversation(user_id, conversation_id)
        if conversation is None:
            return False
        timestamp = now_utc().isoformat()
        self.conversations[conversation_id]["deleted_at"] = timestamp
        self.conversations[conversation_id]["updated_at"] = timestamp
        return True

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        served_by: str | None = None,
        tokens: int = 0,
        latency_ms: int = 0,
    ) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        message = {
            "id": str(uuid4()),
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "served_by": served_by,
            "tokens": tokens,
            "latency_ms": latency_ms,
            "created_at": timestamp,
        }
        self.messages[conversation_id].append(message)
        if conversation_id in self.conversations:
            self.conversations[conversation_id]["updated_at"] = timestamp
        return dict(message)

    async def list_messages(self, user_id: str, conversation_id: str) -> list[dict[str, Any]]:
        if await self.get_conversation(user_id, conversation_id) is None:
            return []
        return [dict(message) for message in self.messages[conversation_id]]


_postgres_store: PostgresChatHistoryStore | None = None


def get_chat_history_store() -> ChatHistoryStore:
    global _postgres_store
    if _postgres_store is None:
        _postgres_store = PostgresChatHistoryStore()
    return _postgres_store
