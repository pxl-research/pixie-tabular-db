"""Rank attributes by usefulness for customer decision making."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage

from ..abstractclasses.llm import LLM


class AttributeRankerLLM:
    """LLM helper that orders attributes by usefulness for customer decision making."""

    def __init__(self, llm: LLM):
        self.llm = llm

    def rank(
        self,
        *,
        table_name: str,
        table_description: str,
        attributes: Dict[str, Dict[str, Any]],
    ) -> Dict[str, int]:
        """
        Rank attributes by usefulness for customer decisions.

        Returns a dictionary mapping attribute names to ranks, where rank 1 is most useful.
        """
        if not attributes:
            return {}

        prompt = self._build_prompt(table_name, table_description, attributes)
        response = self._call_llm(prompt)

        if not response:
            return {}

        return _parse_ranking(response)

    def _build_prompt(self, table_name: str, description: str, attributes: Dict) -> str:
        """Build the ranking prompt with input data."""
        payload = json.dumps(
            {
                "table_name": table_name,
                "table_description": description or "",
                "attributes": attributes,
            },
            ensure_ascii=False,
        )

        return f"""
You are ranking table attributes by usefulness for customer decisions.
Return ONLY valid JSON: {{"ranking": {{"attribute_name": rank, ...}}}}
Rank 1 is most useful. Use consecutive integers.

Data:
{payload}
"""

    def _call_llm(self, prompt: str) -> str | None:
        """Call LLM with JSON mode, fallback to regular if needed."""
        messages = [
            SystemMessage(content="Respond with valid JSON only: {'ranking': {...}}"),
            HumanMessage(content=prompt),
        ]

        try:
            response = self.llm.invoke(
                messages,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            logging.debug("JSON mode failed (%s), retrying without", exc)
            try:
                response = self.llm.invoke(messages)
            except Exception:
                return None

        if not response:
            return None

        content = getattr(response, "content", None)
        if isinstance(content, list):
            content = "\n".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )

        return str(content) if content else None


def _parse_ranking(content: str) -> Dict[str, int]:
    """Parse LLM response to ranking dict."""
    try:
        data = json.loads(content.strip())

        # Extract ranking dict
        if isinstance(data, dict) and "ranking" in data:
            ranking = data["ranking"]
        else:
            ranking = data

        if not isinstance(ranking, dict):
            return {}

        # Normalize to consecutive integers
        items = sorted(ranking.items(), key=lambda x: (int(x[1]), x[0]))
        return {name: idx for idx, (name, _) in enumerate(items, start=1)}

    except (json.JSONDecodeError, ValueError, TypeError):
        logging.warning("Could not parse ranking from: %s", content[:100])
        return {}


__all__ = ["AttributeRankerLLM"]
