from fastapi import APIRouter
from .health_router import router as health_router
from .collections_router import router as collections_router
from .documents_router import router as documents_router
from .queries_router import router as queries_router

collections_main_router = APIRouter(
    tags=["collections"],
)
collections_main_router.include_router(collections_router)
collections_main_router.include_router(documents_router)
collections_main_router.include_router(queries_router)


__all__ = [
    "collections_main_router",
    "health_router",
]
