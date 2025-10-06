from fastapi import APIRouter, Depends

from .collections import router as _collections_router
from .documents import router as _documents_router
from .queries import router as _queries_router
from ...security import require_api_key

router = APIRouter(
    prefix="/collections",
    tags=["collections"],
    dependencies=[Depends(require_api_key)],
)
router.include_router(_collections_router)
router.include_router(_documents_router, prefix="/{collection_name}/documents")
router.include_router(_queries_router, prefix="/{collection_name}/products")

__all__ = ["router"]
