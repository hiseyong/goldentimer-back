"""응급실 대기 시간 추정 (병상 가용 + 유입 환자 기반)."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.hospital import Hospital


@dataclass(frozen=True)
class WaitTimeEstimate:
    estimated_wait_minutes: int
    bed_pressure_minutes: int
    incoming_queue_minutes: int
    severity_adjustment_minutes: int
    wait_level: str
    guidance: str


def estimate_er_wait_time(
    hospital: Hospital,
    active_incoming_count: int,
    ktas_levels: list[int | None],
) -> WaitTimeEstimate:
    beds = hospital.total_er_beds

    if beds < 0:
        bed_pressure = 45 + min(abs(beds) * 4, 40)
    elif beds == 0:
        bed_pressure = 40
    elif beds <= 3:
        bed_pressure = 28
    elif beds <= 8:
        bed_pressure = 18
    else:
        bed_pressure = 10

    queue_minutes = active_incoming_count * 12
    severe_count = sum(1 for level in ktas_levels if level is not None and level <= 2)
    severity_adjustment = severe_count * 6

    total = min(bed_pressure + queue_minutes + severity_adjustment, 180)
    wait_level = _wait_level(total)
    guidance = _build_guidance(hospital, total, wait_level, active_incoming_count)

    return WaitTimeEstimate(
        estimated_wait_minutes=total,
        bed_pressure_minutes=bed_pressure,
        incoming_queue_minutes=queue_minutes,
        severity_adjustment_minutes=severity_adjustment,
        wait_level=wait_level,
        guidance=guidance,
    )


def _wait_level(minutes: int) -> str:
    if minutes <= 20:
        return "low"
    if minutes <= 45:
        return "moderate"
    if minutes <= 90:
        return "high"
    return "severe"


def _build_guidance(
    hospital: Hospital,
    wait_minutes: int,
    wait_level: str,
    incoming_count: int,
) -> str:
    if wait_level == "low":
        return (
            f"{hospital.hospital_name} 응급실은 현재 비교적 원활합니다. "
            f"예상 대기 약 {wait_minutes}분, 가용 병상 {hospital.total_er_beds}개."
        )
    if wait_level == "moderate":
        return (
            f"{hospital.hospital_name} 응급실은 보통 수준의 혼잡도입니다. "
            f"예상 대기 약 {wait_minutes}분, 유입 예정 환자 {incoming_count}명."
        )
    if wait_level == "high":
        return (
            f"{hospital.hospital_name} 응급실은 혼잡합니다. "
            f"예상 대기 약 {wait_minutes}분. 인근 다른 병원 검토를 권장합니다."
        )
    return (
        f"{hospital.hospital_name} 응급실은 매우 혼잡하거나 병상 여유가 부족합니다. "
        f"예상 대기 {wait_minutes}분 이상. 다른 응급의료기관 이송을 적극 검토하세요."
    )
