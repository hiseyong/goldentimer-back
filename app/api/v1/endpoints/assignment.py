from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import check_database_connection, get_db
from app.schemas.assignment import VoiceAssignmentRequest, VoiceAssignmentResponse
from app.services.assignment import AssignmentService

router = APIRouter()


@router.post("", response_model=VoiceAssignmentResponse)
def create_voice_assignment(
    request: VoiceAssignmentRequest,
    db: Session = Depends(get_db),
) -> VoiceAssignmentResponse:
    """
    응급대원 음성인식 텍스트를 수신하여 환자를 등록하고 병원을 배정합니다.

    현재는 LLM 분석 및 실제 병원 탐색 없이 dummy 데이터를 반환합니다.
    """
    service = AssignmentService(db)
    return service.process_voice_assignment(request)
