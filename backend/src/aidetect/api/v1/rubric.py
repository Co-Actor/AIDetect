from fastapi import APIRouter

from aidetect.api.deps import SettingsDep

router = APIRouter()


@router.get("/versions")
async def rubric_versions(settings: SettingsDep) -> dict[str, object]:
    return {
        "current": settings.rubric_version,
        "available": [settings.rubric_version],
    }
