import logging

from fastapi import FastAPI

from .config import get_settings
from .logging_config import configure_logging
from .routers import collections_main_router, health_router
from .services import AttributeDescriberLLM, AttributeRankerLLM, AzureOpenAILLM


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Pixie Tabular API", version="0.1.0")
    app.include_router(health_router)
    app.include_router(collections_main_router)

    _configure_attribute_describer(app)
    return app


def _configure_attribute_describer(app: FastAPI) -> None:
    settings = get_settings()

    if not settings.azure_llm_configured:
        logging.warning(
            "Attribute describer LLM not configured; missing Azure OpenAI settings"
        )
        return

    # After azure_llm_configured check, we know these values are not None
    assert settings.azure_openai_endpoint is not None
    assert settings.azure_openai_key is not None
    assert settings.azure_openai_api_version is not None
    assert settings.azure_openai_model_version is not None

    try:
        azure_llm = AzureOpenAILLM(
            endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_key,
            api_version=settings.azure_openai_api_version,
            deployment=settings.azure_openai_model_version,
        )
        app.state.attribute_describer_llm = AttributeDescriberLLM(azure_llm)
        app.state.attribute_ranker_llm = AttributeRankerLLM(azure_llm)
    except Exception as exc:  # pragma: no cover - configuration/runtime specific
        logging.error("Failed to initialise attribute describer LLM: %s", exc)


app = create_app()


__all__ = ["app", "create_app"]
