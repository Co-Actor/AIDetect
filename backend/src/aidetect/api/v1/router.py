from fastapi import APIRouter

from aidetect.api.v1 import detections, feedback, health, rewrite, rubric

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(detections.router, prefix="/detections", tags=["detections"])
api_router.include_router(feedback.router, prefix="/feedback", tags=["feedback"])
api_router.include_router(rewrite.router, prefix="/rewrite", tags=["rewrite"])
api_router.include_router(rubric.router, prefix="/rubric", tags=["rubric"])
