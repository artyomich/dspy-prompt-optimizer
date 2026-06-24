"""Agent domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentType(str, Enum):
    """Types of specialized agents."""

    RESEARCH = "research"
    CODING = "coding"
    REVIEW = "review"
    QA = "qa"


@dataclass
class AgentTask:
    """A task assigned to an agent."""

    task_id: str
    description: str
    status: str = "pending"
    result: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "status": self.status,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentTask":
        return cls(
            task_id=data.get("task_id", ""),
            description=data.get("description", ""),
            status=data.get("status", "pending"),
            result=data.get("result"),
        )


class Agent:
    """Represents a specialized agent in the system."""

    def __init__(
        self,
        agent_id: str,
        agent_type: AgentType,
        description: str = "",
    ):
        if not agent_id:
            raise ValueError("agent_id must be non-empty")
        self._agent_id = agent_id
        self._agent_type = agent_type
        self._description = description
        self._tasks: List[AgentTask] = []
        self._status: str = "idle"
        self._created_at = datetime.now()
        self._last_updated = datetime.now()

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def agent_type(self) -> AgentType:
        return self._agent_type

    @property
    def description(self) -> str:
        return self._description

    @property
    def status(self) -> str:
        return self._status

    @property
    def tasks(self) -> List[AgentTask]:
        return list(self._tasks)

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def last_updated(self) -> datetime:
        return self._last_updated

    def assign_task(self, task_id: str, description: str) -> AgentTask:
        """Assign a new task to this agent."""
        task = AgentTask(task_id=task_id, description=description)
        self._tasks.append(task)
        self._status = "active"
        self._last_updated = datetime.now()
        return task

    def complete_task(self, task_id: str, result: str) -> bool:
        """Mark a task as completed."""
        for task in self._tasks:
            if task.task_id == task_id:
                task.status = "completed"
                task.result = result
                self._last_updated = datetime.now()
                return True
        return False

    def set_status(self, status: str) -> None:
        """Update agent status."""
        self._status = status
        self._last_updated = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self._agent_id,
            "agent_type": self._agent_type.value,
            "description": self._description,
            "status": self._status,
            "tasks": [t.to_dict() for t in self._tasks],
            "created_at": self._created_at.isoformat(),
            "last_updated": self._last_updated.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Agent":
        created_at_str = data.get("created_at", datetime.now().isoformat())
        last_updated_str = data.get("last_updated", datetime.now().isoformat())
        agent = cls(
            agent_id=data.get("agent_id", ""),
            agent_type=AgentType(data.get("agent_type", "research")),
            description=data.get("description", ""),
        )
        agent._status = data.get("status", "idle")
        agent._tasks = [AgentTask.from_dict(t) for t in data.get("tasks", [])]
        agent._created_at = datetime.fromisoformat(created_at_str)
        agent._last_updated = datetime.fromisoformat(last_updated_str)
        return agent


class AgentRegistry:
    """Registry of available agents (in-memory for now)."""

    def __init__(self) -> None:
        self._agents: Dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        """Register an agent in the registry."""
        self._agents[agent.agent_id] = agent

    def get(self, agent_id: str) -> Optional[Agent]:
        """Retrieve an agent by ID."""
        return self._agents.get(agent_id)

    def list_all(self) -> List[Agent]:
        """List all registered agents."""
        return list(self._agents.values())

    def remove(self, agent_id: str) -> bool:
        """Remove an agent from the registry."""
        if agent_id in self._agents:
            del self._agents[agent_id]
            return True
        return False