"""Service helpers for querying document rows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..schemas import AttributeRangeFilter, DocumentQueryRequest, DocumentQueryResponse
from .documents_service import (
    normalize_to_dict,
    get_collection_id,
    normalize_collection_name,
)

_NUMERIC_REGEX_SQL = "^\\s*-?[0-9]+(?:\\.[0-9]+)?\\s*$"

logger = logging.getLogger(__name__)


@dataclass
class _DocumentInfo:
    """Internal representation of document metadata for querying."""

    document_id: int
    field_types: Dict[str, str]


def _get_document_info(
    db: Session,
    collection_id: int,
    product_name: str,
) -> _DocumentInfo:
    """Fetch document metadata needed for querying."""
    document_row = db.execute(
        text(
            """
            SELECT id, file_schema
            FROM tabular_documents
            WHERE collection_id = :collection_id AND product_name = :product_name
            """
        ),
        {"collection_id": collection_id, "product_name": product_name},
    ).fetchone()

    if document_row is None:
        raise HTTPException(status_code=404, detail="Product not found in collection")

    schema: Dict[str, Any] = normalize_to_dict(document_row.file_schema)
    field_types: Dict[str, str] = (
        schema.get("field_types", {}) if isinstance(schema, dict) else {}
    )

    return _DocumentInfo(document_id=document_row.id, field_types=field_types)


def _build_filter_clause(
    attribute_filter: Any,
    index: int,
    field_types: Dict[str, str],
    filter_conditions: list[str],
    filter_params: Dict[str, Any],
) -> None:
    """Build SQL filter clause for a single attribute filter."""
    attribute_name = attribute_filter.name.strip()
    if not attribute_name:
        raise HTTPException(status_code=400, detail="Attribute name cannot be empty")

    if attribute_name not in field_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown attribute '{attribute_name}' for document",
        )

    attr_param = f"attr_{index}"
    filter_params[attr_param] = attribute_name
    column_type = field_types.get(attribute_name, "TEXT")

    if isinstance(attribute_filter, AttributeRangeFilter):
        _build_range_filter(
            attribute_filter,
            index,
            attribute_name,
            column_type,
            attr_param,
            filter_conditions,
            filter_params,
        )
    elif column_type == "NUMERIC":
        _build_numeric_filter(
            attribute_filter,
            index,
            attribute_name,
            attr_param,
            filter_conditions,
            filter_params,
        )
    elif column_type == "BOOLEAN":
        _build_boolean_filter(
            attribute_filter,
            index,
            attribute_name,
            attr_param,
            filter_conditions,
            filter_params,
        )
    else:
        _build_text_filter(
            attribute_filter, index, attr_param, filter_conditions, filter_params
        )


def _build_range_filter(
    attribute_filter: AttributeRangeFilter,
    index: int,
    attribute_name: str,
    column_type: str,
    attr_param: str,
    filter_conditions: list[str],
    filter_params: Dict[str, Any],
) -> None:
    """Build SQL filter for numeric range queries."""
    if column_type != "NUMERIC":
        raise HTTPException(
            status_code=400,
            detail=(
                "Range filters are only supported for numeric attributes "
                f"(received '{attribute_name}')"
            ),
        )

    numeric_expr = _numeric_expression(attr_param)
    if attribute_filter.min_value is not None:
        min_param = f"min_{index}"
        filter_params[min_param] = _parse_decimal(
            attribute_filter.min_value, attribute_name
        )
        filter_conditions.append(f"{numeric_expr} >= :{min_param}")
    if attribute_filter.max_value is not None:
        max_param = f"max_{index}"
        filter_params[max_param] = _parse_decimal(
            attribute_filter.max_value, attribute_name
        )
        filter_conditions.append(f"{numeric_expr} <= :{max_param}")


def _build_numeric_filter(
    attribute_filter: Any,
    index: int,
    attribute_name: str,
    attr_param: str,
    filter_conditions: list[str],
    filter_params: Dict[str, Any],
) -> None:
    """Build SQL filter for exact numeric value matching."""
    numeric_expr = _numeric_expression(attr_param)
    value_param = f"value_{index}"
    filter_params[value_param] = _parse_decimal(attribute_filter.value, attribute_name)
    filter_conditions.append(f"{numeric_expr} = :{value_param}")


def _build_boolean_filter(
    attribute_filter: Any,
    index: int,
    attribute_name: str,
    attr_param: str,
    filter_conditions: list[str],
    filter_params: Dict[str, Any],
) -> None:
    """Build SQL filter for boolean value matching."""
    boolean_expr = _boolean_expression(attr_param)
    value_param = f"value_{index}"
    filter_params[value_param] = _parse_boolean(attribute_filter.value, attribute_name)
    filter_conditions.append(f"{boolean_expr} = :{value_param}")


def _build_text_filter(
    attribute_filter: Any,
    index: int,
    attr_param: str,
    filter_conditions: list[str],
    filter_params: Dict[str, Any],
) -> None:
    """Build SQL filter for text value matching."""
    value_param = f"value_{index}"
    filter_params[value_param] = str(attribute_filter.value)
    filter_conditions.append(
        f"jsonb_extract_path_text(attributes, :{attr_param}) = :{value_param}"
    )


def execute_document_query(
    *,
    db: Session,
    collection_name: str,
    product_name: str,
    request: DocumentQueryRequest,
) -> DocumentQueryResponse:
    """Run a filtered row query for a given product within a collection."""

    trimmed_collection = normalize_collection_name(collection_name)
    trimmed_product = product_name.strip()
    if not trimmed_product:
        raise HTTPException(
            status_code=400,
            detail="Collection and product names are required",
        )

    logger.info(
        "Querying collection '%s', product '%s' with %d filter(s) (limit=%d, offset=%d)",
        trimmed_collection,
        trimmed_product,
        len(request.filters),
        request.limit,
        request.offset,
    )

    collection_id = get_collection_id(db, trimmed_collection)
    doc_info = _get_document_info(db, collection_id, trimmed_product)

    filter_conditions: list[str] = ["file_id = :document_id"]
    filter_params: Dict[str, Any] = {"document_id": doc_info.document_id}

    for index, attribute_filter in enumerate(request.filters):
        _build_filter_clause(
            attribute_filter,
            index,
            doc_info.field_types,
            filter_conditions,
            filter_params,
        )

    where_clause = " AND ".join(filter_conditions)

    rows_stmt = text(
        f"""
        SELECT attributes
        FROM tabular_rows
        WHERE {where_clause}
        ORDER BY id ASC
        LIMIT :limit OFFSET :offset
        """
    )
    count_stmt = text(f"SELECT COUNT(*) FROM tabular_rows WHERE {where_clause}")

    rows_params = {**filter_params, "limit": request.limit, "offset": request.offset}

    rows_result = db.execute(rows_stmt, rows_params).fetchall()
    total_count = db.execute(count_stmt, filter_params).scalar_one()

    return DocumentQueryResponse(
        product_name=trimmed_product,
        results=[row.attributes for row in rows_result],
        count=len(rows_result),
        total=total_count,
        limit=request.limit,
        offset=request.offset,
    )


def _numeric_expression(attr_param: str) -> str:
    return (
        "CASE "
        f"WHEN jsonb_extract_path_text(attributes, :{attr_param}) ~ '{_NUMERIC_REGEX_SQL}' "
        f"THEN trim(jsonb_extract_path_text(attributes, :{attr_param}))::numeric "
        "ELSE NULL END"
    )


def _boolean_expression(attr_param: str) -> str:
    return (
        "CASE "
        f"WHEN jsonb_extract_path_text(attributes, :{attr_param}) IS NULL THEN NULL "
        f"WHEN lower(jsonb_extract_path_text(attributes, :{attr_param})) IN ('true', 'false') "
        f"THEN (jsonb_extract_path_text(attributes, :{attr_param}))::boolean "
        "ELSE NULL END"
    )


def _parse_decimal(value: Any, attribute_name: str) -> Decimal:
    try:
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        if isinstance(value, str):
            trimmed = value.strip()
            if not trimmed:
                raise ValueError
            return Decimal(trimmed)
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as exc:  # pragma: no cover - defensive path
        raise HTTPException(
            status_code=400,
            detail=f"Invalid numeric value for attribute '{attribute_name}'",
        ) from exc
    raise HTTPException(
        status_code=400,
        detail=f"Invalid numeric value for attribute '{attribute_name}'",
    )


def _parse_boolean(value: Any, attribute_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value in (0, 0.0):
            return False
        if value in (1, 1.0):
            return True
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    raise HTTPException(
        status_code=400,
        detail=f"Invalid boolean value for attribute '{attribute_name}'",
    )


__all__ = ["execute_document_query"]
