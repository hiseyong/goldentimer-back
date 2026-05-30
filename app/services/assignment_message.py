"""환자 병원 배정 안내 메시지 생성."""

from __future__ import annotations

from app.services.hospital_recommendation import CapabilityNeeds, estimate_travel_minutes
from app.services.hospital_wait_time import WaitTimeEstimate

WAIT_LEVEL_KO = {
    "low": "원활",
    "moderate": "보통",
    "high": "혼잡",
    "severe": "매우 혼잡",
}


def _summarize_symptoms(transcript: str, needs: CapabilityNeeds) -> str:
    text = transcript.strip()
    if len(text) > 60:
        text = text[:57] + "..."
    if text:
        return text
    if needs.any_required:
        return needs.korean_summary()
    return "응급"


def _facility_description(needs: CapabilityNeeds) -> str:
    if needs.any_required:
        return needs.korean_summary()
    return "응급의료"


def build_assignment_guidance_message(
    *,
    transcript: str,
    needs: CapabilityNeeds,
    hospital_name: str,
    distance_km: float,
    wait: WaitTimeEstimate,
    recommend_only: bool = False,
) -> str:
    symptom_text = _summarize_symptoms(transcript, needs)
    facility_text = _facility_description(needs)
    travel_minutes = estimate_travel_minutes(distance_km)
    congestion = WAIT_LEVEL_KO.get(wait.wait_level, wait.wait_level)
    final_wait = wait.estimated_wait_minutes
    action = "추천합니다" if recommend_only else "배정되었습니다"

    return (
        f"해당 환자는 {symptom_text} 증상이 있어서 {facility_text} 시설이 있는 병원 중에\n"
        f"이동 시간 약 {travel_minutes}분 (거리 {distance_km:.1f}km)\n"
        f"번잡도 {congestion}\n"
        f"{hospital_name}으로 {action}.\n"
        f"구급차가 병원에 도착했을 때 환자가 대기해야 하는 최종 예상 시간은 {final_wait}분입니다."
    )
