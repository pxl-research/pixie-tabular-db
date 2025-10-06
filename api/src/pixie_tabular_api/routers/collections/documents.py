import json
import logging
from hashlib import sha256
from typing import Any, List

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...database import get_db
from ...schemas import Document
from ...services import (
    AttributeDescriberLLM,
    AttributeRankerLLM,
    DocumentParseError,
    EmptyDocumentError,
    UnsupportedDocumentType,
    describe_attributes,
    parse_document,
)
from .dependencies import get_attribute_describer_llm, get_attribute_ranker_llm

router = APIRouter()


@router.post("/", response_model=Document, status_code=201)
def add_document(
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

    file.file.seek(0)
    content = file.file.read()
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
        _bulk_insert_rows(db, document_id, parsed.rows)

        db.execute(
            text(
                """
                INSERT INTO tabular_collection_entries (collection_id, product_name, file_name, document_id)
                VALUES (:collection_id, :product_name, :file_name, :document_id)
                """
            ),
            {
                "collection_id": collection_row.id,
                "product_name": trimmed_product,
                "file_name": file_name,
                "document_id": document_id,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        msg = str(exc).lower()
        if "tabular_collection_entries" in msg:
            raise HTTPException(
                status_code=409,
                detail="Product already has a document in this collection",
            ) from exc
        raise
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


@router.delete("/{document_name}", status_code=204)
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

    target_product: str | None = None

    if product_name is not None:
        trimmed_product = product_name.strip()
        if not trimmed_product:
            raise HTTPException(status_code=400, detail="Product name cannot be empty")
        target_product = trimmed_product
    else:
        product_rows = db.execute(
            text(
                """
                SELECT product_name FROM tabular_collection_entries
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
        target_product = product_rows[0].product_name

    mapping = db.execute(
        text(
            """
            DELETE FROM tabular_collection_entries
            WHERE collection_id = :collection_id
                AND file_name = :file_name
                AND product_name = :product_name
            RETURNING document_id, product_name
            """
        ),
        {
            "collection_id": collection_row.id,
            "file_name": trimmed_document,
            "product_name": target_product,
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

        db.commit()
    except Exception:
        db.rollback()
        raise

    return None


def _bulk_insert_rows(db: Session, document_id: int, rows: List[dict[str, Any]]) -> None:
    if not rows:
        return

    insert_stmt = text(
        "INSERT INTO tabular_rows (file_id, attributes) VALUES (:file_id, :attributes)"
    )
    parameters = [
        {
            "file_id": document_id,
            "attributes": json.dumps(row, default=_json_default),
        }
        for row in rows
    ]

    db.execute(insert_stmt, parameters)


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


__all__ = [
    "add_document",
    "delete_document",
    "router",
]
