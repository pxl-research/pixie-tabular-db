from fastapi import APIRouter, Depends

from ..security import require_api_key
from .collections import router as collections_router
from .documents import router as documents_router
from .queries import router as queries_router

router = APIRouter(
    prefix="/collections",
    tags=["collections"],
    dependencies=[Depends(require_api_key)],
)
router.include_router(collections_router)
router.include_router(documents_router, prefix="/{collection_name}/documents")
router.include_router(queries_router, prefix="/{collection_name}/products")

__all__ = ["router"]
