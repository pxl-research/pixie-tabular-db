"""Describe and rank attributes of a table."""

import logging
from typing import Any

import pandas as pd

from .attribute_analyzer import analyze_attribute
from .llms.attribute_describer_llm import AttributeDescriberLLM
from .llms.attribute_ranker_llm import AttributeRankerLLM


def describe_attributes(
    file_name: str,
    file_description: str,
    file_schema: dict[str, str],
    df: pd.DataFrame,
    attribute_describer_llm: AttributeDescriberLLM,
    attribute_ranker_llm: AttributeRankerLLM,
) -> dict[str, dict[str, Any]]:
    """
    Describe attributes based on the file schema and DataFrame, and rank them by usefulness.

    Returns a dictionary with attribute names as keys and metadata (type, description, rank, ...).
    """
    # Step 1: Analyze attribute types
    attributes = {}
    for column_name, datatype in file_schema.items():
        logging.info(f"Analyzing attribute '{column_name}' with datatype '{datatype}'")
        attributes[column_name] = analyze_attribute(column_name, df, datatype)

    # Step 2: Generate descriptions
    for column_name, attr_info in attributes.items():
        description = attribute_describer_llm.generate(
            table_name=file_name,
            table_description=file_description,
            column_name=column_name,
            attribute_values=attr_info.get("values"),
        )
        attr_info["description"] = description

    # Step 3: Add ranking
    ranking = _get_ranking(
        file_name, file_description, attributes, attribute_ranker_llm
    )
    for column_name, rank in ranking.items():
        if column_name in attributes:
            attributes[column_name]["rank"] = rank

    return attributes


def _get_ranking(
    file_name: str,
    file_description: str,
    attributes: dict[str, dict[str, Any]],
    ranker: AttributeRankerLLM,
) -> dict[str, int]:
    """Get ranking with fallback to sequential order."""
    try:
        ranking = ranker.rank(
            table_name=file_name,
            table_description=file_description,
            attributes=attributes,
        )
        if ranking:
            return _fill_missing_ranks(attributes, ranking)
    except Exception as exc:
        logging.error("Ranking failed: %s", exc)

    # Fallback: sequential order
    return {name: idx for idx, name in enumerate(attributes.keys(), start=1)}


def _fill_missing_ranks(
    attributes: dict[str, dict[str, Any]], ranking: dict[str, int]
) -> dict[str, int]:
    """Add ranks for attributes not mentioned by the ranker."""
    max_rank = max(ranking.values(), default=0)
    result = dict(ranking)

    for column_name in attributes:
        if column_name not in result:
            max_rank += 1
            result[column_name] = max_rank

    return result
