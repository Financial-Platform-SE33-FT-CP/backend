"""AR/AP API router."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health-complete")
async def health_complete():
    """Combined health check for the AR/AP module."""
    return {"status": "ok"}
