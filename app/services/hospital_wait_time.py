"""응급실 대기 시간 추정 (병상 가용 + 병원 내/유입 환자 중증도)."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.hospital import Hospital

KTAS_PROCESSING_MINUTES: dict[int, int] = {
    1: 90,
    2: 60,
    3: 35,
    4: 20,
    5: 12,
}
INCOMING_BURDEN_RATIO = 0.5


@dataclass(frozen=True)
class HospitalQueueCase:
    ktas_level: int | None
    transport_status: str | None


@dataclass(frozen=True)
class WaitTimeEstimate:
    estimated_wait_minutes: int
    bed_pressure_minutes: int
    existing_patient_minutes: int
    incoming_queue_minutes: int
    wait_level: str
    guidance: str


def ktas_burden_minutes(ktas_level: int | None) -> int:
    if ktas_level is None:
        return 25
    return KTAS_PROCESSING_MINUTES.get(ktas_level, 25)


def _is_present_at_hospital(transport_status: str | None) -> bool:
    return transport_status not in (None, "in_transit")


def estimate_er_wait_time(
    hospital: Hospital,
    queue_cases: list[HospitalQueueCase],
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

    existing_patient_minutes = sum(
        ktas_burden_minutes(case.ktas_level)
        for case in queue_cases
        if _is_present_at_hospital(case.transport_status)
    )
    incoming_queue_minutes = sum(
        int(ktas_burden_minutes(case.ktas_level) * INCOMING_BURDEN_RATIO)
        for case in queue_cases
        if not _is_present_at_hospital(case.transport_status)
    )

    total = min(
        bed_pressure + existing_patient_minutes + incoming_queue_minutes,
        180,
    )
    incoming_count = sum(
        1 for case in queue_cases if not _is_present_at_hospital(case.transport_status)
    )
    present_count = len(queue_cases) - incoming_count
    wait_level = _wait_level(total)
    guidance = _build_guidance(
        hospital,
        total,
        wait_level,
        present_count,
        incoming_count,
    )

    return WaitTimeEstimate(
        estimated_wait_minutes=total,
        bed_pressure_minutes=bed_pressure,
        existing_patient_minutes=existing_patient_minutes,
        incoming_queue_minutes=incoming_queue_minutes,
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
    present_count: int,
    incoming_count: int,
) -> str:
    if wait_level == "low":
        return (
            f"{hospital.hospital_name} ER is currently relatively clear. "
            f"Estimated wait ~{wait_minutes} min; {hospital.total_er_beds} beds available."
        )
    if wait_level == "moderate":
        return (
            f"{hospital.hospital_name} ER has moderate congestion. "
            f"Estimated wait ~{wait_minutes} min "
            f"({present_count} patients on site, {incoming_count} incoming)."
        )
    if wait_level == "high":
        return (
            f"{hospital.hospital_name} ER is congested. "
            f"{present_count} critical patients are being treated; "
            f"estimated wait ~{wait_minutes} min. "
            f"Consider nearby alternative hospitals."
        )
    return (
        f"{hospital.hospital_name} ER is severely congested or bed capacity is low. "
        f"On-site critical patient load suggests wait of {wait_minutes}+ min. "
        f"Strongly consider transfer to another emergency facility."
    )
