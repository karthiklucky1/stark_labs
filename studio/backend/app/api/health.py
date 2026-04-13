"""
Mark II Studio — Health Endpoint
"""
from fastapi import APIRouter

from app.settings import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "product": settings.product_name,
        "profiles": settings.supported_profiles,
    }
