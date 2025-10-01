from __future__ import annotations

from typing import Any, Iterable
from openai import AzureOpenAI

from ..abstractclasses.llm import LLM


class AzureOpenAILLM(LLM):
    """LLM wrapper around Azure OpenAI Chat Completions."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        api_version: str,
        deployment: str,
        default_temperature: float = 0.0,
    ) -> None:
        client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
        )
        super().__init__(deployment, client=client)
        self._temperature = default_temperature

    def invoke(self, messages: Iterable[Any]) -> Any:
        chat_messages = [
            {
                "role": _map_role(getattr(message, "type", "user")),
                "content": _extract_content(message),
            }
            for message in messages
        ]

        completion = self._client.chat.completions.create(
            model=self.model_name,
            messages=chat_messages,
            temperature=self._temperature,
        )
        return completion.choices[0].message if completion.choices else None


def _map_role(role: str) -> str:
    if role == "human":
        return "user"
    if role == "ai":
        return "assistant"
    return role or "user"


def _extract_content(message: Any) -> Any:
    content = getattr(message, "content", None)
    if isinstance(content, list):
        # LangChain messages sometimes provide structured content - join text parts
        return "\n".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    if content is None:
        return str(message)
    return content


__all__ = ["AzureOpenAILLM"]
