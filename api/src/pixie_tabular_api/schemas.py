from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, StringConstraints


class CollectionCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Collection(BaseModel):
    id: int
    name: str


__all__ = [
    "Collection",
    "CollectionCreate",
]

