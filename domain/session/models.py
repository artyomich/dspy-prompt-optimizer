"""Domain models for session management."""

from __future__ import annotations

import math
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class MessageRole(str, Enum):
    """Role of a message sender."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class Message:
    """Represents a single message in a conversation."""

    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize message to dictionary."""
        return {
            "role": self.role.value if isinstance(self.role, MessageRole) else self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata or {},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Deserialize message from dictionary."""
        role_value = data.get("role", "user")
        role = MessageRole(role_value) if isinstance(role_value, str) else role_value
        timestamp_str = data.get("timestamp", datetime.now().isoformat())
        timestamp = datetime.fromisoformat(timestamp_str) if isinstance(timestamp_str, str) else timestamp_str
        return cls(
            role=role,
            content=data.get("content", ""),
            timestamp=timestamp,
            metadata=data.get("metadata") or {},
        )
class ContextVectorizer:
    """Utility for computing context embeddings."""

    VECTOR_DIM = 128

    @staticmethod
    def embed_context(messages: List[Message], recent_n: int = 5) -> List[float]:
        """Produce a deterministic pseudo-embedding from recent messages."""
        context_text = " ".join(
            m.content for m in messages[-recent_n:]
        )
        raw = [hash(str(context_text) + str(i)) % 1024 for i in range(ContextVectorizer.VECTOR_DIM)]
        # L2-normalize
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]


@dataclass
class AgentState:
    """Represents the state of a single agent."""

    agent_id: str
    status: str = "idle"
    tasks: List[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "tasks": self.tasks,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentState":
        updated_at_str = data.get("updated_at", datetime.now().isoformat())
        updated_at = datetime.fromisoformat(updated_at_str) if isinstance(updated_at_str, str) else updated_at_str
        return cls(
            agent_id=data.get("agent_id", ""),
            status=data.get("status", "idle"),
            tasks=data.get("tasks", []),
            updated_at=updated_at,
        )


class SessionState:
    """Core domain model representing a user session with conversation history."""

    def __init__(self, user_id: str, session_id: str):
        if not user_id or not isinstance(user_id, str):
            raise ValueError("user_id must be a non-empty string")
        if not session_id or not isinstance(session_id, str):
            raise ValueError("session_id must be a non-empty string")

        self._user_id = user_id
        self._session_id = session_id
        self._created_at = datetime.now()
        self._last_updated = datetime.now()
        self._messages: List[Message] = []
        self._agent_states: Dict[str, AgentState] = {}
        self._context_vector: List[float] = []
        self._state_version: int = 0
        self._is_active: bool = True

    # --- Properties ---

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def last_updated(self) -> datetime:
        return self._last_updated

    @property
    def messages(self) -> List[Message]:
        return list(self._messages)

    @property
    def agent_states(self) -> Dict[str, AgentState]:
        return dict(self._agent_states)

    @property
    def context_vector(self) -> List[float]:
        return list(self._context_vector)

    @property
    def state_version(self) -> int:
        return self._state_version

    @property
    def is_active(self) -> bool:
        return self._is_active

    # --- Domain methods ---

    def add_message(self, role: MessageRole, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Append a message to the conversation history."""
        if not isinstance(content, str):
            raise ValueError(f"content must be str, got {type(content)}")
        if not content.strip():
            raise ValueError("content must not be empty")

        message = Message(role=role, content=content, metadata=metadata or {})
        self._messages.append(message)
        self._recompute_context()
        self._state_version += 1
        self._last_updated = datetime.now()

    def add_agent_state(self, agent_id: str, state: AgentState) -> None:
        """Register or update an agent's state."""
        if not agent_id:
            raise ValueError("agent_id must be non-empty")
        state.agent_id = agent_id
        state.updated_at = datetime.now()
        self._agent_states[agent_id] = state

    def get_agent_state(self, agent_id: str) -> Optional[AgentState]:
        """Retrieve an agent's current state."""
        return self._agent_states.get(agent_id)

    def remove_agent_state(self, agent_id: str) -> bool:
        """Remove an agent's state. Returns True if removed."""
        if agent_id in self._agent_states:
            del self._agent_states[agent_id]
            return True
        return False

    def deactivate(self) -> None:
        """Mark the session as inactive."""
        self._is_active = False
        self._state_version += 1
        self._last_updated = datetime.now()

    def activate(self) -> None:
        """Mark the session as active."""
        self._is_active = True
        self._state_version += 1
        self._last_updated = datetime.now()

    def get_summary(self) -> str:
        """Return a human-readable summary of the session."""
        return (
            f"Session {self._session_id} "
            f"(User: {self._user_id}) - "
            f"{len(self._messages)} messages, "
            f"v{self._state_version}"
        )

    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """Return serialized conversation history."""
        return [msg.to_dict() for msg in self._messages]

    # --- Internal helpers ---

    def _recompute_context(self) -> None:
        """Recompute the context vector from recent messages."""
        self._context_vector = ContextVectorizer.embed_context(self._messages)

    def serialize(self) -> Dict[str, Any]:
        """Serialize the full session state."""
        return {
            "user_id": self._user_id,
            "session_id": self._session_id,
            "created_at": self._created_at.isoformat(),
            "last_updated": self._last_updated.isoformat(),
            "messages": [m.to_dict() for m in self._messages],
            "agent_states": {k: v.to_dict() for k, v in self._agent_states.items()},
            "context_vector": self._context_vector,
            "state_version": self._state_version,
            "is_active": self._is_active,
        }

    @classmethod
    def deserialize(cls, data: Dict[str, Any]) -> "SessionState":
        """Deserialize a session state from a dictionary."""
        obj = cls(data["user_id"], data["session_id"])
        obj._created_at = datetime.fromisoformat(data["created_at"])
        obj._last_updated = datetime.fromisoformat(data["last_updated"])
        obj._messages = [Message.from_dict(m) for m in data["messages"]]
        obj._agent_states = {
            k: AgentState.from_dict(v) for k, v in data.get("agent_states", {}).items()
        }
        obj._context_vector = data.get("context_vector", [])
        obj._state_version = data.get("state_version", 0)
        obj._is_active = data.get("is_active", True)
        return obj