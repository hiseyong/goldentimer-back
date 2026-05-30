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
