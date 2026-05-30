import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.repositories.hospital import HospitalRepository
from app.repositories.patient import (
    EmergencyCaseRepository,
    HospitalAssignmentRepository,
    PatientRepository,
)
from app.schemas.assignment import VoiceAssignmentRequest, VoiceAssignmentResponse
from app.schemas.hospital import EmergencyCaseResponse, HospitalResponse

DUMMY_HOSPITAL = HospitalResponse(
    hospital_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    hospital_name="Seoul National University Hospital",
    address="101 Daehak-ro, Jongno-gu, Seoul",
    latitude=37.5796,
    longitude=126.9988,
    total_er_beds=10,
    trauma_center=True,
    stroke_center=True,
    cardiac_center=True,
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
        # TODO: Replace with LLM analysis and DB-based hospital search
        patient = self.patient_repo.create_unknown()
        case = self.case_repo.create_from_transcript(
            patient_id=patient.patient_id,
            transcript=request.transcript,
            paramedic_id=request.paramedic_id,
            client_location=request.client_location.model_dump(exclude_none=True),
        )

        hospital = self.hospital_repo.get_first()
        if hospital is not None:
            self.assignment_repo.create(
                case_id=case.case_id,
                hospital_id=hospital.hospital_id,
            )
            hospital_response = HospitalResponse.model_validate(hospital)
        else:
            hospital_response = DUMMY_HOSPITAL

        self.assignment_repo.commit()

        return VoiceAssignmentResponse(
            emergency_case=EmergencyCaseResponse.model_validate(case),
            hospital=hospital_response,
        )
