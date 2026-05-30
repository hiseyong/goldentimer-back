from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.jobs.scheduler import setup_hospital_sync_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    scheduler, stop_event, rotation_task = setup_hospital_sync_scheduler(settings)
    yield
    if stop_event is not None:
        stop_event.set()
    if rotation_task is not None:
        rotation_task.cancel()
        try:
            await rotation_task
        except asyncio.CancelledError:
            pass
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        logger.info("Hospital sync scheduler stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
    )
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
