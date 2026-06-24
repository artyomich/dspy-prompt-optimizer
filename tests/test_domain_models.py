"""Unit tests for domain models."""

import pytest
import math
from datetime import datetime

from domain.session.models import (
    Message,
    MessageRole,
    SessionState,
    ContextVectorizer,
    AgentState,
)
from domain.agent.models import Agent, AgentType, AgentTask, AgentRegistry


# ====================================================================
# MessageRole
# ====================================================================

class TestMessageRole:
    def test_user_role(self):
        assert MessageRole.USER == "user"

    def test_assistant_role(self):
        assert MessageRole.ASSISTANT == "assistant"

    def test_system_role(self):
        assert MessageRole.SYSTEM == "system"


# ====================================================================
# Message
# ====================================================================

class TestMessage:
    def test_default_timestamp(self):
        before = datetime.now()
        msg = Message(role=MessageRole.USER, content="hello")
        after = datetime.now()
        assert before <= msg.timestamp <= after

    def test_to_dict(self):
        msg = Message(
            role=MessageRole.USER,
            content="hello",
            metadata={"key": "value"},
        )
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "hello"
        assert d["metadata"]["key"] == "value"
        assert "timestamp" in d

    def test_from_dict(self):
        data = {
            "role": "assistant",
            "content": "hi there",
            "timestamp": "2025-01-15T10:30:00",
            "metadata": {"source": "test"},
        }
        msg = Message.from_dict(data)
        assert msg.role == MessageRole.ASSISTANT
        assert msg.content == "hi there"
        assert msg.metadata["source"] == "test"


# ====================================================================
# ContextVectorizer
# ====================================================================

class TestContextVectorizer:
    def test_embed_context_returns_correct_dim(self):
        msgs = [
            Message(MessageRole.USER, "hello world"),
            Message(MessageRole.ASSISTANT, "hi back"),
        ]
        vec = ContextVectorizer.embed_context(msgs)
        assert len(vec) == 128

    def test_embed_context_is_normalized(self):
        msgs = [Message(MessageRole.USER, "test content")]
        vec = ContextVectorizer.embed_context(msgs)
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-6

    def test_deterministic(self):
        msgs = [Message(MessageRole.USER, "same content")]
        vec1 = ContextVectorizer.embed_context(msgs)
        vec2 = ContextVectorizer.embed_context(msgs)
        assert vec1 == vec2


# ====================================================================
# AgentState
# ====================================================================

class TestAgentState:
    def test_default_values(self):
        state = AgentState(agent_id="test")
        assert state.status == "idle"
        assert state.tasks == []
        assert state.agent_id == "test"

    def test_to_dict(self):
        state = AgentState(agent_id="a1", status="active", tasks=["t1"])
        d = state.to_dict()
        assert d["agent_id"] == "a1"
        assert d["status"] == "active"
        assert d["tasks"] == ["t1"]

    def test_from_dict(self):
        data = {
            "agent_id": "a2",
            "status": "busy",
            "tasks": ["x", "y"],
            "updated_at": "2025-06-01T00:00:00",
        }
        s = AgentState.from_dict(data)
        assert s.agent_id == "a2"
        assert s.status == "busy"
        assert s.tasks == ["x", "y"]


# ====================================================================
# SessionState
# ====================================================================

class TestSessionState:
    def test_create_session(self):
        s = SessionState("user1", "sess1")
        assert s.user_id == "user1"
        assert s.session_id == "sess1"
        assert s.is_active is True
        assert s.state_version == 0
        assert len(s.messages) == 0

    def test_create_session_invalid_user_id(self):
        with pytest.raises(ValueError, match="user_id"):
            SessionState("", "sess1")

    def test_create_session_invalid_session_id(self):
        with pytest.raises(ValueError, match="session_id"):
            SessionState("user1", "")

    def test_add_message(self):
        s = SessionState("u1", "s1")
        s.add_message(MessageRole.USER, "hello")
        assert len(s.messages) == 1
        assert s.state_version == 1

    def test_add_message_empty_content_raises(self):
        s = SessionState("u1", "s1")
        with pytest.raises(ValueError, match="empty"):
            s.add_message(MessageRole.USER, "   ")

    def test_add_message_invalid_content_type(self):
        s = SessionState("u1", "s1")
        with pytest.raises(ValueError, match="content must be str"):
            s.add_message(MessageRole.USER, 123)  # type: ignore

    def test_context_vector_on_add_message(self):
        s = SessionState("u1", "s1")
        assert s.context_vector == []
        s.add_message(MessageRole.USER, "hello")
        assert len(s.context_vector) == 128

    def test_get_summary(self):
        s = SessionState("u1", "s1")
        s.add_message(MessageRole.USER, "hi")
        summary = s.get_summary()
        assert "s1" in summary
        assert "u1" in summary
        assert "1 messages" in summary

    def test_agent_state_management(self):
        s = SessionState("u1", "s1")
        state = AgentState(agent_id="coding", status="active", tasks=["t1"])
        s.add_agent_state("coding", state)
        assert s.get_agent_state("coding").status == "active"
        assert s.remove_agent_state("coding") is True
        assert s.remove_agent_state("coding") is False

    def test_activate_deactivate(self):
        s = SessionState("u1", "s1")
        s.deactivate()
        assert s.is_active is False
        assert s.state_version == 1
        s.activate()
        assert s.is_active is True
        assert s.state_version == 2

    def test_serialize_deserialize_roundtrip(self):
        s = SessionState("u1", "s1")
        s.add_message(MessageRole.USER, "hello")
        s.add_message(MessageRole.ASSISTANT, "hi back")
        s.add_agent_state("coding", AgentState("coding", "active", ["t1"]))

        data = s.serialize()
        restored = SessionState.deserialize(data)

        assert restored.user_id == "u1"
        assert restored.session_id == "s1"
        assert len(restored.messages) == 2
        assert len(restored.context_vector) == 128
        assert "coding" in restored.agent_states

    def test_get_conversation_history(self):
        s = SessionState("u1", "s1")
        s.add_message(MessageRole.USER, "msg1")
        s.add_message(MessageRole.ASSISTANT, "msg2")
        history = s.get_conversation_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"


# ====================================================================
# Agent
# ====================================================================

class TestAgent:
    def test_create_agent(self):
        a = Agent("coding", AgentType.CODING, "Writes code")
        assert a.agent_id == "coding"
        assert a.agent_type == AgentType.CODING
        assert a.status == "idle"
        assert a.tasks == []

    def test_assign_task(self):
        a = Agent("coding", AgentType.CODING)
        task = a.assign_task("t1", "Write function")
        assert task.task_id == "t1"
        assert task.status == "pending"
        assert a.status == "active"
        assert len(a.tasks) == 1

    def test_complete_task(self):
        a = Agent("coding", AgentType.CODING)
        a.assign_task("t1", "Write function")
        result = a.complete_task("t1", "Done")
        assert result is True
        assert a.tasks[0].status == "completed"
        assert a.tasks[0].result == "Done"

    def test_complete_nonexistent_task(self):
        a = Agent("coding", AgentType.CODING)
        assert a.complete_task("nonexistent", "result") is False

    def test_set_status(self):
        a = Agent("coding", AgentType.CODING)
        a.set_status("busy")
        assert a.status == "busy"

    def test_to_dict(self):
        a = Agent("coding", AgentType.CODING, "desc")
        a.assign_task("t1", "d1")
        d = a.to_dict()
        assert d["agent_id"] == "coding"
        assert d["agent_type"] == "coding"
        assert len(d["tasks"]) == 1

    def test_from_dict(self):
        data = {
            "agent_id": "review",
            "agent_type": "review",
            "description": "Reviews code",
            "status": "idle",
            "tasks": [],
            "created_at": "2025-01-01T00:00:00",
            "last_updated": "2025-01-01T00:00:00",
        }
        a = Agent.from_dict(data)
        assert a.agent_id == "review"
        assert a.agent_type == AgentType.REVIEW
        assert a.description == "Reviews code"


# ====================================================================
# AgentRegistry
# ====================================================================

class TestAgentRegistry:
    def test_register_and_get(self):
        reg = AgentRegistry()
        a = Agent("coding", AgentType.CODING)
        reg.register(a)
        assert reg.get("coding") is a

    def test_get_nonexistent(self):
        assert AgentRegistry().get("nonexistent") is None

    def test_list_all(self):
        reg = AgentRegistry()
        reg.register(Agent("a1", AgentType.CODING))
        reg.register(Agent("a2", AgentType.RESEARCH))
        assert len(reg.list_all()) == 2

    def test_remove(self):
        reg = AgentRegistry()
        a = Agent("a1", AgentType.CODING)
        reg.register(a)
        assert reg.remove("a1") is True
        assert reg.remove("a1") is False
        assert len(reg.list_all()) == 0