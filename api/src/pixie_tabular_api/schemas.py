from __future__ import annotations

from typing import Annotated, Dict, Any, List, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator


class CollectionCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Collection(BaseModel):
    id: int
    name: str


class Document(BaseModel):
    id: int
    file_name: str
    collection: str
    product: str | None = None
    row_count: int
    columns: List[str]
    attribute_descriptions: Dict[str, Dict[str, Any]] | None = None


class Product(BaseModel):
    id: int
    name: str
    collection: str


class AttributeExactFilter(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    type: Literal["exact"]
    value: str | int | float | bool


class AttributeRangeFilter(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    type: Literal["range"]
    min_value: float | int | None = None
    max_value: float | int | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "AttributeRangeFilter":
        if self.min_value is None and self.max_value is None:
            raise ValueError("range filter requires at least one bound")
        return self


AttributeFilter = Annotated[
    AttributeExactFilter | AttributeRangeFilter,
    Field(discriminator="type"),
]


class DocumentQueryRequest(BaseModel):
    filters: List[AttributeFilter] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class DocumentQueryResponse(BaseModel):
    product_name: str
    results: List[Dict[str, Any]]
    count: int
    total: int
    limit: int
    offset: int


__all__ = [
    "Collection",
    "CollectionCreate",
    "Document",
    "Product",
    "AttributeExactFilter",
    "AttributeRangeFilter",
    "AttributeFilter",
    "DocumentQueryRequest",
    "DocumentQueryResponse",
]
