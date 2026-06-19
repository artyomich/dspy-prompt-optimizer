#!/usr/bin/env python3

"""
Agentic State Preservation System
Stack: Python, Redis, PostgreSQL, DSPy patterns
"""

import json
import hashlib
import logging
import math
from typing import Dict, List, Any, Optional

import redis
import psycopg2
from psycopg2.extras import Json
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# 1. SESSION STATE MANAGEMENT
# ============================================================================

class SessionState:
    """Stores and manages conversation session state."""

    VECTOR_DIM = 128

    def __init__(self, user_id: str, session_id: str):
        self.user_id = user_id
        self.session_id = session_id
        self.created_at = datetime.now()
        self.last_updated = datetime.now()
        self.messages: List[Dict[str, Any]] = []
        self.agent_states: Dict[str, Any] = {}
        self.context_vector: List[float] = []
        self.state_version = 0
        self.is_active = True

    def add_message(self, role: str, content: str,
                    metadata: Optional[Dict] = None):
        """Append a message to conversation history."""
        if not isinstance(content, str):
            raise ValueError(f"content must be str, got {type(content)}")
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        self.messages.append(message)
        self._update_vector()
        self.state_version += 1
        self.last_updated = datetime.now()

    def _update_vector(self):
        """Recompute context vector from recent messages."""
        if self.messages:
            context_text = " ".join(
                m["content"] for m in self.messages[-5:]
            )
            self.context_vector = self._embed_context(context_text)

    def _embed_context(self, context: str) -> List[float]:
        """
        Produce a deterministic pseudo-embedding.
        Replace with sentence-transformers in production:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer('all-MiniLM-L6-v2')
            return model.encode(context).tolist()
        """
        raw = [hash(str(context) + str(i)) % 1024 for i in range(self.VECTOR_DIM)]
        # L2-normalize
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]

    def get_summary(self) -> str:
        return (f"Session {self.session_id} "
                f"(User: {self.user_id}) - "
                f"{len(self.messages)} messages, "
                f"v{self.state_version}")

    # --- Redis persistence ---

    def save_to_redis(self, client: redis.Redis, ttl: int = 604800):
        """Save state to Redis with TTL (default 7 days)."""
        key = f"agent_session:{self.session_id}"
        data = self._serialize()
        try:
            client.setex(key, ttl, json.dumps(data))
            logger.debug("Saved session %s to Redis", self.session_id)
        except redis.RedisError as e:
            logger.error("Redis save failed: %s", e)
            raise

    def load_from_redis(self, client: redis.Redis,
                        session_id: str) -> Optional["SessionState"]:
        """Load and return a SessionState from Redis."""
        key = f"agent_session:{session_id}"
        try:
            raw = client.get(key)
        except redis.RedisError as e:
            logger.error("Redis load failed: %s", e)
            raise
        if not raw:
            return None
        return SessionState._deserialize(json.loads(raw))

    def delete_from_redis(self, client: redis.Redis):
        """Delete session from Redis."""
        key = f"agent_session:{self.session_id}"
        try:
            client.delete(key)
        except redis.RedisError as e:
            logger.error("Redis delete failed: %s", e)
            raise

    # --- Serialization helpers ---

    def _serialize(self) -> dict:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "messages": self.messages,
            "agent_states": self.agent_states,
            "context_vector": self.context_vector,
            "state_version": self.state_version,
            "is_active": self.is_active,
        }

    @classmethod
    def _deserialize(cls, data: dict) -> "SessionState":
        obj = cls(data["user_id"], data["session_id"])
        obj.created_at = datetime.fromisoformat(data["created_at"])
        obj.last_updated = datetime.fromisoformat(data["last_updated"])
        obj.messages = data["messages"]
        obj.agent_states = data["agent_states"]
        obj.context_vector = data["context_vector"]
        obj.state_version = data["state_version"]
        obj.is_active = data["is_active"]
        return obj


# ============================================================================
# 2. DATABASE STATE MANAGER
# ============================================================================

class DatabaseStateManager:
    """PostgreSQL-backed durable state storage."""

    def __init__(self, db_config: Dict[str, Any]):
        self.db_config = db_config
        self.conn: Optional[psycopg2.extensions.connection] = None

    def connect(self):
        self.conn = psycopg2.connect(**self.db_config)
        self.conn.autocommit = False

    def close(self):
        if self.conn and not self.conn.closed:
            self.conn.close()

    def create_tables(self):
        """Create tables if they don't exist. Run once at startup."""
        if not self.conn:
            self.connect()
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_sessions (
                session_id   VARCHAR(255) PRIMARY KEY,
                user_id      VARCHAR(255) NOT NULL,
                created_at   TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
                state_version INTEGER     DEFAULT 0,
                is_active    BOOLEAN      DEFAULT TRUE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_messages (
                id          SERIAL PRIMARY KEY,
                session_id  VARCHAR(255) REFERENCES agent_sessions(session_id),
                role        VARCHAR(50),
                content     TEXT,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata    JSONB
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_states (
                id           SERIAL PRIMARY KEY,
                agent_id     VARCHAR(255),
                session_id   VARCHAR(255) REFERENCES agent_sessions(session_id),
                state        JSONB,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_context (
                id             SERIAL PRIMARY KEY,
                session_id     VARCHAR(255) REFERENCES agent_sessions(session_id),
                embedding_vector FLOAT4[],
                context_text   TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Indexes for fast lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session
            ON agent_messages(session_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_states_session
            ON agent_states(session_id)
        """)
        # Unique index for agent_context upsert
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_context_session
            ON agent_context(session_id)
        """)
        self.conn.commit()
        cursor.close()

    def save_session(self, session: SessionState):
        """Upsert session + append message + agent states."""
        if not self.conn:
            self.connect()
        assert self.conn is not None
        cursor = self.conn.cursor()
        try:
            # Upsert session
            cursor.execute("""
                INSERT INTO agent_sessions
                    (session_id, user_id, last_updated, state_version, is_active)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    last_updated = EXCLUDED.last_updated,
                    state_version = EXCLUDED.state_version,
                    is_active = EXCLUDED.is_active
            """, (
                session.session_id, session.user_id,
                session.last_updated.isoformat(),
                session.state_version, session.is_active,
            ))

            # Append latest message
            if session.messages:
                last = session.messages[-1]
                cursor.execute("""
                    INSERT INTO agent_messages
                        (session_id, role, content, timestamp, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    session.session_id, last["role"],
                    last["content"], last["timestamp"],
                    Json(last.get("metadata", {}))
                ))

            # Upsert agent states
            for agent_id, state in session.agent_states.items():
                cursor.execute("""
                    INSERT INTO agent_states
                        (agent_id, session_id, state, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (agent_id, session_id) DO UPDATE SET
                        state = EXCLUDED.state,
                        updated_at = EXCLUDED.updated_at
                """, (agent_id, session.session_id,
                      Json(state), session.last_updated.isoformat()))

            # Upsert context vector
            if session.context_vector:
                cursor.execute("""
                    INSERT INTO agent_context
                        (session_id, embedding_vector, context_text)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (session_id) DO UPDATE SET
                        embedding_vector = EXCLUDED.embedding_vector,
                        context_text = EXCLUDED.context_text
                """, (session.session_id,
                      session.context_vector,
                      " ".join(m["content"] for m in session.messages[-5:])))

            self.conn.commit()
            logger.debug("Saved session %s to PostgreSQL", session.session_id)
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()

    def load_session(self, session_id: str) -> Optional[SessionState]:
        """Load full session from PostgreSQL."""
        if not self.conn:
            self.connect()
        assert self.conn is not None
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT session_id, user_id, created_at, last_updated,
                       state_version, is_active
                FROM agent_sessions WHERE session_id = %s
            """, (session_id,))
            row = cursor.fetchone()
            if not row:
                return None

            session = SessionState(row[1], row[0])
            session.created_at = row[2]
            session.last_updated = row[3]
            session.state_version = row[4]
            session.is_active = row[5]

            # Messages
            cursor.execute("""
                SELECT role, content, timestamp, metadata
                FROM agent_messages
                WHERE session_id = %s ORDER BY id ASC
            """, (session_id,))
            for r in cursor.fetchall():
                session.messages.append({
                    "role": r[0], "content": r[1],
                    "timestamp": r[2].isoformat(),
                    "metadata": r[3] or {}
                })

            # Agent states
            cursor.execute("""
                SELECT agent_id, state FROM agent_states
                WHERE session_id = %s
            """, (session_id,))
            for r in cursor.fetchall():
                session.agent_states[r[0]] = r[1] or {}

            # Recompute vector
            session._update_vector()
            return session
        finally:
            cursor.close()

    def search_by_context(self, query_vector: List[float],
                           limit: int = 10) -> List[SessionState]:
        """Cosine similarity search over stored context vectors."""
        if not self.conn:
            self.connect()
        assert self.conn is not None
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT session_id,
                    1 - (embedding_vector <=> %s::float4[]) AS similarity
                FROM agent_context
                WHERE embedding_vector IS NOT NULL
                ORDER BY similarity DESC
                LIMIT %s
            """, (query_vector, limit))
            results = []
            for row in cursor.fetchall():
                s = self.load_session(row[0])
                if s:
                    results.append(s)
            return results
        finally:
            cursor.close()


# ============================================================================
# 3. AGENT ORCHESTRATOR
# ============================================================================

class AgentOrchestrator:
    """Central agent manager with state persistence."""

    def __init__(self, redis_client: redis.Redis,
                 db_config: Dict[str, Any]):
        self.redis_client = redis_client
        self.db_manager = DatabaseStateManager(db_config)
        self.agents: Dict[str, Dict[str, Any]] = {
            "research": {"role": "research", "tasks": []},
            "coding":   {"role": "coding",   "tasks": []},
            "review":   {"role": "review",   "tasks": []},
            "qa":       {"role": "qa",       "tasks": []},
        }
        self.active_sessions: Dict[str, SessionState] = {}

    def create_session(self, user_id: str,
                       session_id: str) -> SessionState:
        """Create a new session (fails if already exists)."""
        # Ensure tables exist
        self.db_manager.create_tables()
        if session_id in self.active_sessions:
            raise ValueError(f"Session {session_id} already exists")
        session = SessionState(user_id, session_id)
        session.save_to_redis(self.redis_client)
        self.db_manager.save_session(session)
        self.active_sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """Retrieve session: try Redis first, then PostgreSQL."""
        # Check in-memory cache
        if session_id in self.active_sessions:
            return self.active_sessions[session_id]
        # Try Redis
        session = SessionState("", "").load_from_redis(
            self.redis_client, session_id
        )
        if session:
            self.active_sessions[session_id] = session
            return session
        # Fallback to PostgreSQL
        session = self.db_manager.load_session(session_id)
        if session:
            self.active_sessions[session_id] = session
            session.save_to_redis(self.redis_client)
        return session

    def add_agent(self, agent_id: str, config: Dict[str, Any]):
        self.agents[agent_id] = {
            "role": config.get("role", agent_id),
            "tasks": config.get("tasks", []),
        }

    def process_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Process a user request through the agent pipeline."""
        user_id = request.get("user_id", "anonymous")
        session_id = request.get("session_id", f"session_{user_id}")
        message = request.get("message", "")

        # Ensure tables exist
        self.db_manager.create_tables()

        session = self.get_session(session_id)
        if not session:
            session = self.create_session(user_id, session_id)

        session.add_message("user", message)

        response = {"agent_responses": [], "session_id": session_id}
        for agent_id, info in self.agents.items():
            response["agent_responses"].append({
                "agent_id": agent_id,
                "role": info["role"],
                "response": f"Agent {agent_id} processed: {message[:50]}..."
            })

        session.save_to_redis(self.redis_client)
        self.db_manager.save_session(session)
        return response

    def get_conversation_history(self, session_id: str) -> List[Dict]:
        session = self.get_session(session_id)
        return session.messages if session else []


# ============================================================================
# 4. DSPY PROMPT OPTIMIZER
# ============================================================================

class DSPyPromptOptimizer:
    """
    Stub for DSPy-based prompt optimization.
    Requires: pip install dspy-ai

    Usage:
        optimizer = DSPyPromptOptimizer(
            model="qwen2.5-4b-instruct",
            metric="accuracy"
        )
        best_prompt = optimizer.optimize(
            original_prompt,
            training_examples=[...]
        )
    """

    def __init__(self, model: str = "local/llama-server",
                 metric: str = "accuracy"):
        self.model_name = model
        self.metric = metric
        # TODO: integrate dspy.Teleprompter, dspy.Mipro

    def optimize_prompt(self, prompt: str,
                        training_data: Optional[List[dict]] = None) -> str:
        """
        Optimize a prompt using DSPy patterns.
        Placeholder — replace with actual DSPy pipeline:
            import dspy
            teleprompter = dspy.Mipro(predictor, metric, trainset)
            return teleprompter.compile()
        """
        logger.info("DSPy optimization requested (stub). "
                     "Prompt: %.100s...", prompt)
        return prompt  # no-op until DSPy pipeline is wired


# ============================================================================
# 5. DEMO / MAIN
# ============================================================================

def main():
    """Demo: run without external Redis/PostgreSQL (uses in-memory stubs)."""

    print("=" * 72)
    print("  AGENTIC STATE PRESERVATION — DEMO")
    print("=" * 72)

    # --- Example 1: Session creation ---
    print("\n[1] Create session & add messages")
    session = SessionState("user_abc123", "session_001")
    session.add_message("user", "Привет, мне нужен Python-скрипт для анализа CSV")
    session.add_message("assistant", "Конечно! Вот пример...")
    print(f"  ✅ {session.get_summary()}")
    print(f"  Vector dim: {len(session.context_vector)}")

    # --- Example 2: Agent states ---
    print("\n[2] Agent states")
    session.agent_states = {
        "research": {"status": "idle", "tasks": []},
        "coding":   {"status": "active", "tasks": ["analyze_code", "write_code"]},
        "review":   {"status": "idle", "tasks": []},
        "qa":       {"status": "idle", "tasks": []},
    }
    print(f"  Active agents: {[k for k,v in session.agent_states.items() if v['status']=='active']}")

    # --- Example 3: Serialization round-trip ---
    print("\n[3] Serialization round-trip")
    data = session._serialize()
    restored = SessionState._deserialize(data)
    assert restored.session_id == session.session_id
    assert len(restored.messages) == 2
    print(f"  ✅ Round-trip OK — {len(restored.messages)} messages preserved")

    # --- Example 4: Versioning ---
    print("\n[4] State versioning")
    print(f"  Version: {session.state_version}")
    session.add_message("user", "Добавь обработку ошибок")
    print(f"  After new message → version: {session.state_version}")

    # --- Example 5: Orchestrator ---
    print("\n[5] Orchestrator process_request (with Redis + PostgreSQL)")
    try:
        r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True, socket_timeout=5, socket_connect_timeout=5)
        r.ping()
        orchestrator = AgentOrchestrator(r, {
            "dbname": "agents", "user": "postgres",
            "password": "postgres", "host": "localhost",
            "port": 5432,
            "connect_timeout": 10
        })
        result = orchestrator.process_request({
            "user_id": "user_abc123",
            "session_id": "session_001",
            "message": "Напиши функцию парсинга JSON"
        })
        print(f"  ✅ Response keys: {list(result.keys())}")
        print(f"  ✅ Agent responses: {len(result['agent_responses'])}")
    except (redis.ConnectionError, redis.TimeoutError, TimeoutError,
             psycopg2.OperationalError) as e:
        print(f"  ⚠️  Service not available ({type(e).__name__}) — skipping live orchestrator test")

    # --- Example 6: DSPy optimizer stub ---
    print("\n[6] DSPy optimizer (stub)")
    opt = DSPyPromptOptimizer()
    new_prompt = opt.optimize_prompt("Answer the following question...")
    print(f"  ✅ Optimizer returned prompt (stub): {new_prompt[:50]}...")

    print("\n" + "=" * 72)
    print("  DEMO COMPLETE")
    print("=" * 72)


if __name__ == "__main__":
    main()
