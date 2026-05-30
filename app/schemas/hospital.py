import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class HospitalResponse(BaseModel):
    hospital_id: uuid.UUID
    hospital_name: str
    address: str
    latitude: float
    longitude: float
    total_er_beds: int
    trauma_center: bool
    stroke_center: bool
    cardiac_center: bool

    model_config = {"from_attributes": True}


class NearbyHospitalDetail(BaseModel):
    hospital_id: uuid.UUID
    hpid: str | None
    hospital_name: str
    address: str
    stage1: str | None
    stage2: str | None
    latitude: float
    longitude: float
    distance_km: float = Field(description="Distance from client location in km")
    estimated_travel_minutes: int = Field(
        description="Estimated ambulance travel time in minutes"
    )
    total_eta_minutes: int = Field(
        description="Estimated travel + ER wait time in minutes"
    )
    total_er_beds: int = Field(description="Available ER beds from realtime API (hvec)")
    er_beds_available: bool = Field(description="Whether ER beds > 0")
    estimated_wait_minutes: int = Field(description="Estimated ER wait time in minutes")
    wait_level: str = Field(description="low | moderate | high | severe")
    trauma_center: bool
    stroke_center: bool
    cardiac_center: bool
    updated_at: datetime | None = Field(
        default=None, description="Last bed info sync time (UTC)"
    )

    model_config = {"from_attributes": True}


class NearbyHospitalsResponse(BaseModel):
    latitude: float
    longitude: float
    count: int
    hospitals: list[NearbyHospitalDetail]


class HospitalRecommendRequest(BaseModel):
    latitude: float = Field(
        ...,
        ge=-90,
        le=90,
        description="Client latitude in decimal degrees",
        examples=[37.4979],
    )
    longitude: float = Field(
        ...,
        ge=-180,
        le=180,
        description="Client longitude in decimal degrees",
        examples=[127.0276],
    )
    symptoms: str = Field(
        ...,
        min_length=1,
        description="Chief complaint or symptom description (Korean or English)",
        examples=["60대 남성, 흉통 및 호흡곤란"],
    )


class HospitalRecommendResponse(BaseModel):
    latitude: float
    longitude: float
    symptoms: str
    inferred_capabilities: str = Field(
        description="Inferred specialty needs: trauma / stroke / cardiac, or general"
    )
    ktas_level: int = Field(description="Inferred KTAS triage level (1–5 scale used here: 1–3)")
    hospital: NearbyHospitalDetail
    message: str = Field(description="Human-readable recommendation summary")


class IncomingPatientStatus(BaseModel):
    assignment_id: uuid.UUID
    case_id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str | None
    chief_complaint: str | None
    ktas_level: int | None
    transport_status: str | None
    case_status: str | None
    acceptance_status: str | None
    estimated_arrival_minutes: int | None
    assigned_at: datetime


class HospitalPatientStatusResponse(BaseModel):
    hospital_id: uuid.UUID
    hospital_name: str
    total_er_beds: int
    active_incoming_count: int
    patients: list[IncomingPatientStatus]
    summary: str


class WaitTimeBreakdown(BaseModel):
    bed_pressure_minutes: int = Field(description="Estimated delay from ER bed availability")
    existing_patient_minutes: int = Field(
        description="Delay from patients already at the hospital, weighted by KTAS severity"
    )
    incoming_queue_minutes: int = Field(
        description="Delay from incoming patients, weighted by KTAS severity"
    )


class HospitalWaitTimeResponse(BaseModel):
    hospital_id: uuid.UUID
    hospital_name: str
    total_er_beds: int
    active_incoming_count: int
    estimated_wait_minutes: int
    wait_level: str = Field(description="low | moderate | high | severe")
    breakdown: WaitTimeBreakdown
    guidance: str
    data_as_of: datetime | None


class EmergencyCaseResponse(BaseModel):
    case_id: uuid.UUID
    patient_id: uuid.UUID
    chief_complaint: str | None
    detailed_description: str | None
    ktas_level: int | None
    transport_status: str | None
    status: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
