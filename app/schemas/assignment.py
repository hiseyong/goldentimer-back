from pydantic import BaseModel, Field

from app.schemas.hospital import EmergencyCaseResponse, HospitalResponse


class ClientLocation(BaseModel):
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
    address: str | None = Field(
        default=None,
        description="Optional human-readable address from the client",
        examples=["123 Gangnam-daero, Gangnam-gu, Seoul"],
    )


class VoiceAssignmentRequest(BaseModel):
    transcript: str = Field(
        ...,
        min_length=1,
        description="Patient information text converted from paramedic voice recognition",
        examples=[
            "Male in his 60s, chest pain and shortness of breath, alert, en route to 123 Gangnam-daero"
        ],
    )
    client_location: ClientLocation = Field(
        ...,
        description="Current client (ambulance/paramedic app) location",
    )
    paramedic_id: str | None = Field(
        default=None,
        description="Paramedic identifier",
        examples=["EMT-001"],
    )


class VoiceAssignmentResponse(BaseModel):
    emergency_case: EmergencyCaseResponse
    hospital: HospitalResponse
    message: str = "Hospital assignment completed."
