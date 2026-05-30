"""병원 데이터 동기화 스케줄러."""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.clients.ermct import ErmctClient
from app.core.config import Settings
from app.core.database import SessionLocal
from app.repositories.hospital import HospitalRepository
from app.services.hospital_sync import HospitalSyncService

logger = logging.getLogger(__name__)


async def _hospital_rotation_loop(settings: Settings, stop_event: asyncio.Event) -> None:
    """전국 병원을 순환하며 실시간 병상 정보를 갱신한다."""
    if not settings.ermct_service_key:
        logger.warning("ERMCT service key missing; rotation loop not started")
        return

    logger.info(
        "Hospital rotation loop started (cycle=%s min)",
        settings.hospital_sync_cycle_minutes,
    )

    while not stop_event.is_set():
        db = SessionLocal()
        sleep_seconds = 60.0
        try:
            service = HospitalSyncService(
                db,
                ErmctClient(
                    settings.ermct_service_key,
                    request_delay_sec=settings.hospital_sync_request_delay_sec,
                ),
                cycle_minutes=settings.hospital_sync_cycle_minutes,
            )
            result = service.sync_next_hospital()
            sleep_seconds = result.sleep_seconds

            if result.updated:
                logger.debug(
                    "Bed updated: %s (%s) next_in=%.1fs",
                    result.hospital_name,
                    result.hpid,
                    sleep_seconds,
                )
            elif result.error:
                logger.warning(
                    "Bed sync skipped: %s (%s) reason=%s next_in=%.1fs",
                    result.hospital_name,
                    result.hpid,
                    result.error,
                    sleep_seconds,
                )
        except Exception:
            logger.exception("Hospital rotation loop error")
            db.rollback()
        finally:
            db.close()

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=sleep_seconds)
            break
        except asyncio.TimeoutError:
            continue

    logger.info("Hospital rotation loop stopped")


def _run_full_sync(settings: Settings) -> None:
    if not settings.ermct_service_key:
        logger.warning("ERMCT service key missing; skipping full hospital sync")
        return

    db = SessionLocal()
    try:
        service = HospitalSyncService(
            db,
            ErmctClient(
                settings.ermct_service_key,
                request_delay_sec=settings.hospital_sync_request_delay_sec,
            ),
            cycle_minutes=settings.hospital_sync_cycle_minutes,
        )
        stats = service.sync_full()
        logger.info(
            "Full hospital sync done: regions=%s upserted=%s api_calls=%s errors=%s",
            stats.regions_processed,
            stats.hospitals_upserted,
            stats.api_calls,
            len(stats.errors),
        )
        if stats.errors:
            logger.warning("Full sync errors: %s", stats.errors[:5])
    except Exception:
        logger.exception("Full hospital sync failed")
        db.rollback()
    finally:
        db.close()


def setup_hospital_sync_scheduler(
    settings: Settings,
) -> tuple[AsyncIOScheduler | None, asyncio.Event | None, asyncio.Task | None]:
    if not settings.hospital_sync_enabled:
        return None, None, None
    if not settings.ermct_service_key:
        logger.warning("Hospital sync enabled but ERMCT_SERVICE_KEY is empty")
        return None, None, None

    HospitalSyncService.ensure_schema()

    db = SessionLocal()
    try:
        count = HospitalRepository(db).count_with_hpid()
    finally:
        db.close()

    interval = (settings.hospital_sync_cycle_minutes * 60) / max(count, 1)

    stop_event = asyncio.Event()
    rotation_task = asyncio.create_task(_hospital_rotation_loop(settings, stop_event))

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        _run_full_sync,
        CronTrigger(hour=settings.hospital_sync_full_hour, minute=0),
        args=[settings],
        id="hospital_full_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()

    logger.info(
        "Hospital sync started (rotation cycle=%s min, ~%.1fs/hospital, full=%02d:00 KST)",
        settings.hospital_sync_cycle_minutes,
        interval,
        settings.hospital_sync_full_hour,
    )
    return scheduler, stop_event, rotation_task
