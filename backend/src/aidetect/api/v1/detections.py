import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from aidetect.api.deps import SettingsDep, require_internal_token
from aidetect.db.session import get_db_session
from aidetect.schemas.detection import DetectionRequest, DetectionResponse
from aidetect.services.auth import get_current_user
from aidetect.services.cache import get_cache
from aidetect.services.orchestrator import Orchestrator

router = APIRouter()


async def require_detection_auth(
    settings: SettingsDep,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if x_api_key:
        await require_internal_token(settings, x_api_key=x_api_key)
        return
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if secrets.compare_digest(token, settings.aidetect_internal_token):
            await require_internal_token(settings, authorization=authorization)
            return
    await get_current_user(settings, session, authorization)


DetectionAuthDep = Annotated[None, Depends(require_detection_auth)]


@router.post("", response_model=DetectionResponse, status_code=status.HTTP_201_CREATED)
async def create_detection(
    payload: DetectionRequest,
    settings: SettingsDep,
    _auth: DetectionAuthDep,
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
