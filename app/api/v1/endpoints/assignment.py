from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.assignment import VoiceAssignmentRequest, VoiceAssignmentResponse
from app.services.assignment import AssignmentService

router = APIRouter()


@router.post("", response_model=VoiceAssignmentResponse)
def create_voice_assignment(
    request: VoiceAssignmentRequest,
    db: Session = Depends(get_db),
) -> VoiceAssignmentResponse:
    """
    Receive paramedic voice-recognition text and client location,
    register the patient, and recommend the nearest suitable hospital from DB.
    """
    service = AssignmentService(db)
    return service.process_voice_assignment(request)
