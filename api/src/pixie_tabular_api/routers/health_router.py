from fastapi import APIRouter
from sqlalchemy import text

from ..database import engine


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


__all__ = ["router"]
