"""Abstract repository interface for session persistence."""

from abc import ABC, abstractmethod
from typing import List, Optional

from domain.session.models import SessionState


class SessionRepository(ABC):
    """Abstract interface for session persistence.

    Implementations may use Redis, PostgreSQL, or any other storage backend.
    """

    @abstractmethod
    def save(self, session: SessionState) -> None:
        """Persist a session state."""
        ...

    @abstractmethod
    def find_by_id(self, session_id: str) -> Optional[SessionState]:
        """Retrieve a session by its ID. Returns None if not found."""
        ...

    @abstractmethod
    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        ...

    @abstractmethod
    def search_by_context(
        self,
        query_vector: List[float],
        limit: int = 10,
    ) -> List[SessionState]:
        """Find sessions most similar to the query vector."""
        ...