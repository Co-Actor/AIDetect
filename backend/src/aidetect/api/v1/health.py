from fastapi import APIRouter

from aidetect import __version__
from aidetect.api.deps import SettingsDep

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(settings: SettingsDep) -> dict[str, object]:
    return {
        "status": "ok",
        "version": __version__,
        "model_version": settings.model_version,
        "rubric_version": settings.rubric_version,
        "environment": settings.environment,
    }
