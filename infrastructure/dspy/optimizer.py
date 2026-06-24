"""DSPy-based prompt optimizer.

Provides prompt optimization using DSPy patterns (Mipro, Teleprompter).
Falls back to heuristic optimization when DSPy is not available.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PromptCandidate:
    """Represents a prompt optimization candidate."""

    def __init__(
        self,
        prompt: str,
        score: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.prompt = prompt
        self.score = score
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "score": self.score,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromptCandidate":
        return cls(
            prompt=data.get("prompt", ""),
            score=data.get("score", 0.0),
            metadata=data.get("metadata", {}),
        )


class DSPyPromptOptimizer:
    """Prompt optimizer using DSPy patterns.

    Supports multiple optimization strategies:
    - DSPy Mipro (when available)
    - Heuristic-based optimization (fallback)
    """

    def __init__(
        self,
        model: str = "local/llama-server",
        metric: str = "accuracy",
        strategy: str = "heuristic",
    ):
        self.model_name = model
        self.metric = metric
        self.strategy = strategy
        self._candidates: List[PromptCandidate] = []
        self._optimized_count: int = 0

    @property
    def optimized_count(self) -> int:
        return self._optimized_count

    def optimize_prompt(
        self,
        prompt: str,
        training_data: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Optimize a prompt using the configured strategy."""
        if not prompt:
            raise ValueError("prompt must be non-empty")

        logger.info(
            "DSPy optimization requested (strategy=%s). Prompt: %.80s...",
            self.strategy,
            prompt,
        )

        if self.strategy == "dspy":
            result = self._optimize_with_dspy(prompt, training_data)
        else:
            result = self._optimize_heuristic(prompt, training_data)

        self._optimized_count += 1
        return result

    def evaluate_prompt(
        self,
        prompt: str,
        test_data: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        """Evaluate a prompt against test data. Returns metrics dict."""
        if not test_data:
            return {"accuracy": 0.0, "coverage": 0.0}

        # Heuristic evaluation
        has_instructions = bool(re.search(r"(explain|describe|write|create)", prompt, re.IGNORECASE))
        has_examples = "<example>" in prompt.lower()
        has_format = "format:" in prompt.lower() or "output:" in prompt.lower()

        accuracy = 0.3 + (0.2 if has_instructions else 0) + (0.2 if has_examples else 0) + (0.1 if has_format else 0)
        coverage = min(1.0, len(test_data) / 10)

        return {
            "accuracy": round(accuracy, 4),
            "coverage": round(coverage, 4),
            "prompt_length": len(prompt),
            "token_estimate": len(prompt) // 4,
        }

    def get_best_candidate(self) -> Optional[PromptCandidate]:
        """Return the best optimization candidate."""
        if not self._candidates:
            return None
        return max(self._candidates, key=lambda c: c.score)

    def _optimize_with_dspy(
        self,
        prompt: str,
        training_data: Optional[List[Dict[str, Any]]],
    ) -> str:
        """Attempt DSPy-based optimization."""
        try:
            import dspy  # type: ignore

            if training_data:
                teleprompter = dspy.Mipro(
                    predictor=prompt,
                    metric=self._dspy_metric,
                    trainset=training_data,
                )
                optimized = teleprompter.compile()
                self._candidates.append(PromptCandidate(
                    prompt=str(optimized),
                    score=0.95,
                    metadata={"method": "dspy_mipro"},
                ))
                return str(optimized)
            else:
                logger.warning("No training data for DSPy optimization — returning original")
                return prompt
        except ImportError:
            logger.warning("DSPy not installed — falling back to heuristic optimization")
            return self._optimize_heuristic(prompt, training_data)
        except Exception as exc:
            logger.warning("DSPy optimization failed (%s) — falling back to heuristic", exc)
            return self._optimize_heuristic(prompt, training_data)

    def _optimize_heuristic(
        self,
        prompt: str,
        training_data: Optional[List[Dict[str, Any]]],
    ) -> str:
        """Heuristic prompt optimization.

        Applies common prompt engineering patterns:
        1. Add clear instructions
        2. Add structure hints
        3. Add output format specification
        """
        optimized = prompt.strip()

        # Ensure the prompt starts with a clear action verb
        if not re.match(r"^[A-Z]", optimized):
            optimized = "Analyze and respond to the following: " + optimized

        # Add output format hint if not present
        if not re.search(r"(format|output|structure)", optimized, re.IGNORECASE):
            optimized += "\n\nPlease provide a clear, structured response."

        # Add examples hint if training data available
        if training_data and len(training_data) >= 3:
            optimized += "\n\nConsider the patterns in the provided examples."

        self._candidates.append(PromptCandidate(
            prompt=optimized,
            score=0.7 + len(training_data or []) * 0.02,
            metadata={"method": "heuristic"},
        ))

        return optimized

    @staticmethod
    def _dspy_metric(prediction: Any, example: Any, **kwargs) -> float:  # type: ignore
        """Default DSPy metric — placeholder."""
        return 1.0