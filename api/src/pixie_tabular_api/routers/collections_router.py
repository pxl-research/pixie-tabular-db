from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import Collection, CollectionCreate
from ..security import require_api_key
from ..services.collections_service import (
    create_collection as create_collection_service,
    delete_collection as delete_collection_service,
    list_collections as list_collections_service,
)

router = APIRouter(
    prefix="/collections",
    dependencies=[Depends(require_api_key)],
)


@router.post("", response_model=Collection, status_code=201)
def create_collection(
    create_request: CollectionCreate, db: Session = Depends(get_db)
) -> Collection:
    """Create a new collection with the given name."""
    return create_collection_service(db=db, create_request=create_request)


@router.get("", response_model=List[Collection])
def list_collections(db: Session = Depends(get_db)) -> List[Collection]:
    """List all available collections with their document counts."""
    return list_collections_service(db=db)


@router.delete("/{collection_name}", status_code=204)
def delete_collection(collection_name: str, db: Session = Depends(get_db)) -> None:
    """Delete a collection and all its associated documents."""
    delete_collection_service(db=db, collection_name=collection_name)


__all__ = [
    "create_collection",
    "list_collections",
    "delete_collection",
    "router",
]
