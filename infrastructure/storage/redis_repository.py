"""Redis-backed session repository implementation."""

from __future__ import annotations

import json
import logging
from typing import List, Optional

import redis

from domain.session.models import SessionState
from domain.session.repository import SessionRepository

logger = logging.getLogger(__name__)


class RedisSessionRepository(SessionRepository):
    """Stores session states in Redis with TTL support."""

    def __init__(self, client: redis.Redis, default_ttl: int = 604800):
        """
        Args:
            client: Connected redis.Redis instance.
            default_ttl: TTL in seconds (default 7 days).
        """
        self._client = client
        self._default_ttl = default_ttl

    def _make_key(self, session_id: str) -> str:
        return f"agent_session:{session_id}"

    def save(self, session: SessionState) -> None:
        key = self._make_key(session.session_id)
        data = session.serialize()
        try:
            self._client.setex(key, self._default_ttl, json.dumps(data))
            logger.debug("Saved session %s to Redis", session.session_id)
        except redis.RedisError as exc:
            logger.error("Redis save failed: %s", exc)
            raise

    def find_by_id(self, session_id: str) -> Optional[SessionState]:
        key = self._make_key(session_id)
        try:
            raw = self._client.get(key)
        except redis.RedisError as exc:
            logger.error("Redis get failed: %s", exc)
            raise
        if raw is None:
            return None
        return SessionState.deserialize(json.loads(raw))

    def delete(self, session_id: str) -> bool:
        key = self._make_key(session_id)
        try:
            result = self._client.delete(key)
            return bool(result)
        except redis.RedisError as exc:
            logger.error("Redis delete failed: %s", exc)
            raise

    def search_by_context(
        self,
        query_vector: List[float],
        limit: int = 10,
    ) -> List[SessionState]:
        """Redis does not support vector search natively — returns empty list."""
        logger.warning("Vector search not supported on Redis repository")
        return []