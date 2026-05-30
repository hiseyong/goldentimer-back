"""응급실 대기 시간 추정 (병상 가용 + 병원 내/유입 환자 중증도)."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.hospital import Hospital

# Per-patient queue contribution (not full treatment duration).
KTAS_QUEUE_MINUTES: dict[int, int] = {
    1: 40,
    2: 28,
    3: 18,
    4: 12,
    5: 8,
}
INCOMING_BURDEN_RATIO = 0.35
QUEUE_SECONDARY_FACTOR = 0.25
MAX_WAIT_MINUTES = 120


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
        return 15
    return KTAS_QUEUE_MINUTES.get(ktas_level, 15)


def _diminishing_burden_sum(burdens: list[int]) -> int:
    """First patient drives most of the wait; additional patients add less."""
    if not burdens:
        return 0
    ordered = sorted(burdens, reverse=True)
    total = ordered[0]
    for burden in ordered[1:]:
        total += int(burden * QUEUE_SECONDARY_FACTOR)
    return total


def _bed_pressure_minutes(available_beds: int, queue_count: int) -> int:
    if available_beds < 0:
        base = 18 + min(abs(available_beds) * 2, 20)
    elif available_beds == 0:
        base = 25
    elif available_beds <= 2:
        base = 12
    elif available_beds <= 5:
        base = 7
    else:
        base = 4

    if queue_count == 0:
        return base
    # Active queue already reflects congestion; avoid double-counting scarcity.
    return max(int(base * 0.5), 3)


def _is_present_at_hospital(transport_status: str | None) -> bool:
    return transport_status not in (None, "in_transit")


def estimate_er_wait_time(
    hospital: Hospital,
    queue_cases: list[HospitalQueueCase],
) -> WaitTimeEstimate:
    present_burdens = [
        ktas_burden_minutes(case.ktas_level)
        for case in queue_cases
        if _is_present_at_hospital(case.transport_status)
    ]
    incoming_burdens = [
        int(ktas_burden_minutes(case.ktas_level) * INCOMING_BURDEN_RATIO)
        for case in queue_cases
        if not _is_present_at_hospital(case.transport_status)
    ]

    existing_patient_minutes = _diminishing_burden_sum(present_burdens)
    incoming_queue_minutes = _diminishing_burden_sum(incoming_burdens)
    bed_pressure = _bed_pressure_minutes(
        hospital.total_er_beds, len(queue_cases)
    )

    total = min(
        bed_pressure + existing_patient_minutes + incoming_queue_minutes,
        MAX_WAIT_MINUTES,
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
