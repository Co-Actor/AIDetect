import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aidetect import __version__
from aidetect.api.v1.router import api_router
from aidetect.config import get_settings
from aidetect.services.cache import close_cache
from aidetect.services.observability import flush_observer, get_observer

logger = logging.getLogger(__name__)


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
    yield
    flush_observer()
    await close_cache()
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
