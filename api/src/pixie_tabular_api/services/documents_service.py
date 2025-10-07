"""Service helpers for document ingestion and parsing."""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Dict, List, Sequence

import pandas as pd
from fastapi import HTTPException, UploadFile
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .attribute_describer import describe_attributes
from .llms import AttributeDescriberLLM, AttributeRankerLLM

logger = logging.getLogger(__name__)


class DocumentParseError(Exception):
    """Base class for document parsing issues."""


class UnsupportedDocumentType(DocumentParseError):
    """Raised when the uploaded document type is not supported."""


class EmptyDocumentError(DocumentParseError):
    """Raised when the uploaded document does not contain data rows."""


@dataclass(slots=True)
class ParsedDocument:
    source_name: str
    columns: List[str]
    rows: List[dict[str, Any]]


def parse_document(file_name: str, content: bytes) -> List[ParsedDocument]:
    """Parse CSV or XLSX content into document objects."""

    lowered = file_name.lower()
    if lowered.endswith(".csv"):
        return [_parse_csv(file_name, content)]
    if lowered.endswith(".xlsx"):
        return _parse_xlsx(content)
    raise UnsupportedDocumentType("Only .csv and .xlsx files are supported at this stage")


def _parse_csv(file_name: str, content: bytes) -> ParsedDocument:
    try:
        text_stream = io.StringIO(content.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:  # pragma: no cover - depends on input file
        raise DocumentParseError("CSV file must be UTF-8 encoded") from exc

    reader = csv.DictReader(text_stream)
    if reader.fieldnames is None:
        raise EmptyDocumentError("CSV file is missing a header row")

    rows: List[dict[str, Any]] = []
    for raw_row in reader:
        row_dict = {field: raw_row.get(field) for field in reader.fieldnames}
        if all(value in (None, "") for value in row_dict.values()):
            continue
        rows.append(row_dict)

    if not rows:
        raise EmptyDocumentError("CSV file does not contain any data rows")

    base_name = file_name.rsplit("/", maxsplit=1)[-1]
    return ParsedDocument(
        source_name=base_name,
        columns=[field for field in reader.fieldnames],
        rows=rows,
    )


def _parse_xlsx(content: bytes) -> List[ParsedDocument]:
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except InvalidFileException as exc:
        raise DocumentParseError("XLSX file is invalid or corrupted") from exc

    parsed_sheets: List[ParsedDocument] = []

    try:
        for sheet in workbook.worksheets:
            if sheet is None:
                continue

            sheet_title = (sheet.title or "Sheet").strip() or "Sheet"
            rows_iter = sheet.iter_rows(values_only=True)

            try:
                header_row = next(rows_iter)
            except StopIteration:
                logging.info("Skipping empty sheet '%s'", sheet_title)
                continue

            columns: List[str] = []
            column_indexes: List[int] = []
            for idx, cell in enumerate(header_row):
                if cell is None:
                    continue
                column_name = str(cell).strip()
                if not column_name:
                    continue
                columns.append(column_name)
                column_indexes.append(idx)

            if not columns:
                logging.info("Skipping sheet '%s' without column names", sheet_title)
                continue

            rows: List[dict[str, Any]] = []
            for row in rows_iter:
                row_dict = {
                    columns[pos]: (
                        row[column_indexes[pos]] if column_indexes[pos] < len(row) else None
                    )
                    for pos in range(len(columns))
                }
                if all(value in (None, "") for value in row_dict.values()):
                    continue
                rows.append(row_dict)

            if not rows:
                logging.info("Skipping sheet '%s' without data rows", sheet_title)
                continue

            parsed_sheets.append(
                ParsedDocument(source_name=sheet_title, columns=columns, rows=rows)
            )
    finally:
        workbook.close()

    if not parsed_sheets:
        raise EmptyDocumentError("XLSX workbook does not contain any usable sheets")

    return parsed_sheets


@dataclass(slots=True)
class PreparedDocument:
    """Normalized document payload ready for database insertion."""

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


def normalize_collection_name(collection_name: str) -> str:
    """Trim whitespace and ensure a collection name is present."""

    trimmed = collection_name.strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Collection name is required")
    return trimmed


def get_collection_id(db: Session, collection_name: str) -> int:
    """Fetch the collection identifier or raise when the collection is unknown."""

    collection_row = db.execute(
        text("SELECT id FROM tabular_collections WHERE name = :name"),
        {"name": collection_name},
    ).fetchone()
    if collection_row is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection_row.id


def read_uploaded_file(file: UploadFile) -> tuple[str, bytes]:
    """Read the in-memory upload and enforce non-empty content."""

    file.file.seek(0)
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    file_name = file.filename or "uploaded_document"
    return file_name, content


def parse_uploaded_documents(file_name: str, content: bytes) -> List[ParsedDocument]:
    """Convert binary file content into parsed document structures."""

    try:
        return parse_document(file_name, content)
    except EmptyDocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnsupportedDocumentType as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DocumentParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def prepare_documents(
    *,
    file_name: str,
    file_content: bytes,
    parsed_documents: Sequence[ParsedDocument],
    product_prefix: str | None,
    description: str | None,
    language: str | None,
    attribute_describer_llm: AttributeDescriberLLM,
    attribute_ranker_llm: AttributeRankerLLM,
) -> List[PreparedDocument]:
    """Assemble per-document metadata, including schema inference and LLM output."""

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
        product_name = resolve_product_name(product_prefix, default_name, index)

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
        inferred_schema = infer_schema(df, list(parsed_document.columns))
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
            logger.error(
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
                rows=list(parsed_document.rows),
            )
        )

    return prepared_documents


def resolve_product_name(
    product_prefix: str | None, default_name: str, index: int
) -> str:
    """Derive the product name for the current sheet using the provided prefix."""

    if product_prefix and product_prefix.strip():
        return f"{product_prefix.strip()} {index}"
    return default_name


def store_documents(
    *,
    db: Session,
    collection_id: int,
    collection_name: str,
    prepared_documents: Sequence[PreparedDocument],
) -> List[Dict[str, Any]]:
    """Persist prepared documents and return the raw database payload."""

    stored_documents: List[Dict[str, Any]] = []

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
                        prepared.attribute_descriptions, default=json_default
                    ),
                },
            ).scalar_one()

            bulk_insert_rows(db, document_id, prepared.rows)

            stored_documents.append(
                {
                    "id": document_id,
                    "file_name": prepared.file_name,
                    "collection": collection_name,
                    "product": prepared.product_name,
                    "row_count": len(prepared.rows),
                    "columns": prepared.columns,
                    "attribute_descriptions": prepared.attribute_descriptions,
                }
            )

        db.commit()
    except IntegrityError as exc:
        db.rollback()
        msg = str(exc).lower()
        logger.warning(
            "Constraint violation while storing document(s) for collection '%s': %s",
            collection_name,
            exc,
        )
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
        logger.exception(
            "Unexpected error while storing document(s) for collection '%s'",
            collection_name,
        )
        raise

    return stored_documents


def bulk_insert_rows(db: Session, document_id: int, rows: Sequence[dict[str, Any]]) -> None:
    """Insert document rows in a single statement for efficiency."""

    if not rows:
        return

    insert_stmt = text(
        "INSERT INTO tabular_rows (file_id, attributes) VALUES (:file_id, :attributes)"
    )
    parameters = [
        {
            "file_id": document_id,
            "attributes": json.dumps(row, default=json_default),
        }
        for row in rows
    ]

    db.execute(insert_stmt, parameters)


def ensure_json_dict(value: Any) -> Dict[str, Any]:
    """Best-effort conversion from JSONB/str payload to a dictionary."""

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


def infer_schema(df: pd.DataFrame, columns: Sequence[str]) -> dict[str, str]:
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


def json_default(value: Any):
    from decimal import Decimal

    if isinstance(value, Decimal):
        return float(value)
    return str(value)


__all__ = [
    "DocumentParseError",
    "EmptyDocumentError",
    "ParsedDocument",
    "PreparedDocument",
    "UnsupportedDocumentType",
    "bulk_insert_rows",
    "ensure_json_dict",
    "get_collection_id",
    "infer_schema",
    "json_default",
    "normalize_collection_name",
    "parse_document",
    "parse_uploaded_documents",
    "prepare_documents",
    "read_uploaded_file",
    "resolve_product_name",
    "store_documents",
]
