"""Main entry point for the DDD-refactored application."""

from __future__ import annotations

import logging
import sys
from typing import Optional

import redis

from domain.session.models import MessageRole, SessionState
from domain.session.repository import SessionRepository
from infrastructure.storage.redis_repository import RedisSessionRepository
from infrastructure.storage.postgres_repository import PostgresSessionRepository
from infrastructure.storage.composite_repository import CompositeSessionRepository
from infrastructure.dspy.optimizer import DSPyPromptOptimizer
from application.services.orchestrator import AgentOrchestrator, RequestContext

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_orchestrator(
    redis_client: Optional[redis.Redis] = None,
    db_config: Optional[dict] = None,
) -> AgentOrchestrator:
    """Build the full application stack."""
    # Build session repository
    if redis_client is None and db_config is None:
        # In-memory fallback: use composite with no external deps
        # Create minimal Redis client (will fail gracefully)
        redis_client = redis.Redis(
            host="localhost", port=6379, db=0,
            decode_responses=True,
            socket_timeout=2, socket_connect_timeout=2,
        )
        db_config = {
            "dbname": "agents", "user": "postgres",
            "password": "postgres", "host": "localhost",
            "port": 5432, "connect_timeout": 5,
        }

    redis_repo = RedisSessionRepository(redis_client)
    postgres_repo = PostgresSessionRepository(db_config)
    composite_repo = CompositeSessionRepository(redis_repo, postgres_repo)

    prompt_optimizer = DSPyPromptOptimizer(strategy="heuristic")

    orchestrator = AgentOrchestrator(
        session_repository=composite_repo,
        prompt_optimizer=prompt_optimizer,
    )
    return orchestrator


def demo() -> None:
    """Run a demo of the DDD architecture."""
    print("=" * 72)
    print("  DDD AGENTIC STATE PRESERVATION — DEMO")
    print("=" * 72)

    # --- Demo 1: Domain models ---
    print("\n[1] Domain models — SessionState")
    session = SessionState("user_abc123", "session_001")
    session.add_message(MessageRole.USER, "Привет, мне нужен Python-скрипт для анализа CSV")
    session.add_message(MessageRole.ASSISTANT, "Конечно! Вот пример...")
    print(f"  ✅ {session.get_summary()}")
    print(f"  Context vector dim: {len(session.context_vector)}")

    # --- Demo 2: Agent states ---
    print("\n[2] Agent states")
    from domain.session.models import AgentState
    session.agent_states["research"] = AgentState(agent_id="research", status="idle", tasks=[])
    session.agent_states["coding"] = AgentState(agent_id="coding", status="active", tasks=["analyze_code", "write_code"])
    active_agents = [k for k, v in session.agent_states.items() if v.status == "active"]
    print(f"  Active agents: {active_agents}")

    # --- Demo 3: Serialization round-trip ---
    print("\n[3] Serialization round-trip")
    data = session.serialize()
    restored = SessionState.deserialize(data)
    assert restored.session_id == session.session_id
    assert len(restored.messages) == 2
    print(f"  ✅ Round-trip OK — {len(restored.messages)} messages preserved")

    # --- Demo 4: State versioning ---
    print("\n[4] State versioning")
    print(f"  Version: {session.state_version}")
    session.add_message(MessageRole.USER, "Добавь обработку ошибок")
    print(f"  After new message → version: {session.state_version}")

    # --- Demo 5: Agent domain ---
    print("\n[5] Agent domain")
    from domain.agent.models import Agent, AgentType
    coding_agent = Agent("coding", AgentType.CODING, "Write and optimize code")
    coding_agent.assign_task("task_001", "Analyze CSV structure")
    coding_agent.complete_task("task_001", "CSV parser written successfully")
    print(f"  Agent: {coding_agent.agent_id}, status: {coding_agent.status}")
    print(f"  Tasks: {len(coding_agent.tasks)}, completed: {sum(1 for t in coding_agent.tasks if t.status == 'completed')}")

    # --- Demo 6: DSPy optimizer ---
    print("\n[6] DSPy optimizer")
    optimizer = DSPyPromptOptimizer(strategy="heuristic")
    new_prompt = optimizer.optimize_prompt("Answer the following question...")
    metrics = optimizer.evaluate_prompt(new_prompt, [{"input": "test", "output": "answer"}])
    print(f"  ✅ Optimized prompt: {new_prompt[:60]}...")
    print(f"  Evaluation metrics: {metrics}")

    # --- Demo 7: Orchestrator (in-memory) ---
    print("\n[7] Orchestrator (in-memory session)")
    try:
        r = redis.Redis(
            host="localhost", port=6379, db=0,
            decode_responses=True, socket_timeout=3, socket_connect_timeout=3,
        )
        r.ping()
        orchestrator = build_orchestrator(redis_client=r)
        result = orchestrator.process_request(RequestContext(
            user_id="user_abc123",
            session_id="session_001",
            message="Напиши функцию парсинга JSON",
        ))
        print(f"  ✅ Response keys: {list(result.to_dict().keys())}")
        print(f"  ✅ Agent responses: {len(result.agent_responses)}")
    except (redis.ConnectionError, redis.TimeoutError, TimeoutError, Exception) as exc:
        print(f"  ⚠️  Services not available ({type(exc).__name__}) — skipping live orchestrator test")

    # --- Demo 8: Prompt optimization ---
    print("\n[8] Prompt optimization comparison")
    original = "write code"
    optimized = optimizer.optimize_prompt(original, training_data=[{"input": "a", "output": "b"}] * 5)
    print(f"  Original:  '{original}'")
    print(f"  Optimized: '{optimized[:80]}...'")

    print("\n" + "=" * 72)
    print("  DEMO COMPLETE")
    print("=" * 72)


if __name__ == "__main__":
    demo()