from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.repositories.hospital import HospitalRepository
from app.repositories.patient import (
    EmergencyCaseRepository,
    HospitalAssignmentRepository,
    PatientRepository,
)
from app.schemas.assignment import (
    AssignmentWaitTime,
    VoiceAssignmentRequest,
    VoiceAssignmentResponse,
)
from app.schemas.hospital import EmergencyCaseResponse, HospitalResponse, WaitTimeBreakdown
from app.services.assignment_message import build_assignment_guidance_message
from app.services.hospital_recommendation import (
    estimate_travel_minutes,
    haversine_km,
    infer_capability_needs,
    infer_ktas_level,
    infer_patient_profile,
    recommend_hospital,
)
from app.services.hospital_wait_time import estimate_er_wait_time


class AssignmentService:
    def __init__(self, db: Session):
        self.db = db
        self.patient_repo = PatientRepository(db)
        self.case_repo = EmergencyCaseRepository(db)
        self.assignment_repo = HospitalAssignmentRepository(db)
        self.hospital_repo = HospitalRepository(db)

    def process_voice_assignment(
        self, request: VoiceAssignmentRequest
    ) -> VoiceAssignmentResponse:
        needs = infer_capability_needs(request.transcript)
        ktas_level = infer_ktas_level(request.transcript, needs)
        suspected = needs.korean_summary() if needs.any_required else None
        profile = infer_patient_profile(request.transcript)

        hospitals = self.hospital_repo.list_for_recommendation()
        queue_map = self.assignment_repo.map_active_queue_cases_by_hospital()
        wait_estimates = {
            hospital.hospital_id: estimate_er_wait_time(
                hospital, queue_map.get(hospital.hospital_id, [])
            )
            for hospital in hospitals
        }

        hospital = recommend_hospital(
            hospitals,
            request.client_location.latitude,
            request.client_location.longitude,
            needs,
            wait_estimates=wait_estimates,
        )

        if hospital is None:
            detail = "No suitable hospital found"
            if needs.any_required:
                detail = (
                    f"No hospital with required capabilities: {needs.english_summary()}"
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=detail,
            )

        distance_km = haversine_km(
            request.client_location.latitude,
            request.client_location.longitude,
            float(hospital.latitude),
            float(hospital.longitude),
        )
        wait = wait_estimates[hospital.hospital_id]
        travel_minutes = estimate_travel_minutes(distance_km)

        patient, case = self._register_emergency_case(
            request=request,
            profile=profile,
            ktas_level=ktas_level,
            suspected_diagnosis=suspected,
        )
        self.assignment_repo.register_case_assignment(
            case_id=case.case_id,
            hospital_id=hospital.hospital_id,
            estimated_arrival_minutes=travel_minutes,
        )
        self.db.commit()

        message = build_assignment_guidance_message(
            transcript=request.transcript,
            needs=needs,
            hospital_name=hospital.hospital_name,
            distance_km=distance_km,
            wait=wait,
        )

        return VoiceAssignmentResponse(
            emergency_case=EmergencyCaseResponse.model_validate(case),
            hospital=HospitalResponse.model_validate(hospital),
            wait_time=AssignmentWaitTime(
                distance_km=round(distance_km, 2),
                travel_minutes=travel_minutes,
                estimated_wait_minutes=wait.estimated_wait_minutes,
                wait_level=wait.wait_level,
                breakdown=WaitTimeBreakdown(
                    bed_pressure_minutes=wait.bed_pressure_minutes,
                    existing_patient_minutes=wait.existing_patient_minutes,
                    incoming_queue_minutes=wait.incoming_queue_minutes,
                ),
            ),
            message=message,
        )

    def _register_emergency_case(
        self,
        *,
        request: VoiceAssignmentRequest,
        profile,
        ktas_level: int,
        suspected_diagnosis: str | None,
    ):
        patient = self.patient_repo.create_from_profile(
            name=profile.name,
            age=profile.age,
            sex=profile.sex,
        )
        case = self.case_repo.create_from_transcript(
            patient_id=patient.patient_id,
            transcript=request.transcript,
            paramedic_id=request.paramedic_id,
            client_location=request.client_location.model_dump(exclude_none=True),
            ktas_level=ktas_level,
            suspected_diagnosis=suspected_diagnosis,
        )
        return patient, case
