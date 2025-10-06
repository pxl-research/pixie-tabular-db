from fastapi import APIRouter

from .collections_crud import router as _collections_crud_router
from .documents import router as _documents_router
from .queries import router as _queries_router

router = APIRouter(prefix="/collections", tags=["collections"])
router.include_router(_collections_crud_router)
router.include_router(_documents_router, prefix="/{collection_name}/documents")
router.include_router(_queries_router, prefix="/{collection_name}/products")

__all__ = ["router"]
