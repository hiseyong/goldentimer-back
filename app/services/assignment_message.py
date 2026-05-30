"""Patient hospital assignment guidance message generation."""

from __future__ import annotations

import logging

from app.clients.gemini import GeminiApiError, GeminiClient
from app.core.config import Settings, get_settings
from app.services.hospital_recommendation import CapabilityNeeds, estimate_travel_minutes
from app.services.hospital_wait_time import WaitTimeEstimate

logger = logging.getLogger(__name__)

WAIT_LEVEL_EN = {
    "low": "low congestion",
    "moderate": "moderate congestion",
    "high": "high congestion",
    "severe": "severe congestion",
}

MESSAGE_PROMPT = """You are an emergency medical dispatch assistant.
Write a concise English guidance message (3-5 sentences) for paramedics after hospital assignment.

Transcript:
\"\"\"
{transcript}
\"\"\"

Clinical summary: {clinical_summary}
KTAS level: {ktas_level}
Required hospital capabilities: {capabilities}
Assigned hospital: {hospital_name}
Distance: {distance_km:.1f} km
Estimated travel time: {travel_minutes} min
ER congestion: {congestion}
Estimated wait on arrival: {final_wait} min

Include: patient presentation, required specialty, travel/wait estimates, and assigned hospital.
Do not use markdown or bullet points. Plain text only.
"""


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
    ktas_level: int | None = None,
    clinical_summary: str | None = None,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    if settings.gemini_enabled:
        try:
            return _build_with_gemini(
                transcript=transcript,
                needs=needs,
                hospital_name=hospital_name,
                distance_km=distance_km,
                wait=wait,
                ktas_level=ktas_level,
                clinical_summary=clinical_summary,
                settings=settings,
            )
        except GeminiApiError as exc:
            logger.warning("Gemini message generation failed, using template: %s", exc)
        except Exception:
            logger.exception("Unexpected Gemini message error, using template")

    return _build_template_message(
        transcript=transcript,
        needs=needs,
        hospital_name=hospital_name,
        distance_km=distance_km,
        wait=wait,
        recommend_only=recommend_only,
    )


def _build_with_gemini(
    *,
    transcript: str,
    needs: CapabilityNeeds,
    hospital_name: str,
    distance_km: float,
    wait: WaitTimeEstimate,
    ktas_level: int | None,
    clinical_summary: str | None,
    settings: Settings,
) -> str:
    client = GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_sec=settings.gemini_timeout_sec,
    )
    travel_minutes = estimate_travel_minutes(distance_km)
    congestion = WAIT_LEVEL_EN.get(wait.wait_level, wait.wait_level)
    summary = clinical_summary or _summarize_symptoms(transcript, needs)

    prompt = MESSAGE_PROMPT.format(
        transcript=transcript.strip(),
        clinical_summary=summary,
        ktas_level=ktas_level if ktas_level is not None else "unknown",
        capabilities=_facility_description(needs),
        hospital_name=hospital_name,
        distance_km=distance_km,
        travel_minutes=travel_minutes,
        congestion=congestion,
        final_wait=wait.estimated_wait_minutes,
    )
    message = client.generate_content(prompt).strip()
    if not message:
        raise GeminiApiError("Empty guidance message from Gemini")
    return message


def _build_template_message(
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
