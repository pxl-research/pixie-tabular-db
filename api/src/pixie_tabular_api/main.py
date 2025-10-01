import logging
import os

from fastapi import FastAPI

from .routers import collections, health
from .services import AttributeDescriberLLM, AttributeRankerLLM, AzureOpenAILLM


def create_app() -> FastAPI:
    app = FastAPI(title="Pixie Tabular API", version="0.1.0")
    app.include_router(health.router)
    app.include_router(collections.router)

    _configure_attribute_describer(app)
    return app


def _configure_attribute_describer(app: FastAPI) -> None:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION")
    deployment = os.getenv("AZURE_OPENAI_MODEL_VERSION")

    if not all([endpoint, api_key, api_version, deployment]):
        logging.warning(
            "Attribute describer LLM not configured; missing Azure OpenAI settings"
        )
        return

    try:
        azure_llm = AzureOpenAILLM(
            endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
            deployment=deployment,
        )
        app.state.attribute_describer_llm = AttributeDescriberLLM(azure_llm)
        app.state.attribute_ranker_llm = AttributeRankerLLM(azure_llm)
    except Exception as exc:  # pragma: no cover - configuration/runtime specific
        logging.error("Failed to initialise attribute describer LLM: %s", exc)


app = create_app()


__all__ = ["app", "create_app"]
