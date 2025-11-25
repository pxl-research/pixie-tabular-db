from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import DocumentQueryRequest, DocumentQueryResponse
from ..services.queries_service import execute_document_query
from ..security import require_api_key

router = APIRouter(
    prefix="/collections/{collection_name}/products",
    dependencies=[Depends(require_api_key)],
)


@router.post("/{product_name}/query", response_model=DocumentQueryResponse)
def query_document_rows(
    collection_name: str,
    product_name: str,
    query_request: DocumentQueryRequest,
    db: Session = Depends(get_db),
) -> DocumentQueryResponse:
    """
    Query document rows for a specific product with optional filters.

    Supports exact value matching and range filters for numeric attributes.
    """
    return execute_document_query(
        db=db,
        collection_name=collection_name,
        product_name=product_name,
        request=query_request,
    )


__all__ = [
    "query_document_rows",
    "router",
]
