from fastapi import APIRouter, Depends

from ..security import require_api_key
from .health_router import router as health_router
from .collections_router import router as collections_router
from .documents_router import router as documents_router
from .queries_router import router as queries_router

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
    "health_router",
]
