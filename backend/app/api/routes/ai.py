"""Sentinel AI conversational retrieval endpoint."""

from fastapi import APIRouter

from app.core.config import settings
from app.schemas.ai_chat import AIChatRequest, AIChatResponse
from app.services.ai_chat import AIChatService
from app.services.ai_retrieval import AIRetrievalService
from app.services.ollama_provider import OllamaAnswerProvider

router = APIRouter(prefix="/ai", tags=["sentinel ai"])


def _service() -> AIChatService:
    retrieval = AIRetrievalService(settings.data_dir, settings.investigation_db)
    return AIChatService(retrieval, OllamaAnswerProvider.from_environment(), retrieval.resolve_entity)


@router.post("/chat", response_model=AIChatResponse)
def chat(request: AIChatRequest) -> dict:
    return _service().respond(request.dict())
