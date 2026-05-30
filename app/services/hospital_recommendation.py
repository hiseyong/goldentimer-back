"""병원 추천: 거리, 가용 병상, 중증질환 수용, 대기 시간 기반 (+ Gemini 선택)."""

from __future__ import annotations

import logging
import math
import re
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.clients.gemini import GeminiApiError, GeminiClient
from app.core.config import Settings, get_settings
from app.models.hospital import Hospital
from app.services.hospital_wait_time import WaitTimeEstimate

if TYPE_CHECKING:
    from app.services.transcript_analysis import TranscriptAnalysis

logger = logging.getLogger(__name__)

LLM_CANDIDATE_LIMIT = 10

HOSPITAL_SELECTION_PROMPT = """You are an emergency medical dispatch assistant selecting the best ER hospital.
Choose the single best hospital for this patient from the candidate list.

Symptoms / transcript:
\"\"\"
{symptoms}
\"\"\"

Clinical summary: {clinical_summary}
KTAS level: {ktas_level} (1 = most urgent)
Required specialty centers: {capabilities}

Selection priorities:
1. Must satisfy required specialty centers (trauma / stroke / cardiac)
2. Minimize total time to treatment (travel + ER wait)
3. Prefer hospitals with available ER beds when clinically appropriate
4. For time-critical cases (KTAS 1-2), favor specialty capability over small travel savings

Candidates (sorted by estimated total ETA):
{candidates}

Return JSON only:
{{"hospital_id": "<uuid from list>", "reason": "one concise English sentence"}}
"""

EARTH_RADIUS_KM = 6371.0
AMBULANCE_SPEED_KMH = 40.0

TRAUMA_KEYWORDS = (
    "trauma", "외상", "교통사고", "추돌", "낙상", "골절", "다발성", "관통", "출혈",
    "traumatic", "blunt", "penetrating",
)
STROKE_KEYWORDS = (
    "stroke", "뇌졸중", "뇌경색", "뇌출혈", "마비", "facial droop", "slurred speech",
    "hemiplegia", "aphasia", "cva",
)
CARDIAC_KEYWORDS = (
    "cardiac", "chest pain", "흉통", "심장", "심근", "angina", "stemi", "mi",
    "심정지", "부정맥", "heart attack", "myocardial",
)
KTAS1_KEYWORDS = (
    "심정지", "cardiac arrest", "무의식", "unconscious", "not breathing",
    "호흡 없", "pulseless",
)
KTAS2_KEYWORDS = (
    "chest pain", "흉통", "stroke", "뇌졸중", "severe trauma", "중증 외상",
    "대량 출혈", "massive bleeding", "mi", "stemi",
)


@dataclass(frozen=True)
class PatientProfile:
    name: str
    age: int | None = None
    sex: str | None = None


@dataclass(frozen=True)
class CapabilityNeeds:
    trauma: bool = False
    stroke: bool = False
    cardiac: bool = False

    @property
    def any_required(self) -> bool:
        return self.trauma or self.stroke or self.cardiac

    def labels(self) -> list[str]:
        result: list[str] = []
        if self.trauma:
            result.append("trauma")
        if self.stroke:
            result.append("stroke")
        if self.cardiac:
            result.append("cardiac")
        return result

    def korean_summary(self) -> str:
        mapping = {
            "trauma": "외상(중증외상)",
            "stroke": "뇌혈관(뇌졸중)",
            "cardiac": "심장(흉부)",
        }
        labels = [mapping[label] for label in self.labels()]
        return ", ".join(labels) if labels else "일반"

    def english_summary(self) -> str:
        mapping = {
            "trauma": "severe trauma",
            "stroke": "stroke and cerebrovascular",
            "cardiac": "cardiac chest",
        }
        labels = [mapping[label] for label in self.labels()]
        return ", ".join(labels) if labels else "general"


def infer_patient_profile(transcript: str) -> PatientProfile:
    text = transcript.lower()

    ko_decade = re.search(r"(\d{1,2})대\s*(남|남성|여|여성)", transcript)
    if ko_decade:
        decade = int(ko_decade.group(1))
        sex_token = ko_decade.group(2)
        sex = "M" if sex_token.startswith("남") else "F"
        return PatientProfile(name="미상", age=decade + 2, sex=sex)

    en_age = re.search(
        r"(male|female|man|woman).{0,20}?(?:in (?:his|her)|,?)\s*(\d{1,2})s?",
        text,
    )
    if en_age:
        sex_token = en_age.group(1)
        sex = "M" if sex_token in ("male", "man") else "F"
        return PatientProfile(name="Unknown", age=int(en_age.group(2)), sex=sex)

    en_simple = re.search(r"(male|female|man|woman),?\s*(\d{1,2})\s*years?\s*old", text)
    if en_simple:
        sex_token = en_simple.group(1)
        sex = "M" if sex_token in ("male", "man") else "F"
        return PatientProfile(name="Unknown", age=int(en_simple.group(2)), sex=sex)

    if re.search(r"\b(male|man)\b", text):
        return PatientProfile(name="Unknown", sex="M")
    if re.search(r"\b(female|woman)\b", text):
        return PatientProfile(name="Unknown", sex="F")

    return PatientProfile(name="미상")


def infer_capability_needs(transcript: str) -> CapabilityNeeds:
    text = transcript.lower()
    return CapabilityNeeds(
        trauma=_contains_keyword(text, TRAUMA_KEYWORDS),
        stroke=_contains_keyword(text, STROKE_KEYWORDS),
        cardiac=_contains_keyword(text, CARDIAC_KEYWORDS),
    )


def infer_ktas_level(transcript: str, needs: CapabilityNeeds) -> int:
    text = transcript.lower()
    if _contains_keyword(text, KTAS1_KEYWORDS):
        return 1
    if _contains_keyword(text, KTAS2_KEYWORDS) or needs.any_required:
        return 2
    return 3


def estimate_travel_minutes(distance_km: float) -> int:
    minutes = int(round((distance_km / AMBULANCE_SPEED_KMH) * 60))
    return max(minutes, 3)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(a))


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(re.search(re.escape(kw), text) for kw in keywords)


def _meets_capabilities(hospital: Hospital, needs: CapabilityNeeds) -> bool:
    if needs.trauma and not hospital.trauma_center:
        return False
    if needs.stroke and not hospital.stroke_center:
        return False
    if needs.cardiac and not hospital.cardiac_center:
        return False
    return True


def _recommendation_sort_key(
    hospital: Hospital,
    lat: float,
    lon: float,
    wait_minutes: int,
) -> tuple:
    distance = haversine_km(lat, lon, float(hospital.latitude), float(hospital.longitude))
    travel_minutes = estimate_travel_minutes(distance)
    total_eta = travel_minutes + wait_minutes
    no_beds = hospital.total_er_beds <= 0
    return (no_beds, total_eta, distance)


def list_recommendation_candidates(
    hospitals: list[Hospital],
    latitude: float,
    longitude: float,
    needs: CapabilityNeeds,
    wait_estimates: dict[uuid.UUID, WaitTimeEstimate] | None = None,
    limit: int | None = None,
) -> list[Hospital]:
    if not hospitals:
        return []

    if needs.any_required:
        candidates = [h for h in hospitals if _meets_capabilities(h, needs)]
    else:
        candidates = list(hospitals)

    def wait_for(hospital: Hospital) -> int:
        if wait_estimates and hospital.hospital_id in wait_estimates:
            return wait_estimates[hospital.hospital_id].estimated_wait_minutes
        return 60

    candidates.sort(
        key=lambda h: _recommendation_sort_key(
            h, latitude, longitude, wait_for(h)
        )
    )
    if limit is not None:
        return candidates[:limit]
    return candidates


def recommend_hospital(
    hospitals: list[Hospital],
    latitude: float,
    longitude: float,
    needs: CapabilityNeeds,
    wait_estimates: dict[uuid.UUID, WaitTimeEstimate] | None = None,
) -> Hospital | None:
    candidates = list_recommendation_candidates(
        hospitals, latitude, longitude, needs, wait_estimates
    )
    return candidates[0] if candidates else None


def recommend_hospital_for_analysis(
    hospitals: list[Hospital],
    latitude: float,
    longitude: float,
    analysis: TranscriptAnalysis,
    wait_estimates: dict[uuid.UUID, WaitTimeEstimate] | None = None,
    settings: Settings | None = None,
    symptoms: str | None = None,
) -> Hospital | None:
    """Rank candidates by ETA, then use Gemini to pick the best fit when enabled."""
    settings = settings or get_settings()
    candidates = list_recommendation_candidates(
        hospitals,
        latitude,
        longitude,
        analysis.needs,
        wait_estimates,
        limit=LLM_CANDIDATE_LIMIT,
    )
    if not candidates:
        return None
    if settings.gemini_enabled and len(candidates) > 1:
        try:
            selected = _select_hospital_with_gemini(
                candidates=candidates,
                symptoms=symptoms or "",
                clinical_summary=analysis.clinical_summary,
                ktas_level=analysis.ktas_level,
                needs=analysis.needs,
                latitude=latitude,
                longitude=longitude,
                wait_estimates=wait_estimates,
                settings=settings,
            )
            if selected is not None:
                return selected
        except GeminiApiError as exc:
            logger.warning("Gemini hospital selection failed, using ETA ranking: %s", exc)
        except Exception:
            logger.exception("Unexpected Gemini hospital selection error, using ETA ranking")
    return candidates[0]


def _select_hospital_with_gemini(
    *,
    candidates: list[Hospital],
    symptoms: str,
    clinical_summary: str | None,
    ktas_level: int,
    needs: CapabilityNeeds,
    latitude: float,
    longitude: float,
    wait_estimates: dict[uuid.UUID, WaitTimeEstimate] | None,
    settings: Settings,
) -> Hospital | None:
    client = GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_sec=settings.gemini_timeout_sec,
    )
    candidate_lines: list[str] = []
    for index, hospital in enumerate(candidates, start=1):
        distance = haversine_km(
            latitude, longitude, float(hospital.latitude), float(hospital.longitude)
        )
        travel = estimate_travel_minutes(distance)
        wait = 60
        if wait_estimates and hospital.hospital_id in wait_estimates:
            wait = wait_estimates[hospital.hospital_id].estimated_wait_minutes
        candidate_lines.append(
            f"{index}. hospital_id={hospital.hospital_id}, name={hospital.hospital_name}, "
            f"distance_km={distance:.1f}, travel_min={travel}, wait_min={wait}, "
            f"total_eta_min={travel + wait}, er_beds={hospital.total_er_beds}, "
            f"trauma={hospital.trauma_center}, stroke={hospital.stroke_center}, "
            f"cardiac={hospital.cardiac_center}"
        )

    prompt = HOSPITAL_SELECTION_PROMPT.format(
        symptoms=symptoms.strip(),
        clinical_summary=clinical_summary or "not available",
        ktas_level=ktas_level,
        capabilities=needs.english_summary(),
        candidates="\n".join(candidate_lines),
    )
    raw = client.generate_content(prompt, json_mode=True)
    data = GeminiClient.parse_json_response(raw)
    hospital_id_raw = data.get("hospital_id")
    if not hospital_id_raw:
        raise GeminiApiError("Missing hospital_id in Gemini selection response")

    try:
        selected_id = uuid.UUID(str(hospital_id_raw))
    except ValueError as exc:
        raise GeminiApiError(f"Invalid hospital_id from Gemini: {hospital_id_raw}") from exc

    by_id = {hospital.hospital_id: hospital for hospital in candidates}
    if selected_id not in by_id:
        raise GeminiApiError(f"Gemini selected unknown hospital_id: {selected_id}")

    reason = data.get("reason")
    if isinstance(reason, str) and reason.strip():
        logger.info("Gemini hospital selection: %s", reason.strip())
    return by_id[selected_id]


def find_nearby_hospitals(
    hospitals: list[Hospital],
    latitude: float,
    longitude: float,
    limit: int = 5,
    wait_estimates: dict[uuid.UUID, WaitTimeEstimate] | None = None,
) -> list[tuple[Hospital, float]]:
    ranked = [
        (
            hospital,
            haversine_km(
                latitude, longitude, float(hospital.latitude), float(hospital.longitude)
            ),
        )
        for hospital in hospitals
    ]

    def sort_key(item: tuple[Hospital, float]) -> tuple:
        hospital, distance = item
        wait_minutes = 60
        if wait_estimates and hospital.hospital_id in wait_estimates:
            wait_minutes = wait_estimates[hospital.hospital_id].estimated_wait_minutes
        travel_minutes = estimate_travel_minutes(distance)
        total_eta = travel_minutes + wait_minutes
        return (hospital.total_er_beds <= 0, total_eta, distance)

    ranked.sort(key=sort_key)
    return ranked[:limit]
