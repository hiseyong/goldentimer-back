"""Paramedic voice transcript analysis via Gemini with rule-based fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.clients.gemini import GeminiApiError, GeminiClient
from app.core.config import Settings, get_settings
from app.services.hospital_recommendation import (
    CapabilityNeeds,
    PatientProfile,
    infer_capability_needs,
    infer_ktas_level,
    infer_patient_profile,
)

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """You are an emergency medical triage assistant for Korean ambulance dispatch.
Analyze the paramedic voice-recognition transcript and return JSON only.

Transcript:
\"\"\"
{transcript}
\"\"\"

Return this exact JSON shape:
{{
  "patient_name": "string (use 'Unknown' or '미상' if not stated)",
  "patient_age": integer or null,
  "patient_sex": "M", "F", or null,
  "trauma": boolean,
  "stroke": boolean,
  "cardiac": boolean,
  "ktas_level": integer from 1 (most urgent) to 5 (least urgent),
  "suspected_diagnosis": "short Korean or English clinical impression, or null",
  "clinical_summary": "one concise English sentence summarizing presentation"
}}

Rules:
- KTAS 1: cardiac arrest, not breathing, unconscious with life threat
- KTAS 2: chest pain, stroke symptoms, severe trauma, massive bleeding
- KTAS 3: urgent but stable emergencies; default when uncertain
- Set trauma/stroke/cardiac true only when the case needs that specialty center
- Infer age/sex from phrases like "60s male", "60대 남성", etc.
"""


@dataclass(frozen=True)
class TranscriptAnalysis:
    profile: PatientProfile
    needs: CapabilityNeeds
    ktas_level: int
    suspected_diagnosis: str | None
    clinical_summary: str | None = None


class TranscriptAnalyzer:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client: GeminiClient | None = None
        if self.settings.gemini_enabled:
            self._client = GeminiClient(
                api_key=self.settings.gemini_api_key,
                model=self.settings.gemini_model,
                timeout_sec=self.settings.gemini_timeout_sec,
            )

    def analyze(self, transcript: str) -> TranscriptAnalysis:
        if self._client is not None:
            try:
                return self._analyze_with_gemini(transcript)
            except GeminiApiError as exc:
                logger.warning("Gemini transcript analysis failed, using rules: %s", exc)
            except Exception:
                logger.exception("Unexpected Gemini analysis error, using rules")

        return self._analyze_with_rules(transcript)

    def _analyze_with_gemini(self, transcript: str) -> TranscriptAnalysis:
        assert self._client is not None
        prompt = ANALYSIS_PROMPT.format(transcript=transcript.strip())
        raw = self._client.generate_content(prompt, json_mode=True)
        data = GeminiClient.parse_json_response(raw)
        return self._parse_analysis(data, transcript)

    def _parse_analysis(self, data: dict, transcript: str) -> TranscriptAnalysis:
        needs = CapabilityNeeds(
            trauma=bool(data.get("trauma")),
            stroke=bool(data.get("stroke")),
            cardiac=bool(data.get("cardiac")),
        )
        ktas_level = self._clamp_ktas(data.get("ktas_level"), needs, transcript)
        profile = PatientProfile(
            name=str(data.get("patient_name") or "Unknown"),
            age=self._parse_age(data.get("patient_age")),
            sex=self._normalize_sex(data.get("patient_sex")),
        )
        suspected = data.get("suspected_diagnosis")
        if isinstance(suspected, str):
            suspected = suspected.strip() or None
        else:
            suspected = None

        clinical_summary = data.get("clinical_summary")
        if isinstance(clinical_summary, str):
            clinical_summary = clinical_summary.strip() or None
        else:
            clinical_summary = None

        return TranscriptAnalysis(
            profile=profile,
            needs=needs,
            ktas_level=ktas_level,
            suspected_diagnosis=suspected,
            clinical_summary=clinical_summary,
        )

    def _analyze_with_rules(self, transcript: str) -> TranscriptAnalysis:
        needs = infer_capability_needs(transcript)
        ktas_level = infer_ktas_level(transcript, needs)
        profile = infer_patient_profile(transcript)
        suspected = needs.korean_summary() if needs.any_required else None
        return TranscriptAnalysis(
            profile=profile,
            needs=needs,
            ktas_level=ktas_level,
            suspected_diagnosis=suspected,
        )

    def _clamp_ktas(
        self, value: object, needs: CapabilityNeeds, transcript: str
    ) -> int:
        try:
            level = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return infer_ktas_level(transcript, needs)
        return max(1, min(5, level))

    @staticmethod
    def _parse_age(value: object) -> int | None:
        try:
            age = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return age if 0 < age <= 120 else None

    @staticmethod
    def _normalize_sex(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        token = value.strip().upper()
        if token in ("M", "MALE", "MAN"):
            return "M"
        if token in ("F", "FEMALE", "WOMAN"):
            return "F"
        return None
