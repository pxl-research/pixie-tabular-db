from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...database import get_db
from ...schemas import AttributeRangeFilter, DocumentQueryRequest, DocumentQueryResponse

_NUMERIC_REGEX_SQL = "^\\s*-?[0-9]+(?:\\.[0-9]+)?\\s*$"

router = APIRouter()


@router.post("/{product_name}/query", response_model=DocumentQueryResponse)
def query_document_rows(
    collection_name: str,
    product_name: str,
    payload: DocumentQueryRequest,
    db: Session = Depends(get_db),
) -> DocumentQueryResponse:
    trimmed_collection = collection_name.strip()
    trimmed_product = product_name.strip()

    if not trimmed_collection or not trimmed_product:
        raise HTTPException(
            status_code=400,
            detail="Collection and product names are required",
        )

    document_row = db.execute(
        text(
            """
            SELECT d.id AS document_id, d.file_schema
            FROM tabular_collections c
            JOIN tabular_collection_entries e ON e.collection_id = c.id
            JOIN tabular_documents d ON d.id = e.document_id
            WHERE c.name = :collection_name AND e.product_name = :product_name
            """
        ),
        {"collection_name": trimmed_collection, "product_name": trimmed_product},
    ).fetchone()

    if document_row is None:
        raise HTTPException(status_code=404, detail="Product not found in collection")

    schema: dict[str, Any] = document_row.file_schema or {}
    field_types: dict[str, str] = schema.get("field_types", {}) if isinstance(schema, dict) else {}

    filter_conditions: list[str] = ["file_id = :document_id"]
    filter_params: dict[str, Any] = {"document_id": document_row.document_id}

    for index, attribute_filter in enumerate(payload.filters):
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
            if column_type != "NUMERIC":
                raise HTTPException(
                    status_code=400,
                    detail=f"Range filters are only supported for numeric attributes (received '{attribute_name}')",
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
            continue

        if column_type == "NUMERIC":
            numeric_expr = _numeric_expression(attr_param)
            value_param = f"value_{index}"
            filter_params[value_param] = _parse_decimal(
                attribute_filter.value, attribute_name
            )
            filter_conditions.append(f"{numeric_expr} = :{value_param}")
            continue

        if column_type == "BOOLEAN":
            boolean_expr = _boolean_expression(attr_param)
            value_param = f"value_{index}"
            filter_params[value_param] = _parse_boolean(
                attribute_filter.value, attribute_name
            )
            filter_conditions.append(f"{boolean_expr} = :{value_param}")
            continue

        value_param = f"value_{index}"
        filter_params[value_param] = str(attribute_filter.value)
        filter_conditions.append(
            f"jsonb_extract_path_text(attributes, :{attr_param}) = :{value_param}"
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
    count_stmt = text(
        f"SELECT COUNT(*) FROM tabular_rows WHERE {where_clause}"
    )

    rows_params = {**filter_params, "limit": payload.limit, "offset": payload.offset}

    rows_result = db.execute(rows_stmt, rows_params).fetchall()
    total_count = db.execute(count_stmt, filter_params).scalar_one()

    return DocumentQueryResponse(
        product_name=trimmed_product,
        results=[row.attributes for row in rows_result],
        count=len(rows_result),
        total=total_count,
        limit=payload.limit,
        offset=payload.offset,
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
    except (InvalidOperation, TypeError, ValueError) as exc:  # pragma: no cover - defensive guarding
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


__all__ = [
    "query_document_rows",
    "router",
]
