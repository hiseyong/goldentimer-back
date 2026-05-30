from sqlalchemy.orm import Session

from app.models.hospital import Hospital
from app.repositories.hospital import HospitalRepository
from app.schemas.hospital import NearbyHospitalDetail
from app.services.hospital_recommendation import find_nearby_hospitals


class HospitalService:
    def __init__(self, db: Session):
        self.repo = HospitalRepository(db)

    def get_nearby_hospitals(
        self,
        latitude: float,
        longitude: float,
        limit: int = 5,
    ) -> list[NearbyHospitalDetail]:
        hospitals = self.repo.list_for_recommendation()
        nearby = find_nearby_hospitals(hospitals, latitude, longitude, limit=limit)
        return [_to_detail(hospital, distance_km) for hospital, distance_km in nearby]


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
