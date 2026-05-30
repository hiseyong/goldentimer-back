"""Patient hospital assignment guidance message generation."""

from __future__ import annotations

from app.services.hospital_recommendation import CapabilityNeeds, estimate_travel_minutes
from app.services.hospital_wait_time import WaitTimeEstimate

WAIT_LEVEL_EN = {
    "low": "low congestion",
    "moderate": "moderate congestion",
    "high": "high congestion",
    "severe": "severe congestion",
}


def _summarize_symptoms(transcript: str, needs: CapabilityNeeds) -> str:
    text = transcript.strip()
    if len(text) > 60:
        text = text[:57] + "..."
    if text:
        return text
    if needs.any_required:
        return needs.english_summary()
    return "emergency"


def _facility_description(needs: CapabilityNeeds) -> str:
    if needs.any_required:
        return needs.english_summary()
    return "emergency care"


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
    congestion = WAIT_LEVEL_EN.get(wait.wait_level, wait.wait_level)
    final_wait = wait.estimated_wait_minutes
    action = "is recommended" if recommend_only else "has been assigned"

    return (
        f"This patient presents with {symptom_text} and requires a hospital with "
        f"{facility_text} capabilities.\n"
        f"Estimated travel time: ~{travel_minutes} min (distance {distance_km:.1f} km)\n"
        f"Congestion: {congestion}\n"
        f"{hospital_name} {action}.\n"
        f"Estimated wait time upon ambulance arrival: {final_wait} min."
    )
