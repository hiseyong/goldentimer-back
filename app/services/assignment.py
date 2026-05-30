from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.repositories.hospital import HospitalRepository
from app.repositories.patient import (
    EmergencyCaseRepository,
    HospitalAssignmentRepository,
    PatientRepository,
)
from app.schemas.assignment import VoiceAssignmentRequest, VoiceAssignmentResponse
from app.schemas.hospital import EmergencyCaseResponse, HospitalResponse
from app.services.hospital_recommendation import (
    haversine_km,
    infer_capability_needs,
    infer_ktas_level,
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

        patient = self.patient_repo.create_unknown()
        case = self.case_repo.create_from_transcript(
            patient_id=patient.patient_id,
            transcript=request.transcript,
            paramedic_id=request.paramedic_id,
            client_location=request.client_location.model_dump(exclude_none=True),
            ktas_level=ktas_level,
            suspected_diagnosis=suspected,
        )

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
                    f"No hospital with required capabilities: {needs.korean_summary()}"
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=detail,
            )

        self.assignment_repo.create(
            case_id=case.case_id,
            hospital_id=hospital.hospital_id,
        )
        self.assignment_repo.commit()

        distance_km = haversine_km(
            request.client_location.latitude,
            request.client_location.longitude,
            float(hospital.latitude),
            float(hospital.longitude),
        )
        wait = wait_estimates[hospital.hospital_id]
        capability_note = (
            f" [{needs.korean_summary()} 수용 가능]"
            if needs.any_required
            else ""
        )
        message = (
            f"Recommended {hospital.hospital_name}{capability_note} "
            f"({distance_km:.1f} km, ER beds {hospital.total_er_beds}, "
            f"est. wait {wait.estimated_wait_minutes} min)"
        )

        return VoiceAssignmentResponse(
            emergency_case=EmergencyCaseResponse.model_validate(case),
            hospital=HospitalResponse.model_validate(hospital),
            message=message,
        )
