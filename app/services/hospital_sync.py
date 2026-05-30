"""응급의료기관 OpenAPI → hospitals 테이블 동기화."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients.ermct import ErmctApiError, ErmctClient, HospitalBedItem, is_trauma_center
from app.core.database import engine
from app.data.korea_regions import iter_regions
from app.models.hospital import Hospital
from app.repositories.hospital import HospitalRepository

logger = logging.getLogger(__name__)

SCHEMA_MIGRATIONS = [
    "ALTER TABLE hospitals ADD COLUMN IF NOT EXISTS hpid VARCHAR(10)",
    "ALTER TABLE hospitals ADD COLUMN IF NOT EXISTS stage1 VARCHAR(32)",
    "ALTER TABLE hospitals ADD COLUMN IF NOT EXISTS stage2 VARCHAR(64)",
    "ALTER TABLE hospitals ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'hospitals_hpid_key'
        ) THEN
            ALTER TABLE hospitals ADD CONSTRAINT hospitals_hpid_key UNIQUE (hpid);
        END IF;
    END $$;
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_state (
        key VARCHAR(64) PRIMARY KEY,
        value VARCHAR(255) NOT NULL,
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
]

CURSOR_KEY = "hospital_rotation_cursor"


@dataclass
class SyncStats:
    regions_processed: int = 0
    hospitals_upserted: int = 0
    hospitals_updated: int = 0
    api_calls: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class RotationResult:
    updated: bool
    hospital_name: str | None = None
    hpid: str | None = None
    sleep_seconds: float = 60.0
    api_calls: int = 0
    error: str | None = None


@dataclass
class _RegionCacheEntry:
    fetched_at: float
    beds: dict[str, HospitalBedItem]


class HospitalSyncService:
    def __init__(self, db: Session, client: ErmctClient, cycle_minutes: int = 5):
        self.db = db
        self.client = client
        self.repo = HospitalRepository(db)
        self.cycle_minutes = cycle_minutes
        self._region_cache: dict[tuple[str, str], _RegionCacheEntry] = {}

    @staticmethod
    def ensure_schema() -> None:
        with engine.begin() as conn:
            for stmt in SCHEMA_MIGRATIONS:
                conn.execute(text(stmt))

    def rotation_interval(self) -> float:
        total = self.repo.count_with_hpid()
        if total <= 0:
            return 60.0
        cycle_seconds = self.cycle_minutes * 60
        return max(cycle_seconds / total, 0.5)

    def _get_cursor(self) -> int:
        row = self.db.execute(
            text("SELECT value FROM sync_state WHERE key = :key"),
            {"key": CURSOR_KEY},
        ).first()
        if row is None:
            return 0
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return 0

    def _set_cursor(self, cursor: int) -> None:
        self.db.execute(
            text(
                """
                INSERT INTO sync_state (key, value, updated_at)
                VALUES (:key, :value, NOW())
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = NOW()
                """
            ),
            {"key": CURSOR_KEY, "value": str(cursor)},
        )

    def _get_region_beds(
        self,
        stage1: str,
        stage2: str,
        cache_ttl: float,
        stats: SyncStats | None = None,
    ) -> dict[str, HospitalBedItem]:
        cache_key = (stage1, stage2)
        now = time.monotonic()
        cached = self._region_cache.get(cache_key)
        if cached is not None and now - cached.fetched_at < cache_ttl:
            return cached.beds

        bed_items = self.client.fetch_all_bed_info(stage1, stage2)
        if stats is not None:
            stats.api_calls += max(1, (len(bed_items) + 99) // 100)

        beds = {item.hpid: item for item in bed_items if item.hpid}
        self._region_cache[cache_key] = _RegionCacheEntry(fetched_at=now, beds=beds)
        return beds

    def sync_next_hospital(self) -> RotationResult:
        """순환 커서 기준 다음 병원 1곳의 실시간 병상 정보를 갱신한다."""
        interval = self.rotation_interval()
        hospitals = self.repo.list_for_rotation()
        if not hospitals:
            return RotationResult(
                updated=False,
                sleep_seconds=interval,
                error="no hospitals in DB",
            )

        cursor = self._get_cursor() % len(hospitals)
        hospital = hospitals[cursor]
        next_cursor = (cursor + 1) % len(hospitals)

        if not hospital.stage1 or not hospital.stage2:
            self._set_cursor(next_cursor)
            self.repo.commit()
            return RotationResult(
                updated=False,
                hospital_name=hospital.hospital_name,
                hpid=hospital.hpid,
                sleep_seconds=interval,
                error="missing stage1/stage2",
            )

        stats = SyncStats()
        try:
            beds = self._get_region_beds(
                hospital.stage1,
                hospital.stage2,
                cache_ttl=interval,
                stats=stats,
            )
            bed = beds.get(hospital.hpid or "")
            if bed is None:
                self._set_cursor(next_cursor)
                self.repo.commit()
                return RotationResult(
                    updated=False,
                    hospital_name=hospital.hospital_name,
                    hpid=hospital.hpid,
                    sleep_seconds=interval,
                    api_calls=stats.api_calls,
                    error="bed info not found in API response",
                )

            self.repo.update_beds(
                hospital,
                total_er_beds=bed.available_er_beds,
                stroke_center=bed.stroke_center,
                cardiac_center=bed.cardiac_center,
            )
            self._touch_hospital(hospital)
            self._set_cursor(next_cursor)
            self.repo.commit()

            return RotationResult(
                updated=True,
                hospital_name=hospital.hospital_name,
                hpid=hospital.hpid,
                sleep_seconds=interval,
                api_calls=stats.api_calls,
            )
        except ErmctApiError as exc:
            self.db.rollback()
            return RotationResult(
                updated=False,
                hospital_name=hospital.hospital_name,
                hpid=hospital.hpid,
                sleep_seconds=interval,
                error=str(exc),
            )

    def sync_region_full(self, stage1: str, stage2: str, stats: SyncStats) -> None:
        try:
            list_items = self.client.fetch_all_hospital_list(stage1, stage2)
            stats.api_calls += max(1, (len(list_items) + 99) // 100)

            bed_items = self.client.fetch_all_bed_info(stage1, stage2)
            stats.api_calls += max(1, (len(bed_items) + 99) // 100)
        except ErmctApiError as exc:
            stats.errors.append(f"{stage1}/{stage2}: {exc}")
            return

        bed_map = {item.hpid: item for item in bed_items if item.hpid}

        for item in list_items:
            if not item.hpid:
                continue
            bed = bed_map.get(item.hpid)
            self.repo.upsert_from_api(
                hpid=item.hpid,
                hospital_name=item.hospital_name,
                address=item.address,
                stage1=stage1,
                stage2=stage2,
                latitude=item.latitude,
                longitude=item.longitude,
                total_er_beds=bed.available_er_beds if bed else 0,
                trauma_center=is_trauma_center(item.emergency_class),
                stroke_center=bed.stroke_center if bed else False,
                cardiac_center=bed.cardiac_center if bed else False,
            )
            stats.hospitals_upserted += 1

        stats.regions_processed += 1

    def sync_full(
        self,
        regions: list[tuple[str, str]] | None = None,
        max_regions: int | None = None,
    ) -> SyncStats:
        stats = SyncStats()
        target_regions = regions or iter_regions()
        if max_regions is not None:
            target_regions = target_regions[:max_regions]

        for stage1, stage2 in target_regions:
            self.sync_region_full(stage1, stage2, stats)

        self._touch_all_hospitals()
        self.repo.commit()
        return stats

    def _touch_hospital(self, hospital: Hospital) -> None:
        hospital.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    def _touch_all_hospitals(self) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.db.execute(
            text("UPDATE hospitals SET updated_at = :now WHERE hpid IS NOT NULL"),
            {"now": now},
        )
