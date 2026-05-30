import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.hospital import (
    HospitalPatientStatusResponse,
    HospitalWaitTimeResponse,
    NearbyHospitalsResponse,
)
from app.services.hospital import HospitalService

router = APIRouter()


@router.get("/nearby", response_model=NearbyHospitalsResponse)
def get_nearby_hospitals(
    latitude: float = Query(..., ge=-90, le=90, description="Client latitude"),
    longitude: float = Query(..., ge=-180, le=180, description="Client longitude"),
    limit: int = Query(5, ge=1, le=20, description="Number of nearby hospitals to return"),
    db: Session = Depends(get_db),
) -> NearbyHospitalsResponse:
    """Return detailed status of the nearest hospitals from the current location."""
    service = HospitalService(db)
    hospitals = service.get_nearby_hospitals(latitude, longitude, limit=limit)

    if not hospitals:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No hospitals available in database",
        )

    return NearbyHospitalsResponse(
        latitude=latitude,
        longitude=longitude,
        count=len(hospitals),
        hospitals=hospitals,
    )


@router.get("/{hospital_id}/patients", response_model=HospitalPatientStatusResponse)
def get_hospital_patient_status(
    hospital_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> HospitalPatientStatusResponse:
    """Return incoming active patient status for a specific hospital."""
    return HospitalService(db).get_patient_status(hospital_id)


@router.get("/{hospital_id}/wait-time", response_model=HospitalWaitTimeResponse)
def get_hospital_wait_time(
    hospital_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> HospitalWaitTimeResponse:
    """Return estimated ER wait time for a specific hospital."""
    return HospitalService(db).get_wait_time(hospital_id)
