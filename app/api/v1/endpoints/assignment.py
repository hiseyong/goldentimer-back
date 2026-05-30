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
    register the patient, and assign a hospital.

    Currently returns dummy data without LLM analysis or real hospital search.
    """
    service = AssignmentService(db)
    return service.process_voice_assignment(request)
