"""Composite session repository combining Redis cache and PostgreSQL persistence."""

from __future__ import annotations

import logging
from typing import List, Optional

from domain.session.models import SessionState
from domain.session.repository import SessionRepository

from infrastructure.storage.redis_repository import RedisSessionRepository
from infrastructure.storage.postgres_repository import PostgresSessionRepository

logger = logging.getLogger(__name__)


class CompositeSessionRepository(SessionRepository):
    """Reads from Redis first (fast cache), falls back to PostgreSQL.

    Write-through strategy: every save updates both Redis and PostgreSQL.
    """

    def __init__(
        self,
        redis_repo: RedisSessionRepository,
        postgres_repo: PostgresSessionRepository,
    ) -> None:
        self._redis = redis_repo
        self._postgres = postgres_repo

    # --- Delegate reads (Redis → PostgreSQL fallback) ---

    def save(self, session: SessionState) -> None:
        """Write-through to both Redis and PostgreSQL."""
        try:
            self._redis.save(session)
        except Exception:
            logger.warning("Redis save failed, continuing with PostgreSQL only")
        self._postgres.save(session)

    def find_by_id(self, session_id: str) -> Optional[SessionState]:
        """Try Redis first, then PostgreSQL."""
        # 1. Check Redis cache
        try:
            session = self._redis.find_by_id(session_id)
            if session:
                return session
        except Exception:
            logger.warning("Redis read failed, falling back to PostgreSQL")

        # 2. Fallback to PostgreSQL
        session = self._postgres.find_by_id(session_id)
        if session:
            # Warm the cache
            try:
                self._redis.save(session)
            except Exception:
                logger.warning("Redis cache warm failed")
        return session

    def delete(self, session_id: str) -> bool:
        """Delete from both Redis and PostgreSQL."""
        try:
            self._redis.delete(session_id)
        except Exception:
            logger.warning("Redis delete failed")
        return self._postgres.delete(session_id)

    def search_by_context(
        self,
        query_vector: List[float],
        limit: int = 10,
    ) -> List[SessionState]:
        """Search via PostgreSQL (vector similarity)."""
        return self._postgres.search_by_context(query_vector, limit)