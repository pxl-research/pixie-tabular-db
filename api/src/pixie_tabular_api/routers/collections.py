import json
import logging
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, List

import pandas as pd
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    Form,
    Request,
    Query,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import (
    AttributeRangeFilter,
    Collection,
    CollectionCreate,
    Document,
    DocumentQueryRequest,
    DocumentQueryResponse,
)
from ..services import (
    AttributeDescriberLLM,
    AttributeRankerLLM,
    DocumentParseError,
    EmptyDocumentError,
    UnsupportedDocumentType,
    describe_attributes,
    parse_document,
)


router = APIRouter(prefix="/collections", tags=["collections"])

_NUMERIC_REGEX_SQL = "^\\s*-?[0-9]+(?:\\.[0-9]+)?\\s*$"


@router.post("", response_model=Collection, status_code=201)
def create_collection(
    payload: CollectionCreate, db: Session = Depends(get_db)
) -> Collection:
    try:
        res = db.execute(
            text(
                "INSERT INTO tabular_collections (name) VALUES (:name) RETURNING id, name"
            ),
            {"name": payload.name},
        )
        row = res.fetchone()
        if row is None:
            db.rollback()
            raise HTTPException(status_code=500, detail="Failed to create collection")
        db.commit()
        return Collection(id=row.id, name=row.name)
    except Exception as exc:  # pragma: no cover - bubble-up unknown database errors
        db.rollback()
        msg = str(exc).lower()
        if "unique" in msg and "tabular_collections" in msg:
            raise HTTPException(
                status_code=409, detail="Collection name already exists"
            ) from exc
        raise


@router.get("", response_model=List[Collection])
def list_collections(db: Session = Depends(get_db)) -> List[Collection]:
    res = db.execute(text("SELECT id, name FROM tabular_collections ORDER BY name ASC"))
    return [Collection(id=row.id, name=row.name) for row in res.fetchall()]


@router.delete("/{collection_name}", status_code=204)
def delete_collection(collection_name: str, db: Session = Depends(get_db)) -> None:
    trimmed_name = collection_name.strip()
    if not trimmed_name:
        raise HTTPException(status_code=400, detail="Collection name is required")
    res = db.execute(
        text("DELETE FROM tabular_collections WHERE name = :name RETURNING id"),
        {"name": trimmed_name},
    )
    row = res.fetchone()
    if not row:
        db.rollback()
        raise HTTPException(status_code=404, detail="Collection not found")
    db.commit()
    return None


def get_attribute_describer_llm(request: Request) -> AttributeDescriberLLM:
    llm = getattr(request.app.state, "attribute_describer_llm", None)
    if llm is None:
        raise HTTPException(
            status_code=503, detail="Attribute description service is unavailable"
        )
    return llm


def get_attribute_ranker_llm(request: Request) -> AttributeRankerLLM:
    llm = getattr(request.app.state, "attribute_ranker_llm", None)
    if llm is None:
        raise HTTPException(
            status_code=503, detail="Attribute ranking service is unavailable"
        )
    return llm


@router.post("/{collection_name}/documents", response_model=Document, status_code=201)
async def add_document(
    collection_name: str,
    file: UploadFile = File(...),
    product_name: str = Form(...),
    language: str | None = Form(default=None),
    description: str | None = Form(default=None),
    db: Session = Depends(get_db),
    attribute_describer_llm: AttributeDescriberLLM = Depends(
        get_attribute_describer_llm
    ),
    attribute_ranker_llm: AttributeRankerLLM = Depends(get_attribute_ranker_llm),
) -> Document:
    trimmed_name = collection_name.strip()
    if not trimmed_name:
        raise HTTPException(status_code=400, detail="Collection name is required")

    collection_row = db.execute(
        text("SELECT id FROM tabular_collections WHERE name = :name"),
        {"name": trimmed_name},
    ).fetchone()
    if collection_row is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    trimmed_product = product_name.strip()
    if not trimmed_product:
        raise HTTPException(status_code=400, detail="Product name is required")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    file_name = file.filename or "uploaded_document"

    try:
        parsed = parse_document(file_name, content)
    except EmptyDocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnsupportedDocumentType as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DocumentParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    file_hash = sha256(content).hexdigest()

    df = pd.DataFrame(parsed.rows)
    inferred_schema = _infer_schema(df, parsed.columns)
    try:
        attribute_descriptions = describe_attributes(
            file_name=file_name,
            file_description=description or "",
            file_schema=inferred_schema,
            df=df,
            attribute_describer_llm=attribute_describer_llm,
            attribute_ranker_llm=attribute_ranker_llm,
        )
    except Exception as exc:  # pragma: no cover - defensive path
        logging.error("Failed to generate attribute descriptions: %s", exc)
        attribute_descriptions = {}

    try:
        product_insert = db.execute(
            text(
                """
                INSERT INTO tabular_products (collection_id, name)
                VALUES (:collection_id, :name)
                ON CONFLICT (collection_id, name) DO NOTHING
                RETURNING id
                """
            ),
            {"collection_id": collection_row.id, "name": trimmed_product},
        )
        product_id = product_insert.scalar_one_or_none()
        if product_id is None:
            product_id = db.execute(
                text(
                    """
                    SELECT id FROM tabular_products
                    WHERE collection_id = :collection_id AND name = :name
                    """
                ),
                {"collection_id": collection_row.id, "name": trimmed_product},
            ).scalar_one()

        document_id = db.execute(
            text(
                """
                INSERT INTO tabular_documents (
                    file_name,
                    file_hash,
                    language,
                    file_description,
                    file_schema,
                    attribute_descriptions
                )
                VALUES (:file_name, :file_hash, :language, :file_description, :file_schema, :attribute_descriptions)
                RETURNING id
                """
            ),
            {
                "file_name": file_name,
                "file_hash": file_hash,
                "language": language,
                "file_description": description,
                "file_schema": json.dumps(
                    {"columns": parsed.columns, "field_types": inferred_schema}
                ),
                "attribute_descriptions": json.dumps(
                    attribute_descriptions, default=_json_default
                ),
            },
        ).scalar_one()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Document already exists") from exc

    try:
        for row in parsed.rows:
            db.execute(
                text(
                    "INSERT INTO tabular_rows (file_id, attributes) VALUES (:file_id, :attributes)"
                ),
                {
                    "file_id": document_id,
                    "attributes": json.dumps(row, default=_json_default),
                },
            )

        db.execute(
            text(
                """
                INSERT INTO tabular_collection_entries (collection_id, product_id, file_name, document_id)
                VALUES (:collection_id, :product_id, :file_name, :document_id)
                """
            ),
            {
                "collection_id": collection_row.id,
                "product_id": product_id,
                "file_name": file_name,
                "document_id": document_id,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Document already registered for collection"
        ) from exc
    except Exception:
        db.rollback()
        raise

    return Document(
        id=document_id,
        file_name=file_name,
        collection=trimmed_name,
        product=trimmed_product,
        row_count=len(parsed.rows),
        columns=parsed.columns,
        attribute_descriptions=attribute_descriptions,
    )


@router.delete(
    "/{collection_name}/documents/{document_name}", status_code=204
)
def delete_document(
    collection_name: str,
    document_name: str,
    product_name: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> None:
    trimmed_collection = collection_name.strip()
    trimmed_document = document_name.strip()

    if not trimmed_collection or not trimmed_document:
        raise HTTPException(status_code=400, detail="Collection and document names are required")

    collection_row = db.execute(
        text("SELECT id FROM tabular_collections WHERE name = :name"),
        {"name": trimmed_collection},
    ).fetchone()
    if collection_row is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    product_param = None
    trimmed_product = product_name.strip() if product_name is not None else None

    if trimmed_product:
        product_row = db.execute(
            text(
                """
                SELECT id FROM tabular_products
                WHERE collection_id = :collection_id AND name = :product_name
                """
            ),
            {"collection_id": collection_row.id, "product_name": trimmed_product},
        ).fetchone()
        if product_row is None:
            raise HTTPException(status_code=404, detail="Product not found in collection")
        product_param = product_row.id
    else:
        product_rows = db.execute(
            text(
                """
                SELECT product_id FROM tabular_collection_entries
                WHERE collection_id = :collection_id AND file_name = :file_name
                """
            ),
            {"collection_id": collection_row.id, "file_name": trimmed_document},
        ).fetchall()
        if not product_rows:
            db.rollback()
            raise HTTPException(status_code=404, detail="Document not found in collection")
        if len(product_rows) > 1:
            raise HTTPException(
                status_code=409,
                detail="Multiple products reference this document; specify product_name",
            )
        product_param = product_rows[0].product_id
        trimmed_product = None

    mapping = db.execute(
        text(
            """
            DELETE FROM tabular_collection_entries
            WHERE collection_id = :collection_id
                AND file_name = :file_name
                AND product_id = :product_id
            RETURNING document_id, product_id
            """
        ),
        {
            "collection_id": collection_row.id,
            "file_name": trimmed_document,
            "product_id": product_param,
        },
    ).fetchone()

    if mapping is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Document not found in collection")

    try:
        remaining_link = db.execute(
            text(
                "SELECT 1 FROM tabular_collection_entries WHERE document_id = :document_id LIMIT 1"
            ),
            {"document_id": mapping.document_id},
        ).fetchone()

        if remaining_link is None:
            db.execute(
                text("DELETE FROM tabular_documents WHERE id = :document_id"),
                {"document_id": mapping.document_id},
            )

        product_link = db.execute(
            text(
                "SELECT 1 FROM tabular_collection_entries WHERE product_id = :product_id LIMIT 1"
            ),
            {"product_id": mapping.product_id},
        ).fetchone()

        if product_link is None:
            db.execute(
                text("DELETE FROM tabular_products WHERE id = :product_id"),
                {"product_id": mapping.product_id},
            )

        db.commit()
    except Exception:
        db.rollback()
        raise

    return None


@router.post(
    "/{collection_name}/products/{product_name}/query",
    response_model=DocumentQueryResponse,
)
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
            JOIN tabular_products p ON p.collection_id = c.id
            JOIN tabular_collection_entries e ON e.collection_id = c.id AND e.product_id = p.id
            JOIN tabular_documents d ON d.id = e.document_id
            WHERE c.name = :collection_name AND p.name = :product_name
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


def _infer_schema(df: pd.DataFrame, columns: List[str]) -> dict[str, str]:
    schema: dict[str, str] = {}
    for column in columns:
        if column not in df.columns:
            schema[column] = "TEXT"
            continue
        series = df[column].dropna()
        if series.empty:
            schema[column] = "TEXT"
            continue
        if series.isin([True, False]).all():
            schema[column] = "BOOLEAN"
            continue
        if pd.api.types.is_numeric_dtype(series):
            schema[column] = "NUMERIC"
        else:
            schema[column] = "TEXT"
    return schema


def _json_default(value):
    from decimal import Decimal

    if isinstance(value, Decimal):
        return float(value)
    return str(value)


__all__ = ["router"]
