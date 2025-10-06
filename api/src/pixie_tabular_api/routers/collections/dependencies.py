from fastapi import HTTPException, Request

from ...services import AttributeDescriberLLM, AttributeRankerLLM


def get_attribute_describer_llm(request: Request) -> AttributeDescriberLLM:
    llm = getattr(request.app.state, "attribute_describer_llm", None)
    if llm is None:
        raise HTTPException(
            status_code=503, detail="Attribute description service is unavailable"
        )
    return llm


def get_attribute_ranker_llm(request: Request) -> AttributeRankerLLM:
    llm = getattr(request.app.state, "attribute_ranker_llm", None)
    if llm is None:
        raise HTTPException(
            status_code=503, detail="Attribute ranking service is unavailable"
        )
    return llm


__all__ = [
    "get_attribute_describer_llm",
    "get_attribute_ranker_llm",
]
