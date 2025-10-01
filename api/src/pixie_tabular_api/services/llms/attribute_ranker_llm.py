from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from langchain_core.messages import SystemMessage

from ..abstractclasses.llm import LLM


class AttributeRankerLLM:
    """LLM helper that orders attributes by usefulness for customer decision making."""

    def __init__(self, llm: LLM):
        self.llm = llm
        self.system_prompt_template = """
You are an assistant that helps customers choose the best product using table data.
Given the table context and attribute descriptions, rank the attributes from most to least useful for helping a customer decide.
Return only valid JSON with the shape {"ranking": {"attribute_name": rank, ...}} where rank 1 is most useful. Use consecutive integers without ties.
Table name: {table_name}
Table description: {table_description}
Attributes:
{attributes_block}
"""

    def rank(
        self,
        *,
        table_name: str,
        table_description: str,
        attributes: Dict[str, Dict[str, Any]],
    ) -> Dict[str, int]:
        if not attributes:
            return {}

        attributes_block = "\n".join(
            _format_attribute_block(name, meta) for name, meta in attributes.items()
        )

        prompt = self.system_prompt_template.format(
            table_name=table_name,
            table_description=table_description or "",
            attributes_block=attributes_block,
        )

        try:
            response = self.llm.invoke([SystemMessage(content=prompt)])
            if response is None:
                return {}
            content = getattr(response, "content", None)
            if isinstance(content, list):
                content = "\n".join(
                    part.get("text", "") for part in content if isinstance(part, dict)
                )
            if not isinstance(content, str):
                return {}
            return _parse_ranking(content, expected=len(attributes))
        except Exception as exc:  # pragma: no cover - relies on external service
            logging.error("Failed to obtain attribute ranking: %s", exc)
            return {}


def _format_attribute_block(name: str, meta: Dict[str, Any]) -> str:
    parts = [f"- {name}"]
    attr_type = meta.get("type")
    if attr_type:
        parts.append(f"    type: {attr_type}")
    description = meta.get("description")
    if description:
        parts.append(f"    description: {description}")
    values = meta.get("values")
    if values:
        sample = values[:5] if isinstance(values, list) else values
        parts.append(f"    sample values: {sample}")
    return "\n".join(parts)


def _parse_ranking(content: str, *, expected: int) -> Dict[str, int]:
    raw = content.strip()
    if raw.startswith("```"):
        raw = _strip_code_fence(raw)

    parsed = _load_json(raw)
    if parsed is None:
        return {}

    if isinstance(parsed, dict) and "ranking" in parsed:
        parsed = parsed["ranking"]

    ranking: Dict[str, int] = {}
    if isinstance(parsed, dict):
        for key, value in parsed.items():
            rank = _to_int(value)
            if rank is not None:
                ranking[str(key)] = rank
    elif isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict):
                continue
            name = item.get("attribute") or item.get("name")
            rank = _to_int(item.get("rank"))
            if name and rank is not None:
                ranking[str(name)] = rank

    # Normalise ranks to consecutive integers starting from 1 if possible.
    if ranking:
        ordered_items = sorted(ranking.items(), key=lambda kv: (kv[1], kv[0]))
        normalised: Dict[str, int] = {}
        for idx, (name, _) in enumerate(ordered_items, start=1):
            normalised[name] = idx
        return normalised

    return {}


def _strip_code_fence(text: str) -> str:
    lines = [line for line in text.splitlines() if not line.startswith("```")]
    return "\n".join(lines).strip()


def _load_json(raw: str) -> Optional[Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = raw[start : end + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                return None
        return None


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["AttributeRankerLLM"]
