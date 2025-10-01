from __future__ import annotations

from typing import Annotated, List, Dict, Any

from pydantic import BaseModel, StringConstraints


class CollectionCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Collection(BaseModel):
    id: int
    name: str


class Document(BaseModel):
    id: int
    file_name: str
    collection: str
    row_count: int
    columns: List[str]
    attribute_descriptions: Dict[str, Dict[str, Any]] | None = None


__all__ = [
    "Collection",
    "CollectionCreate",
    "Document",
]
