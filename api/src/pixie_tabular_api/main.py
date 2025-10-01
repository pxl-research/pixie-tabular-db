from fastapi import FastAPI

from .routers import collections, health


def create_app() -> FastAPI:
    app = FastAPI(title="Pixie Tabular API", version="0.1.0")
    app.include_router(health.router)
    app.include_router(collections.router)
    return app


app = create_app()


__all__ = ["app", "create_app"]

