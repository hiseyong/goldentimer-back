import json

from sqlalchemy.orm import Session

from app.models.assignment import HospitalAssignment
from app.models.patient import EmergencyCase, Patient
from app.services.hospital_wait_time import HospitalQueueCase


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
        ktas_level: int | None = None,
        suspected_diagnosis: str | None = None,
    ) -> EmergencyCase:
        case = EmergencyCase(
            patient_id=patient_id,
            chief_complaint=transcript,
            detailed_description=f"paramedic_id={paramedic_id}" if paramedic_id else None,
            suspected_diagnosis=suspected_diagnosis,
            incident_location=json.dumps(client_location) if client_location else None,
            ktas_level=ktas_level if ktas_level is not None else 3,
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

    def list_active_by_hospital(
        self, hospital_id
    ) -> list[tuple[HospitalAssignment, EmergencyCase, Patient]]:
        return (
            self.db.query(HospitalAssignment, EmergencyCase, Patient)
            .join(EmergencyCase, HospitalAssignment.case_id == EmergencyCase.case_id)
            .join(Patient, EmergencyCase.patient_id == Patient.patient_id)
            .filter(
                HospitalAssignment.hospital_id == hospital_id,
                EmergencyCase.status == "active",
            )
            .order_by(HospitalAssignment.assigned_at.desc())
            .all()
        )

    def list_active_queue_cases_by_hospital(
        self, hospital_id
    ) -> list[HospitalQueueCase]:
        rows = (
            self.db.query(EmergencyCase.ktas_level, EmergencyCase.transport_status)
            .join(HospitalAssignment, HospitalAssignment.case_id == EmergencyCase.case_id)
            .filter(
                HospitalAssignment.hospital_id == hospital_id,
                EmergencyCase.status == "active",
            )
            .all()
        )
        return [
            HospitalQueueCase(ktas_level=ktas, transport_status=status)
            for ktas, status in rows
        ]

    def map_active_queue_cases_by_hospital(self) -> dict:
        rows = (
            self.db.query(
                HospitalAssignment.hospital_id,
                EmergencyCase.ktas_level,
                EmergencyCase.transport_status,
            )
            .join(EmergencyCase, HospitalAssignment.case_id == EmergencyCase.case_id)
            .filter(EmergencyCase.status == "active")
            .all()
        )
        result: dict = {}
        for hospital_id, ktas, status in rows:
            result.setdefault(hospital_id, []).append(
                HospitalQueueCase(ktas_level=ktas, transport_status=status)
            )
        return result

    def count_active_by_hospital(self, hospital_id) -> int:
        return (
            self.db.query(HospitalAssignment)
            .join(EmergencyCase, HospitalAssignment.case_id == EmergencyCase.case_id)
            .filter(
                HospitalAssignment.hospital_id == hospital_id,
                EmergencyCase.status == "active",
            )
            .count()
        )
