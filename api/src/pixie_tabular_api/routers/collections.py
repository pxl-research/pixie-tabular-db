from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import Collection, CollectionCreate
from ..services.collection_management import (
    create_collection as create_collection_service,
    delete_collection as delete_collection_service,
    list_collections as list_collections_service,
)

router = APIRouter()


@router.post("/", response_model=Collection, status_code=201)
def create_collection(
    payload: CollectionCreate, db: Session = Depends(get_db)
) -> Collection:
    return create_collection_service(db=db, payload=payload)


@router.get("/", response_model=List[Collection])
def list_collections(db: Session = Depends(get_db)) -> List[Collection]:
    return list_collections_service(db=db)


@router.delete("/{collection_name}", status_code=204)
def delete_collection(collection_name: str, db: Session = Depends(get_db)) -> None:
    delete_collection_service(db=db, collection_name=collection_name)


__all__ = [
    "create_collection",
    "list_collections",
    "delete_collection",
    "router",
]
