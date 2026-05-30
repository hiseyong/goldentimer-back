import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class HospitalAssignment(Base):
    __tablename__ = "hospital_assignments"

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emergency_cases.case_id"), nullable=False
    )
    hospital_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hospitals.hospital_id"), nullable=False
    )
    recommendation_rank: Mapped[int | None] = mapped_column(Integer)
    estimated_arrival_minutes: Mapped[int | None] = mapped_column(Integer)
    acceptance_status: Mapped[str | None] = mapped_column(String(30))
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    emergency_case = relationship("EmergencyCase", back_populates="hospital_assignments")
    hospital = relationship("Hospital")
