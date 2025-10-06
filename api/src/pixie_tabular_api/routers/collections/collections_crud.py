from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...database import get_db
from ...schemas import Collection, CollectionCreate

router = APIRouter()


@router.post("", response_model=Collection, status_code=201)
def create_collection(
    payload: CollectionCreate, db: Session = Depends(get_db)
) -> Collection:
    try:
        res = db.execute(
            text(
                "INSERT INTO tabular_collections (name) VALUES (:name) RETURNING id, name"
            ),
            {"name": payload.name},
        )
        row = res.fetchone()
        if row is None:
            db.rollback()
            raise HTTPException(status_code=500, detail="Failed to create collection")
        db.commit()
        return Collection(id=row.id, name=row.name)
    except Exception as exc:  # pragma: no cover - bubble-up unknown database errors
        db.rollback()
        msg = str(exc).lower()
        if "unique" in msg and "tabular_collections" in msg:
            raise HTTPException(
                status_code=409, detail="Collection name already exists"
            ) from exc
        raise


@router.get("", response_model=List[Collection])
def list_collections(db: Session = Depends(get_db)) -> List[Collection]:
    res = db.execute(text("SELECT id, name FROM tabular_collections ORDER BY name ASC"))
    return [Collection(id=row.id, name=row.name) for row in res.fetchall()]


@router.delete("/{collection_name}", status_code=204)
def delete_collection(collection_name: str, db: Session = Depends(get_db)) -> None:
    trimmed_name = collection_name.strip()
    if not trimmed_name:
        raise HTTPException(status_code=400, detail="Collection name is required")
    res = db.execute(
        text("DELETE FROM tabular_collections WHERE name = :name RETURNING id"),
        {"name": trimmed_name},
    )
    row = res.fetchone()
    if not row:
        db.rollback()
        raise HTTPException(status_code=404, detail="Collection not found")
    db.commit()
    return None


__all__ = [
    "create_collection",
    "list_collections",
    "delete_collection",
    "router",
]
