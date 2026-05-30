from sqlalchemy.orm import Session

from app.models.hospital import Hospital


class HospitalRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, hospital_id) -> Hospital | None:
        return self.db.get(Hospital, hospital_id)

    def get_first(self) -> Hospital | None:
        return self.db.query(Hospital).first()

    def list_all(self) -> list[Hospital]:
        return self.db.query(Hospital).all()
