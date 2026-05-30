import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.hospital import Hospital
from app.repositories.hospital import HospitalRepository
from app.repositories.patient import HospitalAssignmentRepository
from app.schemas.hospital import (
    HospitalPatientStatusResponse,
    HospitalRecommendResponse,
    HospitalWaitTimeResponse,
    IncomingPatientStatus,
    NearbyHospitalDetail,
    WaitTimeBreakdown,
)
from app.services.assignment_message import build_assignment_guidance_message
from app.services.hospital_recommendation import (
    estimate_travel_minutes,
    find_nearby_hospitals,
    haversine_km,
    recommend_hospital_for_analysis,
)
from app.services.hospital_wait_time import estimate_er_wait_time
from app.services.transcript_analysis import TranscriptAnalyzer


class HospitalService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = HospitalRepository(db)
        self.assignment_repo = HospitalAssignmentRepository(db)
        self.transcript_analyzer = TranscriptAnalyzer()

    def _build_wait_estimates(self, hospitals: list[Hospital]) -> dict:
        queue_map = self.assignment_repo.map_active_queue_cases_by_hospital()
        return {
            hospital.hospital_id: estimate_er_wait_time(
                hospital, queue_map.get(hospital.hospital_id, [])
            )
            for hospital in hospitals
        }

    def get_nearby_hospitals(
        self,
        latitude: float,
        longitude: float,
        limit: int = 5,
    ) -> list[NearbyHospitalDetail]:
        hospitals = self.repo.list_for_recommendation()
        wait_estimates = self._build_wait_estimates(hospitals)
        nearby = find_nearby_hospitals(
            hospitals, latitude, longitude, limit=limit, wait_estimates=wait_estimates
        )
        return [
            _to_detail(hospital, distance_km, wait_estimates.get(hospital.hospital_id))
            for hospital, distance_km in nearby
        ]

    def recommend_hospital(
        self,
        latitude: float,
        longitude: float,
        symptoms: str,
    ) -> HospitalRecommendResponse:
        analysis = self.transcript_analyzer.analyze(symptoms)
        needs = analysis.needs
        ktas_level = analysis.ktas_level

        hospitals = self.repo.list_for_recommendation()
        wait_estimates = self._build_wait_estimates(hospitals)

        hospital = recommend_hospital_for_analysis(
            hospitals,
            latitude,
            longitude,
            analysis,
            wait_estimates=wait_estimates,
            settings=self.transcript_analyzer.settings,
            symptoms=symptoms,
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
            latitude,
            longitude,
            float(hospital.latitude),
            float(hospital.longitude),
        )
        wait = wait_estimates[hospital.hospital_id]
        detail = _to_detail(hospital, distance_km, wait)
        message = build_assignment_guidance_message(
            transcript=symptoms,
            needs=needs,
            hospital_name=hospital.hospital_name,
            distance_km=distance_km,
            wait=wait,
            recommend_only=True,
            ktas_level=ktas_level,
            clinical_summary=analysis.clinical_summary,
            settings=self.transcript_analyzer.settings,
        )

        return HospitalRecommendResponse(
            latitude=latitude,
            longitude=longitude,
            symptoms=symptoms,
            inferred_capabilities=needs.english_summary(),
            ktas_level=ktas_level,
            hospital=detail,
            message=message,
        )

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
                f"No active incoming patients assigned to {hospital.hospital_name}. "
                f"{hospital.total_er_beds} ER beds available."
            )
        else:
            in_transit = sum(1 for p in patients if p.transport_status == "in_transit")
            summary = (
                f"{hospital.hospital_name}: {count} active incoming patient(s) "
                f"({in_transit} in transit). {hospital.total_er_beds} ER beds available."
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
        queue_cases = self.assignment_repo.list_active_queue_cases_by_hospital(hospital_id)

        estimate = estimate_er_wait_time(hospital, queue_cases)
        incoming_count = sum(
            1 for case in queue_cases if case.transport_status == "in_transit"
        )

        return HospitalWaitTimeResponse(
            hospital_id=hospital.hospital_id,
            hospital_name=hospital.hospital_name,
            total_er_beds=hospital.total_er_beds,
            active_incoming_count=incoming_count,
            estimated_wait_minutes=estimate.estimated_wait_minutes,
            wait_level=estimate.wait_level,
            breakdown=WaitTimeBreakdown(
                bed_pressure_minutes=estimate.bed_pressure_minutes,
                existing_patient_minutes=estimate.existing_patient_minutes,
                incoming_queue_minutes=estimate.incoming_queue_minutes,
            ),
            guidance=estimate.guidance,
            data_as_of=hospital.updated_at,
        )


def _to_detail(
    hospital: Hospital,
    distance_km: float,
    wait=None,
) -> NearbyHospitalDetail:
    estimated_wait = wait.estimated_wait_minutes if wait else 60
    wait_level = wait.wait_level if wait else "moderate"
    travel_minutes = estimate_travel_minutes(distance_km)
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
        estimated_travel_minutes=travel_minutes,
        total_eta_minutes=travel_minutes + estimated_wait,
        total_er_beds=hospital.total_er_beds,
        er_beds_available=hospital.total_er_beds > 0,
        estimated_wait_minutes=estimated_wait,
        wait_level=wait_level,
        trauma_center=hospital.trauma_center,
        stroke_center=hospital.stroke_center,
        cardiac_center=hospital.cardiac_center,
        updated_at=hospital.updated_at,
    )
