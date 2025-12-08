import json
import logging
from typing import Any, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import Document, DocumentUpdate
from ..services import AttributeDescriberLLM, AttributeRankerLLM
from ..services.documents_service import (
    extract_file_extension,
    normalize_to_dict,
    get_collection_id,
    normalize_collection_name,
    parse_uploaded_documents,
    prepare_documents,
    read_uploaded_file,
    store_documents,
)
from ..security import require_api_key
from .llm_dependency_providers import (
    get_attribute_describer_llm,
    get_attribute_ranker_llm,
)

router = APIRouter(
    prefix="/collections/{collection_name}/documents",
    dependencies=[Depends(require_api_key)],
)

logger = logging.getLogger(__name__)
DEFAULT_STORAGE_TARGET = "pixie-tabular-db"


def _normalize_row_count(value: Any) -> int | None:
    """Convert row_count field into a non-negative integer when possible."""
    if value is None:
        return None
    try:
        count = int(value)
        return max(count, 0)
    except (TypeError, ValueError):
        return None


def _build_document(
    *,
    collection: str,
    document_id: int,
    file_name: str,
    product: str | None,
    row_count: Any,
    language: str | None,
    description: str | None,
    attribute_descriptions_raw: Any,
    file_schema_raw: Any,
    fallback_columns: List[str] | None = None,
    original_file_type: str | None = None,
) -> Document:
    """Create a Document response populated with defaults and derived fields."""
    file_schema = normalize_to_dict(file_schema_raw)
    columns = fallback_columns or []
    schema_columns = file_schema.get("columns") if isinstance(file_schema, dict) else None
    if isinstance(schema_columns, list):
        columns = schema_columns

    planned_storage_targets = []
    if isinstance(file_schema, dict):
        schema_planned = file_schema.get("planned_storage_targets")
        if isinstance(schema_planned, list):
            planned_storage_targets = schema_planned
    storage_target = (
        file_schema.get("storage_target") if isinstance(file_schema, dict) else None
    ) or DEFAULT_STORAGE_TARGET

    requires_preprocessing = False
    if isinstance(file_schema, dict):
        requires_preprocessing = bool(file_schema.get("requires_preprocessing", False))

    file_extension = None
    if isinstance(file_schema, dict):
        file_extension = file_schema.get("file_extension") or None
        if original_file_type is None:
            original_file_type = file_schema.get("original_file_type") or None
    if not file_extension:
        file_extension = extract_file_extension(file_name)

    attribute_descriptions = normalize_to_dict(attribute_descriptions_raw) or None

    return Document(
        id=document_id,
        file_name=file_name,
        collection=collection,
        storage_target=storage_target,
        planned_storage_targets=planned_storage_targets,
        file_extension=file_extension,
        original_file_type=original_file_type,
        product=product,
        row_count=_normalize_row_count(row_count),
        columns=columns,
        attribute_descriptions=attribute_descriptions,
        language=language,
        description=description,
        requires_preprocessing=requires_preprocessing,
    )


@router.post("", response_model=List[Document], status_code=201)
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
    """Store the uploaded file as one or more documents and return their metadata."""
    collection = normalize_collection_name(collection_name)
    collection_id = get_collection_id(db, collection)

    file_name, content = read_uploaded_file(file)
    parsed_documents = parse_uploaded_documents(file_name, content)
    logger.info(
        "Parsing upload '%s' for collection '%s' into %d document(s)",
        file_name,
        collection,
        len(parsed_documents),
    )

    prepared_documents = prepare_documents(
        file_name=file_name,
        content_type=file.content_type,
        file_content=content,
        parsed_documents=parsed_documents,
        product_prefix=product_prefix,
        description=description,
        language=language,
        attribute_describer_llm=attribute_describer_llm,
        attribute_ranker_llm=attribute_ranker_llm,
    )

    stored_results = store_documents(
        db=db,
        collection_id=collection_id,
        collection_name=collection,
        prepared_documents=prepared_documents,
    )
    logger.info(
        "Stored %d document(s) from upload '%s' in collection '%s'",
        len(stored_results),
        file_name,
        collection,
    )

    return [
        _build_document(
            collection=collection,
            document_id=db_result["id"],
            file_name=db_result["file_name"],
            product=db_result.get("product"),
            row_count=db_result.get("row_count"),
            language=db_result.get("language"),
            description=db_result.get("description"),
            attribute_descriptions_raw=db_result.get("attribute_descriptions"),
            file_schema_raw=db_result.get("file_schema"),
            fallback_columns=db_result.get("columns"),
            original_file_type=file.content_type or None,
        )
        for db_result in stored_results
    ]


@router.get("", response_model=List[Document])
def list_documents(
    collection_name: str,
    db: Session = Depends(get_db),
) -> List[Document]:
    trimmed_collection = normalize_collection_name(collection_name)
    collection_id = get_collection_id(db, trimmed_collection)

    rows = db.execute(
        text(
            """
            SELECT
                d.id,
                d.file_name,
                d.file_schema,
                d.attribute_descriptions,
                d.product_name,
                d.language,
                d.file_description,
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
        {"collection_id": collection_id},
    ).fetchall()

    return [
        _build_document(
            collection=trimmed_collection,
            document_id=row.id,
            file_name=row.file_name,
            product=row.product_name,
            row_count=row.row_count,
            language=row.language,
            description=row.file_description,
            attribute_descriptions_raw=row.attribute_descriptions,
            file_schema_raw=row.file_schema,
        )
        for row in rows
    ]


@router.patch("/{document_id}", response_model=Document)
def update_document(
    collection_name: str,
    document_id: int,
    update_request: DocumentUpdate,
    db: Session = Depends(get_db),
) -> Document:
    trimmed_collection = normalize_collection_name(collection_name)
    collection_id = get_collection_id(db, trimmed_collection)

    update_data = update_request.model_dump(exclude_unset=True)
    rank_updates = update_data.pop("attribute_ranks", None)
    if update_data.get("product") is None and "product" in update_data:
        raise HTTPException(status_code=400, detail="product may not be null")

    column_map = {
        "product": "product_name",
        "description": "file_description",
        "language": "language",
    }
    set_clauses: List[str] = []
    parameters: dict[str, object] = {
        "document_id": document_id,
        "collection_id": collection_id,
    }

    for field_name, value in update_data.items():
        column_name = column_map.get(field_name)
        if column_name is None:
            continue
        param_name = f"value_{field_name}"
        set_clauses.append(f"{column_name} = :{param_name}")
        parameters[param_name] = value

    try:
        if rank_updates:
            current_row = db.execute(
                text(
                    """
                    SELECT attribute_descriptions
                    FROM tabular_documents
                    WHERE id = :document_id AND collection_id = :collection_id
                    FOR UPDATE
                    """
                ),
                {
                    "document_id": document_id,
                    "collection_id": collection_id,
                },
            ).fetchone()
            if current_row is None:
                raise HTTPException(
                    status_code=404, detail="Document not found in collection"
                )

            attribute_descriptions = normalize_to_dict(
                current_row.attribute_descriptions
            )
            if not attribute_descriptions:
                raise HTTPException(
                    status_code=400,
                    detail="Document has no attribute descriptions to update",
                )

            for attribute_name, rank in rank_updates.items():
                details = attribute_descriptions.get(attribute_name)
                if not isinstance(details, dict):
                    raise HTTPException(
                        status_code=404,
                        detail=f"Attribute '{attribute_name}' not found in document",
                    )
                details["rank"] = rank

            parameters["attribute_descriptions"] = json.dumps(attribute_descriptions)
            set_clauses.append("attribute_descriptions = :attribute_descriptions")

        if not set_clauses:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        update_stmt = text(
            f"""
            UPDATE tabular_documents
            SET {', '.join(set_clauses)}
            WHERE id = :document_id AND collection_id = :collection_id
            RETURNING
                id,
                file_name,
                product_name,
                language,
                file_description,
                file_schema,
                attribute_descriptions,
                (
                    SELECT COUNT(*)
                    FROM tabular_rows r
                    WHERE r.file_id = tabular_documents.id
                ) AS row_count
            """
        )

        row = db.execute(update_stmt, parameters).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404, detail="Document not found in collection"
            )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        msg = str(exc).lower()
        if (
            "tabular_documents" in msg
            or "collection_id" in msg
            or "product_name" in msg
        ):
            raise HTTPException(
                status_code=409,
                detail="Product already has a document in this collection",
            ) from exc
        raise
    except Exception:
        db.rollback()
        raise

    return _build_document(
        collection=trimmed_collection,
        document_id=row.id,
        file_name=row.file_name,
        product=row.product_name,
        row_count=row.row_count,
        language=row.language,
        description=row.file_description,
        attribute_descriptions_raw=row.attribute_descriptions,
        file_schema_raw=row.file_schema,
    )


@router.delete("/{document_id}", status_code=204)
def delete_document(
    collection_name: str,
    document_id: int,
    db: Session = Depends(get_db),
) -> None:
    trimmed_collection = normalize_collection_name(collection_name)
    collection_id = get_collection_id(db, trimmed_collection)

    deleted_row = db.execute(
        text(
            """
            DELETE FROM tabular_documents
            WHERE collection_id = :collection_id AND id = :document_id
            RETURNING id
            """
        ),
        {
            "collection_id": collection_id,
            "document_id": document_id,
        },
    ).fetchone()

    if deleted_row is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Document not found in collection")

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info(
        "Deleted document '%s' from collection '%s'", document_id, trimmed_collection
    )


__all__ = [
    "add_document",
    "delete_document",
    "list_documents",
    "update_document",
    "router",
]
