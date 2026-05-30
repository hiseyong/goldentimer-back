from sqlalchemy.orm import Session

from app.models.hospital import Hospital


class HospitalRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, hospital_id) -> Hospital | None:
        return self.db.get(Hospital, hospital_id)

    def get_by_hpid(self, hpid: str) -> Hospital | None:
        return self.db.query(Hospital).filter(Hospital.hpid == hpid).first()

    def get_first(self) -> Hospital | None:
        return self.db.query(Hospital).first()

    def list_all(self) -> list[Hospital]:
        return self.db.query(Hospital).all()

    def list_for_recommendation(self) -> list[Hospital]:
        return self.db.query(Hospital).filter(Hospital.hpid.isnot(None)).all()

    def list_for_rotation(self) -> list[Hospital]:
        return (
            self.db.query(Hospital)
            .filter(Hospital.hpid.isnot(None))
            .order_by(Hospital.hpid)
            .all()
        )

    def count_with_hpid(self) -> int:
        return (
            self.db.query(Hospital)
            .filter(Hospital.hpid.isnot(None))
            .count()
        )

    def list_distinct_regions(self) -> list[tuple[str, str]]:
        rows = (
            self.db.query(Hospital.stage1, Hospital.stage2)
            .filter(Hospital.stage1.isnot(None), Hospital.stage2.isnot(None))
            .distinct()
            .all()
        )
        return [(row[0], row[1]) for row in rows if row[0] and row[1]]

    def upsert_from_api(
        self,
        *,
        hpid: str,
        hospital_name: str,
        address: str,
        stage1: str,
        stage2: str,
        latitude: float,
        longitude: float,
        total_er_beds: int,
        trauma_center: bool,
        stroke_center: bool,
        cardiac_center: bool,
    ) -> Hospital:
        hospital = self.get_by_hpid(hpid)
        if hospital is None:
            hospital = Hospital(hpid=hpid)
            self.db.add(hospital)

        hospital.hospital_name = hospital_name
        hospital.address = address
        hospital.stage1 = stage1
        hospital.stage2 = stage2
        hospital.latitude = latitude
        hospital.longitude = longitude
        hospital.total_er_beds = total_er_beds
        hospital.trauma_center = trauma_center
        hospital.stroke_center = stroke_center
        hospital.cardiac_center = cardiac_center
        self.db.flush()
        return hospital

    def update_beds(
        self,
        hospital: Hospital,
        *,
        total_er_beds: int,
        stroke_center: bool,
        cardiac_center: bool,
    ) -> Hospital:
        hospital.total_er_beds = total_er_beds
        hospital.stroke_center = stroke_center
        hospital.cardiac_center = cardiac_center
        return hospital

    def commit(self) -> None:
        self.db.commit()
