from fastapi import APIRouter

from app.api.v1.endpoints import assignment, health, hospitals

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(assignment.router, prefix="/assignments", tags=["assignments"])
api_router.include_router(hospitals.router, prefix="/hospitals", tags=["hospitals"])
