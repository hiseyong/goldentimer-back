from pydantic import BaseModel, Field

from app.schemas.hospital import EmergencyCaseResponse, HospitalResponse


class VoiceAssignmentRequest(BaseModel):
    transcript: str = Field(
        ...,
        min_length=1,
        description="응급대원 음성인식으로 변환된 환자 정보 텍스트",
        examples=[
            "60대 남성, 가슴 통증과 호흡곤란, 의식 명료, 현재 강남대로 123번지 이동 중"
        ],
    )
    paramedic_id: str | None = Field(
        default=None,
        description="응급대원 식별자",
        examples=["EMT-001"],
    )


class VoiceAssignmentResponse(BaseModel):
    emergency_case: EmergencyCaseResponse
    hospital: HospitalResponse
    message: str = "병원 배정이 완료되었습니다. (dummy 데이터)"
