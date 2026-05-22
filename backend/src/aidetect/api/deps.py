import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from aidetect.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]


async def require_internal_token(
    settings: SettingsDep,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    token: str | None = x_api_key
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip() or None
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API token required (header X-API-Key or Authorization: Bearer <token>)",
        )
    if not secrets.compare_digest(token, settings.aidetect_internal_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid API token",
        )


AuthDep = Annotated[None, Depends(require_internal_token)]
