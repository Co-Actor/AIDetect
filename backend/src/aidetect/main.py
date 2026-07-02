import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from aidetect import __version__
from aidetect.api.v1.router import api_router
from aidetect.config import Settings, get_settings
from aidetect.db.migrate import run_migrations
from aidetect.db.models import User
from aidetect.db.session import get_engine
from aidetect.services.cache import close_cache
from aidetect.services.observability import flush_observer, get_observer

logger = logging.getLogger(__name__)


async def _promote_configured_admins(engine: AsyncEngine, settings: Settings) -> None:
    """Grant is_admin to every user whose email is in ADMIN_EMAILS.

    Runs after migrations so a listed admin who registered earlier is promoted
    on the next boot; new listed admins self-promote on login (see auth router).
    """
    emails = settings.admin_emails_set
    if not emails:
        return
    async with engine.begin() as conn:
        await conn.execute(update(User).where(User.email.in_(emails)).values(is_admin=True))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    logger.info("AIDetect starting (env=%s, version=%s)", settings.environment, __version__)
    # Eagerly resolve the singleton so the Langfuse SDK init cost is paid at
    # boot, not on the first /v1/detections request. When tracing is disabled
    # this returns a NoopObserver — cheap and never raises.
    observer = get_observer()
    logger.info(
        "[observability] %s",
        "Langfuse enabled" if observer.enabled else "no-op (Langfuse disabled)",
    )
    engine = get_engine()
    await run_migrations(engine)
    await _promote_configured_admins(engine, settings)
    yield
    flush_observer()
    await close_cache()
    await engine.dispose()
    logger.info("AIDetect stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AIDetect API",
        version=__version__,
        description="Multi-signal AI text detector",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/v1")
    return app


app = create_app()
