"""Pydantic models for input validation and security."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    field_serializer,
)
from datetime import datetime


# --- Session validation models ---

class SessionCreateRequest(BaseModel):
    """Validated request to create a session."""

    user_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique user identifier",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique session identifier",
    )

    @field_validator("user_id", "session_id")
    @classmethod
    def sanitize_id(cls, value: str) -> str:
        """Sanitize ID to prevent injection attacks."""
        cleaned = re.sub(r"[^\w\-]", "", value)
        if len(cleaned) != len(value):
            raise ValueError("ID contains invalid characters")
        return cleaned


class RequestContext(BaseModel):
    """Validated request context for processing."""

    user_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="User message content",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("user_id", "session_id")
    @classmethod
    def sanitize_id(cls, value: str) -> str:
        """Sanitize ID to prevent injection attacks."""
        cleaned = re.sub(r"[^\w\-]", "", value)
        if len(cleaned) != len(value):
            raise ValueError("ID contains invalid characters")
        return cleaned

    @field_validator("message")
    @classmethod
    def sanitize_message(cls, value: str) -> str:
        """Sanitize message content to prevent XSS."""
        if len(value) > 10000:
            raise ValueError("Message exceeds maximum length of 10000 characters")
        return value


class ProcessingResult(BaseModel):
    """Result of processing a request."""

    session_id: str
    agent_responses: List[Dict[str, Any]] = Field(default_factory=list)
    optimized_prompt: Optional[str] = None

    @field_serializer("agent_responses")
    @staticmethod
    def serialize_agent_responses(value: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Serialize agent responses safely."""
        return value

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return self.model_dump()


# --- Message validation models ---

class MessageCreateRequest(BaseModel):
    """Validated message creation request."""

    role: str = Field(..., description="Message role: user, assistant, or system")
    content: str = Field(
        ...,
        min_length=1,
        max_length=100000,
        description="Message content",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        """Validate message role."""
        valid_roles = {"user", "assistant", "system"}
        if value not in valid_roles:
            raise ValueError(f"Role must be one of: {valid_roles}")
        return value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        """Validate and sanitize message content."""
        if not value.strip():
            raise ValueError("Content must not be empty or whitespace only")
        if len(value) > 100000:
            raise ValueError("Content exceeds maximum length")
        return value


# --- Agent validation models ---

class AgentCreateRequest(BaseModel):
    """Validated agent creation request."""

    agent_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )
    agent_type: str = Field(
        ...,
        description="Agent type: research, coding, review, or qa",
    )
    description: str = Field(
        default="",
        max_length=1000,
    )

    @field_validator("agent_id")
    @classmethod
    def sanitize_agent_id(cls, value: str) -> str:
        """Sanitize agent ID."""
        cleaned = re.sub(r"[^\w\-]", "", value)
        if len(cleaned) != len(value):
            raise ValueError("Agent ID contains invalid characters")
        return cleaned

    @field_validator("agent_type")
    @classmethod
    def validate_agent_type(cls, value: str) -> str:
        """Validate agent type."""
        valid_types = {"research", "coding", "review", "qa"}
        if value not in valid_types:
            raise ValueError(f"Agent type must be one of: {valid_types}")
        return value


# --- Prompt validation models ---

class PromptOptimizeRequest(BaseModel):
    """Validated prompt optimization request."""

    prompt: str = Field(
        ...,
        min_length=1,
        max_length=10000,
    )
    training_data: Optional[List[Dict[str, Any]]] = None

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        """Validate prompt content."""
        if not value.strip():
            raise ValueError("Prompt must not be empty or whitespace only")
        return value


class PromptEvaluateRequest(BaseModel):
    """Validated prompt evaluation request."""

    prompt: str = Field(
        ...,
        min_length=1,
        max_length=10000,
    )
    test_data: List[Dict[str, Any]] = Field(
        ...,
        min_length=1,
        max_length=1000,
    )


# --- Configuration validation models ---

class DatabaseConfig(BaseModel):
    """Validated database configuration."""

    dbname: str = Field(default="agents")
    user: str = Field(default="postgres")
    password: str = Field(default="")
    host: str = Field(default="localhost")
    port: int = Field(default=5432)
    connect_timeout: int = Field(default=5)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        """Ensure password is not the default."""
        if value == "postgres" or value == "changeme_to_secure_password":
            raise ValueError("Password must be changed from default value")
        return value

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        """Validate host format."""
        if not re.match(r"^[\w\.\-]+$", value):
            raise ValueError("Invalid host format")
        return value

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database connection."""
        return {
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password,
            "host": self.host,
            "port": self.port,
            "connect_timeout": self.connect_timeout,
        }


class RedisConfig(BaseModel):
    """Validated Redis configuration."""

    host: str = Field(default="localhost")
    port: int = Field(default=6379)
    db: int = Field(default=0)
    password: Optional[str] = None
    socket_timeout: float = Field(default=2.0)
    socket_connect_timeout: float = Field(default=2.0)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        """Validate host format."""
        if not re.match(r"^[\w\.\-]+$", value):
            raise ValueError("Invalid host format")
        return value

    def to_kwargs(self) -> Dict[str, Any]:
        """Convert to kwargs for Redis connection."""
        kwargs = {
            "host": self.host,
            "port": self.port,
            "db": self.db,
            "decode_responses": True,
            "socket_timeout": self.socket_timeout,
            "socket_connect_timeout": self.socket_connect_timeout,
        }
        if self.password:
            kwargs["password"] = self.password
        return kwargs


class AppConfig(BaseModel):
    """Application configuration loaded from environment."""

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    session_ttl: int = Field(default=604800)
    session_max_age_seconds: int = Field(default=86400)
    secret_key: str = Field(default="changeme_to_random_secret_key")
    allowed_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"]
    )
    dspy_model: str = Field(default="local/llama-server")
    dspy_strategy: str = Field(default="heuristic")
    dspy_metric: str = Field(default="accuracy")
    log_level: str = Field(default="INFO")

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        """Ensure secret key is not the default."""
        if value == "changeme_to_random_secret_key":
            raise ValueError("SECRET_KEY must be changed from default value")
        if len(value) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Validate log level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if value.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return value.upper()