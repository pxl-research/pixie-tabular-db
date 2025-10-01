from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, StringConstraints
from typing import List, Generator, Annotated
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

# ---- Database setup ----
DB_USER = os.getenv("POSTGRES_USER", "pixie")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "devpassword")
DB_NAME = os.getenv("POSTGRES_DB", "pixie_tabular")
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = int(os.getenv("DB_PORT", "5432"))

DATABASE_URL = (
    f"postgresql+psycopg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---- FastAPI app ----
app = FastAPI(title="Pixie Tabular API", version="0.1.0")


# ---- Schemas ----
class CollectionCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Collection(BaseModel):
    id: int
    name: str


# ---- Endpoints ----


@app.get("/health", tags=["health"])
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post(
    "/collections", response_model=Collection, status_code=201, tags=["collections"]
)
def create_collection(payload: CollectionCreate, db: Session = Depends(get_db)):
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
        return {"id": row.id, "name": row.name}
    except Exception as e:
        db.rollback()
        msg = str(e).lower()
        if "unique" in msg and "tabular_collections" in msg:
            raise HTTPException(
                status_code=409, detail="Collection name already exists"
            )
        raise


@app.get("/collections", response_model=List[Collection], tags=["collections"])
def list_collections(db: Session = Depends(get_db)):
    res = db.execute(text("SELECT id, name FROM tabular_collections ORDER BY name ASC"))
    return [{"id": r.id, "name": r.name} for r in res.fetchall()]


@app.delete("/collections/{collection_id}", status_code=204, tags=["collections"])
def delete_collection(collection_id: int, db: Session = Depends(get_db)):
    res = db.execute(
        text("DELETE FROM tabular_collections WHERE id = :id RETURNING id"),
        {"id": collection_id},
    )
    row = res.fetchone()
    if not row:
        db.rollback()
        raise HTTPException(status_code=404, detail="Collection not found")
    db.commit()
    return
