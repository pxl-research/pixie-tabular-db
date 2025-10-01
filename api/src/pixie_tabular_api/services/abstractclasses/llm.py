from abc import ABC, abstractmethod
from typing import Any, Sequence


class LLM(ABC):
    """Abstract base class for language models."""

    def __init__(self, model_name: str, *, client: Any | None = None):
        self.model_name = model_name
        self._client: Any | None = client

    @abstractmethod
    def invoke(self, messages: Sequence[Any], **kwargs: Any) -> Any:
        """Execute the underlying LLM with the provided messages."""
        raise NotImplementedError


__all__ = ["LLM"]
