from fastapi import APIRouter, HTTPException, status

from aidetect.api.deps import AuthDep, SettingsDep
from aidetect.schemas.rewrite import RewriteRequest, RewriteResponse
from aidetect.services.cache import get_cache
from aidetect.services.orchestrator import Orchestrator
from aidetect.services.rewriter import Rewriter

router = APIRouter()


@router.post("", response_model=RewriteResponse, status_code=status.HTTP_201_CREATED)
async def create_rewrite(
    payload: RewriteRequest,
    settings: SettingsDep,
    _auth: AuthDep,
) -> RewriteResponse:
    if len(payload.text) > settings.max_text_length:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"text exceeds MAX_TEXT_LENGTH={settings.max_text_length}",
        )
    if not settings.openrouter_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="rewriter unavailable: OPENROUTER_API_KEY is not configured",
        )
    cache = await get_cache(settings)
    orchestrator = Orchestrator(settings=settings, cache=cache)
    rewriter = Rewriter(settings=settings, orchestrator=orchestrator)
    try:
        return await rewriter.rewrite(payload)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
