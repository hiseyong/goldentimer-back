import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.hospital import Hospital
from app.repositories.hospital import HospitalRepository
from app.repositories.patient import HospitalAssignmentRepository
from app.schemas.hospital import (
    HospitalPatientStatusResponse,
    HospitalWaitTimeResponse,
    IncomingPatientStatus,
    NearbyHospitalDetail,
    WaitTimeBreakdown,
)
from app.services.hospital_recommendation import find_nearby_hospitals
from app.services.hospital_wait_time import estimate_er_wait_time


class HospitalService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = HospitalRepository(db)
        self.assignment_repo = HospitalAssignmentRepository(db)

    def get_nearby_hospitals(
        self,
        latitude: float,
        longitude: float,
        limit: int = 5,
    ) -> list[NearbyHospitalDetail]:
        hospitals = self.repo.list_for_recommendation()
        nearby = find_nearby_hospitals(hospitals, latitude, longitude, limit=limit)
        return [_to_detail(hospital, distance_km) for hospital, distance_km in nearby]

    def _get_hospital_or_404(self, hospital_id: uuid.UUID):
        hospital = self.repo.get_by_id(hospital_id)
        if hospital is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Hospital not found: {hospital_id}",
            )
        return hospital

    def get_patient_status(
        self, hospital_id: uuid.UUID
    ) -> HospitalPatientStatusResponse:
        hospital = self._get_hospital_or_404(hospital_id)
        rows = self.assignment_repo.list_active_by_hospital(hospital_id)

        patients = [
            IncomingPatientStatus(
                assignment_id=assignment.assignment_id,
                case_id=case.case_id,
                patient_id=patient.patient_id,
                patient_name=patient.name,
                chief_complaint=case.chief_complaint,
                ktas_level=case.ktas_level,
                transport_status=case.transport_status,
                case_status=case.status,
                acceptance_status=assignment.acceptance_status,
                estimated_arrival_minutes=assignment.estimated_arrival_minutes,
                assigned_at=assignment.assigned_at,
            )
            for assignment, case, patient in rows
        ]

        count = len(patients)
        if count == 0:
            summary = (
                f"{hospital.hospital_name}으로 배정된 유입 예정 활성 환자가 없습니다. "
                f"응급실 가용 병상 {hospital.total_er_beds}개."
            )
        else:
            in_transit = sum(1 for p in patients if p.transport_status == "in_transit")
            summary = (
                f"{hospital.hospital_name} 유입 예정 활성 환자 {count}명 "
                f"(이송 중 {in_transit}명). 응급실 가용 병상 {hospital.total_er_beds}개."
            )

        return HospitalPatientStatusResponse(
            hospital_id=hospital.hospital_id,
            hospital_name=hospital.hospital_name,
            total_er_beds=hospital.total_er_beds,
            active_incoming_count=count,
            patients=patients,
            summary=summary,
        )

    def get_wait_time(self, hospital_id: uuid.UUID) -> HospitalWaitTimeResponse:
        hospital = self._get_hospital_or_404(hospital_id)
        rows = self.assignment_repo.list_active_by_hospital(hospital_id)
        ktas_levels = [case.ktas_level for _, case, _ in rows]

        estimate = estimate_er_wait_time(
            hospital,
            active_incoming_count=len(rows),
            ktas_levels=ktas_levels,
        )

        return HospitalWaitTimeResponse(
            hospital_id=hospital.hospital_id,
            hospital_name=hospital.hospital_name,
            total_er_beds=hospital.total_er_beds,
            active_incoming_count=len(rows),
            estimated_wait_minutes=estimate.estimated_wait_minutes,
            wait_level=estimate.wait_level,
            breakdown=WaitTimeBreakdown(
                bed_pressure_minutes=estimate.bed_pressure_minutes,
                incoming_queue_minutes=estimate.incoming_queue_minutes,
                severity_adjustment_minutes=estimate.severity_adjustment_minutes,
            ),
            guidance=estimate.guidance,
            data_as_of=hospital.updated_at,
        )


def _to_detail(hospital: Hospital, distance_km: float) -> NearbyHospitalDetail:
    return NearbyHospitalDetail(
        hospital_id=hospital.hospital_id,
        hpid=hospital.hpid,
        hospital_name=hospital.hospital_name,
        address=hospital.address,
        stage1=hospital.stage1,
        stage2=hospital.stage2,
        latitude=float(hospital.latitude),
        longitude=float(hospital.longitude),
        distance_km=round(distance_km, 2),
        total_er_beds=hospital.total_er_beds,
        er_beds_available=hospital.total_er_beds > 0,
        trauma_center=hospital.trauma_center,
        stroke_center=hospital.stroke_center,
        cardiac_center=hospital.cardiac_center,
        updated_at=hospital.updated_at,
    )
