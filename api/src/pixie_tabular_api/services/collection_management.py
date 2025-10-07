"""Service helpers for managing tabular collections."""

from __future__ import annotations

import logging
from typing import List

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..schemas import Collection, CollectionCreate

logger = logging.getLogger(__name__)


def create_collection(*, db: Session, payload: CollectionCreate) -> Collection:
    """Persist a new collection and return its metadata."""

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
        logger.info("Created collection '%s' (id=%s)", row.name, row.id)
        return Collection(id=row.id, name=row.name)
    except Exception as exc:  # pragma: no cover - bubble-up unknown database errors
        db.rollback()
        msg = str(exc).lower()
        if "unique" in msg and "tabular_collections" in msg:
            raise HTTPException(
                status_code=409, detail="Collection name already exists"
            ) from exc
        logger.exception(
            "Unexpected database error while creating collection '%s'",
            payload.name,
        )
        raise


def list_collections(*, db: Session) -> List[Collection]:
    """Fetch all collections ordered by name."""

    res = db.execute(text("SELECT id, name FROM tabular_collections ORDER BY name ASC"))
    return [Collection(id=row.id, name=row.name) for row in res.fetchall()]


def delete_collection(*, db: Session, collection_name: str) -> None:
    """Delete the given collection by name."""

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
    logger.info("Deleted collection '%s' (id=%s)", trimmed_name, row.id)


__all__ = [
    "create_collection",
    "delete_collection",
    "list_collections",
]
