from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import DocumentQueryRequest, DocumentQueryResponse
from ..services.queries_service import execute_document_query

router = APIRouter()


@router.post("/{product_name}/query", response_model=DocumentQueryResponse)
def query_document_rows(
    collection_name: str,
    product_name: str,
    payload: DocumentQueryRequest,
    db: Session = Depends(get_db),
) -> DocumentQueryResponse:
    return execute_document_query(
        db=db,
        collection_name=collection_name,
        product_name=product_name,
        request=payload,
    )


__all__ = [
    "query_document_rows",
    "router",
]
