from fastapi import APIRouter, Depends

from ..security import require_api_key
from . import health
from .collections import router as collections_router
from .documents import router as documents_router
from .queries import router as queries_router

collections_api = APIRouter(
    prefix="/collections",
    tags=["collections"],
    dependencies=[Depends(require_api_key)],
)
collections_api.include_router(collections_router)
collections_api.include_router(documents_router, prefix="/{collection_name}/documents")
collections_api.include_router(queries_router, prefix="/{collection_name}/products")


__all__ = [
    "collections_api",
    "health",
]
