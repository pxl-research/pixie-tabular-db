import json
import logging
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Dict, List

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
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
    ParsedDocument,
    UnsupportedDocumentType,
    describe_attributes,
    parse_document,
)
from .dependencies import get_attribute_describer_llm, get_attribute_ranker_llm

router = APIRouter()


@dataclass(slots=True)
class PreparedDocument:
    file_name: str
    file_hash: str
    product_name: str
    language: str | None
    file_description: str | None
    columns: List[str]
    field_types: Dict[str, str]
    attribute_descriptions: Dict[str, Any]
    rows: List[dict[str, Any]]

    def schema_payload(self) -> Dict[str, Any]:
        return {"columns": self.columns, "field_types": self.field_types}


@router.post("/", response_model=List[Document], status_code=201)
def add_document(
    collection_name: str,
    file: UploadFile = File(...),
    product_prefix: str | None = Form(default=None),
    language: str | None = Form(default=None),
    description: str | None = Form(default=None),
    db: Session = Depends(get_db),
    attribute_describer_llm: AttributeDescriberLLM = Depends(
        get_attribute_describer_llm
    ),
    attribute_ranker_llm: AttributeRankerLLM = Depends(get_attribute_ranker_llm),
) -> List[Document]:
    collection = _normalize_collection_name(collection_name)
    collection_id = _get_collection_id(db, collection)

    file_name, content = _read_uploaded_file(file)
    parsed_documents = _parse_uploaded_documents(file_name, content)

    prepared_documents = _prepare_documents(
        file_name=file_name,
        file_content=content,
        parsed_documents=parsed_documents,
        product_prefix=product_prefix,
        description=description,
        language=language,
        attribute_describer_llm=attribute_describer_llm,
        attribute_ranker_llm=attribute_ranker_llm,
    )

    return _store_documents(
        db=db,
        collection_id=collection_id,
        collection_name=collection,
        prepared_documents=prepared_documents,
    )


def _normalize_collection_name(collection_name: str) -> str:
    trimmed_name = collection_name.strip()
    if not trimmed_name:
        raise HTTPException(status_code=400, detail="Collection name is required")
    return trimmed_name


def _get_collection_id(db: Session, collection_name: str) -> int:
    collection_row = db.execute(
        text("SELECT id FROM tabular_collections WHERE name = :name"),
        {"name": collection_name},
    ).fetchone()
    if collection_row is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection_row.id


def _read_uploaded_file(file: UploadFile) -> tuple[str, bytes]:
    file.file.seek(0)
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    file_name = file.filename or "uploaded_document"
    return file_name, content


def _parse_uploaded_documents(file_name: str, content: bytes) -> List[ParsedDocument]:
    try:
        return parse_document(file_name, content)
    except EmptyDocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnsupportedDocumentType as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DocumentParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _prepare_documents(
    *,
    file_name: str,
    file_content: bytes,
    parsed_documents: List[ParsedDocument],
    product_prefix: str | None,
    description: str | None,
    language: str | None,
    attribute_describer_llm: AttributeDescriberLLM,
    attribute_ranker_llm: AttributeRankerLLM,
) -> List[PreparedDocument]:
    base_hash = sha256(file_content).hexdigest()
    multi_sheet = len(parsed_documents) > 1
    seen_products: set[str] = set()
    sheet_description = (
        description.strip() if description and description.strip() else None
    )

    prepared_documents: List[PreparedDocument] = []

    for index, parsed_document in enumerate(parsed_documents, start=1):
        source_name = getattr(parsed_document, "source_name", None)
        default_name = source_name or f"Sheet {index}"
        product_name = _resolve_product_name(product_prefix, default_name, index)

        if not product_name:
            raise HTTPException(status_code=400, detail="Product name is required")
        if product_name in seen_products:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate product name '{product_name}' in upload",
            )
        seen_products.add(product_name)

        sheet_hash = (
            base_hash
            if not multi_sheet
            else sha256(f"{base_hash}:{product_name}".encode("utf-8")).hexdigest()
        )

        df = pd.DataFrame(parsed_document.rows)
        inferred_schema = _infer_schema(df, parsed_document.columns)
        llm_table_name = file_name if not multi_sheet else f"{file_name}::{product_name}"

        try:
            attribute_descriptions = describe_attributes(
                file_name=llm_table_name,
                file_description=sheet_description or "",
                file_schema=inferred_schema,
                df=df,
                attribute_describer_llm=attribute_describer_llm,
                attribute_ranker_llm=attribute_ranker_llm,
            )
        except Exception as exc:  # pragma: no cover - defensive path
            logging.error(
                "Failed to generate attribute descriptions for product '%s': %s",
                product_name,
                exc,
            )
            attribute_descriptions = {}

        prepared_documents.append(
            PreparedDocument(
                file_name=file_name,
                file_hash=sheet_hash,
                product_name=product_name,
                language=language,
                file_description=sheet_description,
                columns=list(parsed_document.columns),
                field_types=inferred_schema,
                attribute_descriptions=attribute_descriptions,
                rows=parsed_document.rows,
            )
        )

    return prepared_documents


def _resolve_product_name(
    product_prefix: str | None, default_name: str, index: int
) -> str:
    if product_prefix and product_prefix.strip():
        return f"{product_prefix.strip()} {index}"
    return default_name


def _store_documents(
    *,
    db: Session,
    collection_id: int,
    collection_name: str,
    prepared_documents: List[PreparedDocument],
) -> List[Document]:
    documents_response: List[Document] = []

    try:
        for prepared in prepared_documents:
            document_id = db.execute(
                text(
                    """
                    INSERT INTO tabular_documents (
                        collection_id,
                        product_name,
                        file_name,
                        file_hash,
                        language,
                        file_description,
                        file_schema,
                        attribute_descriptions
                    )
                    VALUES (
                        :collection_id,
                        :product_name,
                        :file_name,
                        :file_hash,
                        :language,
                        :file_description,
                        :file_schema,
                        :attribute_descriptions
                    )
                    RETURNING id
                    """
                ),
                {
                    "collection_id": collection_id,
                    "product_name": prepared.product_name,
                    "file_name": prepared.file_name,
                    "file_hash": prepared.file_hash,
                    "language": prepared.language,
                    "file_description": prepared.file_description,
                    "file_schema": json.dumps(prepared.schema_payload()),
                    "attribute_descriptions": json.dumps(
                        prepared.attribute_descriptions, default=_json_default
                    ),
                },
            ).scalar_one()

            _bulk_insert_rows(db, document_id, prepared.rows)

            documents_response.append(
                Document(
                    id=document_id,
                    file_name=prepared.file_name,
                    collection=collection_name,
                    product=prepared.product_name,
                    row_count=len(prepared.rows),
                    columns=prepared.columns,
                    attribute_descriptions=prepared.attribute_descriptions,
                )
            )

        db.commit()
    except IntegrityError as exc:
        db.rollback()
        msg = str(exc).lower()
        if "tabular_documents" in msg or "collection_id" in msg:
            raise HTTPException(
                status_code=409,
                detail="Product already has a document in this collection",
            ) from exc
        if "file_hash" in msg:
            raise HTTPException(
                status_code=409, detail="Document already exists"
            ) from exc
        raise
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return documents_response


@router.get("/", response_model=List[Document])
def list_documents(
    collection_name: str,
    db: Session = Depends(get_db),
) -> List[Document]:
    trimmed_collection = collection_name.strip()
    if not trimmed_collection:
        raise HTTPException(status_code=400, detail="Collection name is required")

    collection_row = db.execute(
        text("SELECT id FROM tabular_collections WHERE name = :name"),
        {"name": trimmed_collection},
    ).fetchone()

    if collection_row is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    rows = db.execute(
        text(
            """
            SELECT
                d.id,
                d.file_name,
                d.file_schema,
                d.attribute_descriptions,
                d.product_name,
                (
                    SELECT COUNT(*)
                    FROM tabular_rows r
                    WHERE r.file_id = d.id
                ) AS row_count
            FROM tabular_documents d
            WHERE d.collection_id = :collection_id
            ORDER BY d.product_name ASC, d.file_name ASC
            """
        ),
        {"collection_id": collection_row.id},
    ).fetchall()

    documents: List[Document] = []
    for row in rows:
        file_schema = _ensure_json_dict(row.file_schema)
        attribute_descriptions = _ensure_json_dict(row.attribute_descriptions)
        columns = file_schema.get("columns")
        if not isinstance(columns, list):
            columns = []

        row_count = row.row_count
        try:
            row_count_int = int(row_count)
        except (TypeError, ValueError):
            row_count_int = 0

        documents.append(
            Document(
                id=row.id,
                file_name=row.file_name,
                collection=trimmed_collection,
                product=row.product_name,
                row_count=row_count_int,
                columns=columns,
                attribute_descriptions=attribute_descriptions or None,
            )
        )

    return documents


@router.delete("/{identifier}", status_code=204)
def delete_document(
    collection_name: str,
    identifier: str,
    db: Session = Depends(get_db),
) -> None:
    trimmed_collection = collection_name.strip()
    trimmed_identifier = identifier.strip()

    if not trimmed_collection or not trimmed_identifier:
        raise HTTPException(
            status_code=400, detail="Collection and identifier are required"
        )

    collection_row = db.execute(
        text("SELECT id FROM tabular_collections WHERE name = :name"),
        {"name": trimmed_collection},
    ).fetchone()
    if collection_row is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Attempt full upload deletion by matching file name first
    file_match = db.execute(
        text(
            """
            SELECT id
            FROM tabular_documents
            WHERE collection_id = :collection_id AND file_name = :file_name
            """
        ),
        {"collection_id": collection_row.id, "file_name": trimmed_identifier},
    ).fetchall()

    if file_match:
        try:
            db.execute(
                text(
                    """
                    DELETE FROM tabular_documents
                    WHERE collection_id = :collection_id AND file_name = :file_name
                    """
                ),
                {"collection_id": collection_row.id, "file_name": trimmed_identifier},
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        return None

    # Fall back to deleting by product name
    mapping = db.execute(
        text(
            """
            DELETE FROM tabular_documents
            WHERE collection_id = :collection_id AND product_name = :product_name
            RETURNING id
            """
        ),
        {
            "collection_id": collection_row.id,
            "product_name": trimmed_identifier,
        },
    ).fetchone()

    if mapping is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Document not found in collection")

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

def _ensure_json_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, dict):
                return decoded
        except json.JSONDecodeError:
            return {}
    return {}


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
