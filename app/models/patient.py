import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str | None] = mapped_column(String(100))
    age: Mapped[int | None] = mapped_column(Integer)
    sex: Mapped[str | None] = mapped_column(String(10))
    nationality: Mapped[str | None] = mapped_column(String(50))
    language_preference: Mapped[str | None] = mapped_column(String(50))
    blood_type: Mapped[str | None] = mapped_column(String(5))
    emergency_contact_name: Mapped[str | None] = mapped_column(String(100))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    emergency_cases = relationship("EmergencyCase", back_populates="patient")


class EmergencyCase(Base):
    __tablename__ = "emergency_cases"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False
    )
    chief_complaint: Mapped[str | None] = mapped_column(Text)
    detailed_description: Mapped[str | None] = mapped_column(Text)
    suspected_diagnosis: Mapped[str | None] = mapped_column(Text)
    injury_mechanism: Mapped[str | None] = mapped_column(Text)
    ktas_level: Mapped[int | None] = mapped_column(Integer)
    consciousness_level: Mapped[str | None] = mapped_column(String(20))
    incident_location: Mapped[str | None] = mapped_column(Text)
    transport_status: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    patient = relationship("Patient", back_populates="emergency_cases")
    hospital_assignments = relationship(
        "HospitalAssignment", back_populates="emergency_case"
    )
