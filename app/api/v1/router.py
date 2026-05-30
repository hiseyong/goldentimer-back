from fastapi import APIRouter

from app.api.v1.endpoints import assignment, health

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(assignment.router, prefix="/assignments", tags=["assignments"])
