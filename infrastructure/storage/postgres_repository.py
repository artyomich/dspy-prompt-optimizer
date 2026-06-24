"""PostgreSQL-backed session repository implementation."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import Json

from domain.session.models import ContextVectorizer, SessionState
from domain.session.repository import SessionRepository

logger = logging.getLogger(__name__)


class PostgresSessionRepository(SessionRepository):
    """Stores session states in PostgreSQL with vector search support."""

    SCHEMA_SQL = [
        """
        CREATE TABLE IF NOT EXISTS agent_sessions (
            session_id   VARCHAR(255) PRIMARY KEY,
            user_id      VARCHAR(255) NOT NULL,
            created_at   TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
            state_version INTEGER     DEFAULT 0,
            is_active    BOOLEAN      DEFAULT TRUE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_messages (
            id          SERIAL PRIMARY KEY,
            session_id  VARCHAR(255) REFERENCES agent_sessions(session_id),
            role        VARCHAR(50),
            content     TEXT,
            timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metadata    JSONB
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_states (
            id           SERIAL PRIMARY KEY,
            agent_id     VARCHAR(255),
            session_id   VARCHAR(255) REFERENCES agent_sessions(session_id),
            state        JSONB,
            updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_context (
            id             SERIAL PRIMARY KEY,
            session_id     VARCHAR(255) REFERENCES agent_sessions(session_id) UNIQUE,
            embedding_vector FLOAT4[],
            context_text   TEXT,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        # Indexes
        """
        CREATE INDEX IF NOT EXISTS idx_messages_session
        ON agent_messages(session_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_states_session
        ON agent_states(session_id)
        """,
    ]

    def __init__(self, db_config: Dict[str, Any]):
        """
        Args:
            db_config: PostgreSQL connection parameters (dbname, user, password,
                       host, port, connect_timeout).
        """
        self._db_config = db_config
        self._conn = None

    # --- Connection management ---

    def _ensure_connection(self) -> None:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._db_config)
            self._conn.autocommit = False

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()

    def initialize_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        self._ensure_connection()
        cursor = self._conn.cursor()
        try:
            for sql in self.SCHEMA_SQL:
                cursor.execute(sql)
            self._conn.commit()
        finally:
            cursor.close()

    # --- Repository interface ---

    def save(self, session: SessionState) -> None:
        self._ensure_connection()
        cursor = self._conn.cursor()
        try:
            # Upsert session header
            cursor.execute(
                """
                INSERT INTO agent_sessions
                    (session_id, user_id, last_updated, state_version, is_active)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    last_updated = EXCLUDED.last_updated,
                    state_version = EXCLUDED.state_version,
                    is_active = EXCLUDED.is_active
                """,
                (
                    session.session_id,
                    session.user_id,
                    session.last_updated.isoformat(),
                    session.state_version,
                    session.is_active,
                ),
            )

            # Append latest message
            messages = session.messages
            if messages:
                last_msg = messages[-1]
                cursor.execute(
                    """
                    INSERT INTO agent_messages
                        (session_id, role, content, timestamp, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        session.session_id,
                        last_msg.role.value if hasattr(last_msg.role, "value") else str(last_msg.role),
                        last_msg.content,
                        last_msg.timestamp.isoformat() if isinstance(last_msg.timestamp, type(session.last_updated)) or hasattr(last_msg.timestamp, 'isoformat') else str(last_msg.timestamp),
                        Json(last_msg.metadata or {}),
                    ),
                )

            # Upsert agent states
            for agent_id, agent_state in session.agent_states.items():
                state_dict = agent_state.to_dict() if hasattr(agent_state, 'to_dict') else agent_state
                cursor.execute(
                    """
                    INSERT INTO agent_states
                        (agent_id, session_id, state, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (agent_id, session_id) DO UPDATE SET
                        state = EXCLUDED.state,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (agent_id, session.session_id, Json(state_dict), session.last_updated.isoformat()),
                )

            # Upsert context vector
            context_vector = session.context_vector
            if context_vector:
                context_text = " ".join(m.content for m in session.messages[-5:])
                cursor.execute(
                    """
                    INSERT INTO agent_context
                        (session_id, embedding_vector, context_text)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (session_id) DO UPDATE SET
                        embedding_vector = EXCLUDED.embedding_vector,
                        context_text = EXCLUDED.context_text
                    """,
                    (session.session_id, context_vector, context_text),
                )

            self._conn.commit()
            logger.debug("Saved session %s to PostgreSQL", session.session_id)
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cursor.close()

    def find_by_id(self, session_id: str) -> Optional[SessionState]:
        self._ensure_connection()
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                """
                SELECT session_id, user_id, created_at, last_updated,
                       state_version, is_active
                FROM agent_sessions WHERE session_id = %s
                """,
                (session_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            session = SessionState(row[1], row[0])
            session._created_at = row[2]
            session._last_updated = row[3]
            session._state_version = row[4]
            session._is_active = row[5]

            # Load messages
            cursor.execute(
                """
                SELECT role, content, timestamp, metadata
                FROM agent_messages
                WHERE session_id = %s ORDER BY id ASC
                """,
                (session_id,),
            )
            for r in cursor.fetchall():
                ts = r[2]
                if hasattr(ts, 'isoformat'):
                    ts = ts.isoformat()
                session._messages.append({
                    "role": r[0],
                    "content": r[1],
                    "timestamp": ts,
                    "metadata": r[3] or {},
                })

            # Load agent states
            cursor.execute(
                """
                SELECT agent_id, state FROM agent_states
                WHERE session_id = %s
                """,
                (session_id,),
            )
            for r in cursor.fetchall():
                session._agent_states[r[0]] = r[1] or {}

            # Recompute vector
            session._context_vector = ContextVectorizer.embed_context(session._messages)
            return session
        finally:
            cursor.close()

    def delete(self, session_id: str) -> bool:
        self._ensure_connection()
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "DELETE FROM agent_sessions WHERE session_id = %s",
                (session_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0
        finally:
            cursor.close()

    def search_by_context(
        self,
        query_vector: List[float],
        limit: int = 10,
    ) -> List[SessionState]:
        self._ensure_connection()
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                """
                SELECT session_id,
                       1 - (embedding_vector <=> %s::float4[]) AS similarity
                FROM agent_context
                WHERE embedding_vector IS NOT NULL
                ORDER BY similarity DESC
                LIMIT %s
                """,
                (query_vector, limit),
            )
            results: List[SessionState] = []
            for row in cursor.fetchall():
                session = self.find_by_id(row[0])
                if session:
                    results.append(session)
            return results
        finally:
            cursor.close()