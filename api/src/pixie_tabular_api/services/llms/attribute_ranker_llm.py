from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from ..abstractclasses.llm import LLM


class AttributeRankerLLM:
    """LLM helper that orders attributes by usefulness for customer decision making."""

    def __init__(self, llm: LLM):
        self.llm = llm
        self.system_prompt_template = """
You are an assistant that helps customers choose the best product using tabular data.
Your response MUST be valid JSON with the structure {{"ranking": {{"attribute_name": rank, ...}}}},
where rank 1 is most useful and ranks are consecutive integers without ties. Do not include
any additional keys, commentary, or formatting.

Input data (JSON):
{payload}
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

        payload = json.dumps(
            {
                "table_name": table_name,
                "table_description": table_description or "",
                "attributes": attributes,
            },
            ensure_ascii=False,
        )

        prompt = self.system_prompt_template.format(payload=payload)

        messages = [
            SystemMessage(
                content=(
                    "You MUST respond with strict JSON. The response body must be a JSON object "
                    "containing a single property named 'ranking'."
                )
            ),
            HumanMessage(content=prompt),
        ]

        try:
            response = self.llm.invoke(
                messages,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            logging.debug(
                "Attribute ranking JSON mode failed (%s); retrying without response_format",
                exc,
            )
            response = self.llm.invoke(messages)

        try:
            if response is None:
                return {}
            content = getattr(response, "content", None)
            if isinstance(content, list):
                content = "\n".join(
                    part.get("text", "") for part in content if isinstance(part, dict)
                )
            if not isinstance(content, str):
                return {}
            logging.debug("Attribute ranking raw response: %s", content)
            return _parse_ranking(content)
        except Exception as exc:  # pragma: no cover - relies on external service
            logging.error("Failed to obtain attribute ranking: %s", exc)
            return {}

def _parse_ranking(content: str) -> Dict[str, int]:
    raw = content.strip()
    if raw.startswith("```"):
        raw = _strip_code_fence(raw)

    parsed = _load_json(raw)
    if parsed is None:
        enumerated = _parse_enumerated_lines(raw)
        if enumerated:
            return enumerated
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
        if all(isinstance(item, str) for item in parsed):
            return {str(name): idx for idx, name in enumerate(parsed, start=1)}
        for item in parsed:
            if isinstance(item, dict):
                name = item.get("attribute") or item.get("name")
                rank = _to_int(item.get("rank"))
                if name and rank is not None:
                    ranking[str(name)] = rank
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                name = item[0]
                rank = _to_int(item[1])
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


_ENUMERATION_PATTERN = re.compile(r"^\s*(\d+)[\.:)\-]\s*(.+)$")


def _parse_enumerated_lines(raw: str) -> Dict[str, int]:
    ranking: Dict[str, int] = {}
    for line in raw.splitlines():
        match = _ENUMERATION_PATTERN.match(line)
        if not match:
            continue
        rank = _to_int(match.group(1))
        name = match.group(2).strip()
        if rank is None or not name:
            continue
        ranking[name] = rank

    if ranking:
        ordered = sorted(ranking.items(), key=lambda kv: (kv[1], kv[0]))
        return {name: idx for idx, (name, _) in enumerate(ordered, start=1)}

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
