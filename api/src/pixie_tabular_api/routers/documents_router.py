import logging
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import Document, DocumentUpdate
from ..services import AttributeDescriberLLM, AttributeRankerLLM
from ..services.documents_service import (
    ensure_json_dict,
    get_collection_id,
    normalize_collection_name,
    parse_uploaded_documents,
    prepare_documents,
    read_uploaded_file,
    store_documents,
)
from .llm_dependency_providers import (
    get_attribute_describer_llm,
    get_attribute_ranker_llm,
)

router = APIRouter()

logger = logging.getLogger(__name__)


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
        file_content=content,
        parsed_documents=parsed_documents,
        product_prefix=product_prefix,
        description=description,
        language=language,
        attribute_describer_llm=attribute_describer_llm,
        attribute_ranker_llm=attribute_ranker_llm,
    )

    stored_payloads = store_documents(
        db=db,
        collection_id=collection_id,
        collection_name=collection,
        prepared_documents=prepared_documents,
    )
    logger.info(
        "Stored %d document(s) from upload '%s' in collection '%s'",
        len(stored_payloads),
        file_name,
        collection,
    )

    return [Document(**payload) for payload in stored_payloads]


@router.get("/", response_model=List[Document])
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

    documents: List[Document] = []
    for row in rows:
        file_schema = ensure_json_dict(row.file_schema)
        attribute_descriptions = ensure_json_dict(row.attribute_descriptions)
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
                language=row.language,
                description=row.file_description,
            )
        )

    return documents


@router.patch("/{document_id}", response_model=Document)
def update_document(
    collection_name: str,
    document_id: int,
    payload: DocumentUpdate,
    db: Session = Depends(get_db),
) -> Document:
    trimmed_collection = normalize_collection_name(collection_name)
    collection_id = get_collection_id(db, trimmed_collection)

    update_payload = payload.model_dump(exclude_unset=True)
    if not update_payload:
        raise HTTPException(status_code=400, detail="At least one field must be provided")

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

    for field_name, value in update_payload.items():
        column_name = column_map.get(field_name)
        if column_name is None:
            continue
        param_name = f"value_{field_name}"
        set_clauses.append(f"{column_name} = :{param_name}")
        parameters[param_name] = value

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

    try:
        row = db.execute(update_stmt, parameters).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found in collection")
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        msg = str(exc).lower()
        if "tabular_documents" in msg or "collection_id" in msg or "product_name" in msg:
            raise HTTPException(
                status_code=409,
                detail="Product already has a document in this collection",
            ) from exc
        raise
    except Exception:
        db.rollback()
        raise

    file_schema = ensure_json_dict(row.file_schema)
    attribute_descriptions = ensure_json_dict(row.attribute_descriptions)
    columns = file_schema.get("columns")
    if not isinstance(columns, list):
        columns = []

    row_count = row.row_count
    try:
        row_count_int = int(row_count)
    except (TypeError, ValueError):
        row_count_int = 0

    return Document(
        id=row.id,
        file_name=row.file_name,
        collection=trimmed_collection,
        product=row.product_name,
        row_count=row_count_int,
        columns=columns,
        attribute_descriptions=attribute_descriptions or None,
        language=row.language,
        description=row.file_description,
    )


@router.delete("/{identifier}", status_code=204)
def delete_document(
    collection_name: str,
    identifier: str,
    db: Session = Depends(get_db),
) -> None:
    trimmed_collection = normalize_collection_name(collection_name)
    trimmed_identifier = identifier.strip()

    if not trimmed_identifier:
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
        logger.info(
            "Deleted document(s) for collection '%s' via file identifier '%s'",
            trimmed_collection,
            trimmed_identifier,
        )
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
    logger.info(
        "Deleted document(s) for collection '%s' via product identifier '%s'",
        trimmed_collection,
        trimmed_identifier,
    )


__all__ = [
    "add_document",
    "delete_document",
    "list_documents",
    "update_document",
    "router",
]
