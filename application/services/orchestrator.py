"""Agent orchestrator — application-level coordination of domain and infrastructure."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from domain.session.models import MessageRole, SessionState
from domain.session.repository import SessionRepository
from domain.agent.models import Agent, AgentRegistry, AgentType
from infrastructure.dspy.optimizer import DSPyPromptOptimizer

logger = logging.getLogger(__name__)


class RequestContext:
    """DTO for incoming user requests."""

    def __init__(
        self,
        user_id: str,
        session_id: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.user_id = user_id
        self.session_id = session_id
        self.message = message
        self.metadata = metadata or {}


class ProcessingResult:
    """DTO for processing results."""

    def __init__(
        self,
        session_id: str,
        agent_responses: List[Dict[str, Any]],
        optimized_prompt: Optional[str] = None,
    ):
        self.session_id = session_id
        self.agent_responses = agent_responses
        self.optimized_prompt = optimized_prompt

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_responses": self.agent_responses,
            "optimized_prompt": self.optimized_prompt,
        }


class AgentOrchestrator:
    """Central orchestrator managing session lifecycle and agent coordination.

    Coordinates:
    - Session creation and persistence
    - Agent task assignment
    - Prompt optimization via DSPy
    """

    DEFAULT_AGENTS = {
        "research": {"type": AgentType.RESEARCH, "description": "Research and gather information"},
        "coding": {"type": AgentType.CODING, "description": "Write and optimize code"},
        "review": {"type": AgentType.REVIEW, "description": "Review and validate output"},
        "qa": {"type": AgentType.QA, "description": "Quality assurance testing"},
    }

    def __init__(
        self,
        session_repository: SessionRepository,
        prompt_optimizer: Optional[DSPyPromptOptimizer] = None,
        default_agents: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        self._repository = session_repository
        self._prompt_optimizer = prompt_optimizer or DSPyPromptOptimizer()
        self._registry = AgentRegistry()
        self._active_sessions: Dict[str, SessionState] = {}

        # Register default agents
        for agent_id, config in (default_agents or self.DEFAULT_AGENTS).items():
            agent_type = config.get("type", AgentType.RESEARCH)
            description = config.get("description", "")
            self._registry.register(Agent(agent_id, agent_type, description))

    @property
    def agent_registry(self) -> AgentRegistry:
        return self._registry

    @property
    def prompt_optimizer(self) -> DSPyPromptOptimizer:
        return self._prompt_optimizer

    def create_session(self, user_id: str, session_id: str) -> SessionState:
        """Create a new session."""
        if session_id in self._active_sessions:
            raise ValueError(f"Session {session_id} already exists in memory")

        # Check persistence layer
        existing = self._repository.find_by_id(session_id)
        if existing and existing.is_active:
            raise ValueError(f"Session {session_id} already exists")

        session = SessionState(user_id, session_id)
        self._active_sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """Retrieve session: try memory → Redis → PostgreSQL."""
        # 1. In-memory cache
        if session_id in self._active_sessions:
            return self._active_sessions[session_id]

        # 2. Persistence layer (Redis → PostgreSQL via composite)
        session = self._repository.find_by_id(session_id)
        if session:
            self._active_sessions[session_id] = session
        return session

    def process_request(self, request: RequestContext) -> ProcessingResult:
        """Process a user request through the agent pipeline."""
        # Get or create session
        session = self.get_session(request.session_id)
        if not session:
            session = self.create_session(request.user_id, request.session_id)

        # Add user message
        session.add_message(MessageRole.USER, request.message, request.metadata)

        # Process through agents
        agent_responses: List[Dict[str, Any]] = []
        for agent in self._registry.list_all():
            response = self._process_with_agent(agent, request.message)
            agent_responses.append(response)

        # Persist session
        self._repository.save(session)
        self._active_sessions[request.session_id] = session

        return ProcessingResult(
            session_id=request.session_id,
            agent_responses=agent_responses,
        )

    def optimize_prompt(
        self,
        prompt: str,
        training_data: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Optimize a prompt using DSPy."""
        return self._prompt_optimizer.optimize_prompt(prompt, training_data)

    def evaluate_prompt(
        self,
        prompt: str,
        test_data: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        """Evaluate a prompt against test data."""
        return self._prompt_optimizer.evaluate_prompt(prompt, test_data)

    def get_conversation_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Get conversation history for a session."""
        session = self.get_session(session_id)
        if session:
            return session.get_conversation_history()
        return []

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        self._active_sessions.pop(session_id, None)
        return self._repository.delete(session_id)

    # --- Private helpers ---

    def _process_with_agent(
        self,
        agent: Agent,
        message: str,
    ) -> Dict[str, Any]:
        """Process a message with a specific agent."""
        agent.set_status("active")
        task_id = f"task_{agent.agent_id}_{len(agent.tasks) + 1}"
        agent.assign_task(task_id, message[:100])

        # Generate response based on agent type
        response = self._generate_agent_response(agent, message)

        agent.set_status("idle")
        return {
            "agent_id": agent.agent_id,
            "agent_type": agent.agent_type.value,
            "response": response,
        }

    def _generate_agent_response(self, agent: Agent, message: str) -> str:
        """Generate a response based on agent type."""
        agent_type = agent.agent_type.value
        preview = message[:80].replace("\n", " ")
        if not preview:
            preview = message[:80]

        responses = {
            "research": f"Research agent analyzed: '{preview}...'",
            "coding": f"Code agent generated solution for: '{preview}...'",
            "review": f"Review agent validated output for: '{preview}...'",
            "qa": f"QA agent tested scenario for: '{preview}...'",
        }
        return responses.get(agent_type, f"Agent {agent.agent_id} processed: '{preview}...'")