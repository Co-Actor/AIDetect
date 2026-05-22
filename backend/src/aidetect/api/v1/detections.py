import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from aidetect.api.deps import AuthDep, SettingsDep
from aidetect.schemas.detection import DetectionRequest, DetectionResponse
from aidetect.services.cache import get_cache
from aidetect.services.orchestrator import Orchestrator

router = APIRouter()


@router.post("", response_model=DetectionResponse, status_code=status.HTTP_201_CREATED)
async def create_detection(
    payload: DetectionRequest,
    settings: SettingsDep,
    _auth: AuthDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DetectionResponse:
    if len(payload.text) > settings.max_text_length:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"text exceeds MAX_TEXT_LENGTH={settings.max_text_length}",
        )
    started = time.perf_counter()
    cache = await get_cache(settings)
    orchestrator = Orchestrator(settings=settings, cache=cache)
    result = await orchestrator.run(payload, idempotency_key=idempotency_key)
    if not result.metadata.cached:
        result.metadata.duration_ms = int((time.perf_counter() - started) * 1000)
    return result
