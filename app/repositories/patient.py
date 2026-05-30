import json

from sqlalchemy.orm import Session

from app.models.assignment import HospitalAssignment
from app.models.patient import EmergencyCase, Patient


class PatientRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_unknown(self) -> Patient:
        patient = Patient(name="Unknown")
        self.db.add(patient)
        self.db.flush()
        return patient


class EmergencyCaseRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_from_transcript(
        self,
        *,
        patient_id,
        transcript: str,
        paramedic_id: str | None = None,
        client_location: dict | None = None,
    ) -> EmergencyCase:
        case = EmergencyCase(
            patient_id=patient_id,
            chief_complaint=transcript,
            detailed_description=f"paramedic_id={paramedic_id}" if paramedic_id else None,
            incident_location=json.dumps(client_location) if client_location else None,
            ktas_level=2,
            transport_status="in_transit",
            status="active",
        )
        self.db.add(case)
        self.db.flush()
        return case


class HospitalAssignmentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        case_id,
        hospital_id,
        recommendation_rank: int = 1,
        estimated_arrival_minutes: int = 15,
    ) -> HospitalAssignment:
        assignment = HospitalAssignment(
            case_id=case_id,
            hospital_id=hospital_id,
            recommendation_rank=recommendation_rank,
            estimated_arrival_minutes=estimated_arrival_minutes,
            acceptance_status="pending",
        )
        self.db.add(assignment)
        self.db.flush()
        return assignment

    def commit(self) -> None:
        self.db.commit()
