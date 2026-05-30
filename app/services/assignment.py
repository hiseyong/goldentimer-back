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
    recommend_hospital,
)


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
        patient = self.patient_repo.create_unknown()
        case = self.case_repo.create_from_transcript(
            patient_id=patient.patient_id,
            transcript=request.transcript,
            paramedic_id=request.paramedic_id,
            client_location=request.client_location.model_dump(exclude_none=True),
        )

        needs = infer_capability_needs(request.transcript)
        hospitals = self.hospital_repo.list_for_recommendation()
        hospital = recommend_hospital(
            hospitals,
            request.client_location.latitude,
            request.client_location.longitude,
            needs,
        )

        if hospital is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No hospitals available for recommendation",
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
        message = (
            f"Recommended {hospital.hospital_name} "
            f"({distance_km:.1f} km, {hospital.total_er_beds} ER beds available)"
        )

        return VoiceAssignmentResponse(
            emergency_case=EmergencyCaseResponse.model_validate(case),
            hospital=HospitalResponse.model_validate(hospital),
            message=message,
        )
