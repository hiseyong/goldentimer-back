"""병원 추천: 거리, 가용 병상, 중증질환 수용 능력 기반."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.models.hospital import Hospital

EARTH_RADIUS_KM = 6371.0

TRAUMA_KEYWORDS = (
    "trauma", "외상", "교통사고", "추돌", "낙상", "골절", "다발성", "관통",
)
STROKE_KEYWORDS = (
    "stroke", "뇌졸중", "뇌경색", "뇌출혈", "마비", "facial droop", "slurred speech",
)
CARDIAC_KEYWORDS = (
    "cardiac", "chest pain", "흉통", "심장", "심근", "angina", "stemi", "mi",
    "심정지", "부정맥",
)


@dataclass(frozen=True)
class CapabilityNeeds:
    trauma: bool = False
    stroke: bool = False
    cardiac: bool = False

    @property
    def any_required(self) -> bool:
        return self.trauma or self.stroke or self.cardiac


def infer_capability_needs(transcript: str) -> CapabilityNeeds:
    text = transcript.lower()
    return CapabilityNeeds(
        trauma=_contains_keyword(text, TRAUMA_KEYWORDS),
        stroke=_contains_keyword(text, STROKE_KEYWORDS),
        cardiac=_contains_keyword(text, CARDIAC_KEYWORDS),
    )


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


def _sort_key(hospital: Hospital, lat: float, lon: float) -> tuple:
    distance = haversine_km(lat, lon, float(hospital.latitude), float(hospital.longitude))
    no_beds = hospital.total_er_beds <= 0
    return (no_beds, distance)


def recommend_hospital(
    hospitals: list[Hospital],
    latitude: float,
    longitude: float,
    needs: CapabilityNeeds,
) -> Hospital | None:
    if not hospitals:
        return None

    candidates = [h for h in hospitals if _meets_capabilities(h, needs)]
    if not candidates and needs.any_required:
        candidates = list(hospitals)

    candidates.sort(key=lambda h: _sort_key(h, latitude, longitude))
    return candidates[0]


def find_nearby_hospitals(
    hospitals: list[Hospital],
    latitude: float,
    longitude: float,
    limit: int = 5,
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
    ranked.sort(key=lambda item: (item[0].total_er_beds <= 0, item[1]))
    return ranked[:limit]
