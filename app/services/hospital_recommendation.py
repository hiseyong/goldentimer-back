"""병원 추천: 거리, 가용 병상, 중증질환 수용, 대기 시간 기반."""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass

from app.models.hospital import Hospital
from app.services.hospital_wait_time import WaitTimeEstimate

EARTH_RADIUS_KM = 6371.0

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
    no_beds = hospital.total_er_beds <= 0
    return (no_beds, wait_minutes, distance)


def recommend_hospital(
    hospitals: list[Hospital],
    latitude: float,
    longitude: float,
    needs: CapabilityNeeds,
    wait_estimates: dict[uuid.UUID, WaitTimeEstimate] | None = None,
) -> Hospital | None:
    if not hospitals:
        return None

    if needs.any_required:
        candidates = [h for h in hospitals if _meets_capabilities(h, needs)]
        if not candidates:
            return None
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
    return candidates[0]


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
        return (hospital.total_er_beds <= 0, wait_minutes, distance)

    ranked.sort(key=sort_key)
    return ranked[:limit]
