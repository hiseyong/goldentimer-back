#!/usr/bin/env python3
"""병원 데이터 동기화 CLI.

사용 예:
  python scripts/sync_hospitals.py full              # 전국 전체 동기화 (신규 병원 등록)
  python scripts/sync_hospitals.py full --region '서울특별시 강남구'
  python scripts/sync_hospitals.py rotate            # 순환 갱신 1회 (다음 병원 1곳)
  python scripts/sync_hospitals.py migrate           # DB 스키마만 적용
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.clients.ermct import ErmctClient
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.hospital_sync import HospitalSyncService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def parse_region(value: str) -> tuple[str, str]:
    parts = value.strip().split(maxsplit=1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            "region은 '서울특별시 강남구' 형식이어야 합니다."
        )
    return parts[0], parts[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="응급의료기관 DB 동기화")
    subparsers = parser.add_subparsers(dest="command", required=True)

    full_parser = subparsers.add_parser("full", help="기관 목록 + 가용병상 전체 동기화")
    full_parser.add_argument(
        "--region",
        action="append",
        type=parse_region,
        help="특정 지역만 동기화 (예: --region '서울특별시 강남구')",
    )
    full_parser.add_argument(
        "--max-regions",
        type=int,
        default=None,
        help="처리할 최대 지역 수 (테스트용)",
    )

    subparsers.add_parser("rotate", help="순환 갱신 1회 (다음 병원 1곳)")
    subparsers.add_parser("migrate", help="hospitals 테이블 스키마 마이그레이션")

    args = parser.parse_args()
    settings = get_settings()

    if args.command == "migrate":
        HospitalSyncService.ensure_schema()
        logger.info("Schema migration completed")
        return 0

    if not settings.ermct_service_key:
        logger.error("ERMCT_SERVICE_KEY가 .env에 설정되어 있지 않습니다.")
        return 1

    HospitalSyncService.ensure_schema()
    db = SessionLocal()
    stats = None
    try:
        service = HospitalSyncService(
            db,
            ErmctClient(
                settings.ermct_service_key,
                request_delay_sec=settings.hospital_sync_request_delay_sec,
            ),
            cycle_minutes=settings.hospital_sync_cycle_minutes,
        )

        if args.command == "full":
            stats = service.sync_full(
                regions=args.region,
                max_regions=args.max_regions,
            )
            logger.info(
                "Full sync: regions=%s upserted=%s api_calls=%s",
                stats.regions_processed,
                stats.hospitals_upserted,
                stats.api_calls,
            )
        elif args.command == "rotate":
            result = service.sync_next_hospital()
            logger.info(
                "Rotate: updated=%s hospital=%s (%s) sleep=%.1fs api_calls=%s error=%s",
                result.updated,
                result.hospital_name,
                result.hpid,
                result.sleep_seconds,
                result.api_calls,
                result.error,
            )
            if result.error and not result.updated:
                return 2

        if stats and stats.errors:
            logger.warning("Errors (%s):", len(stats.errors))
            for err in stats.errors[:10]:
                logger.warning("  %s", err)
            return 2
        return 0
    except Exception:
        logger.exception("Sync failed")
        db.rollback()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
