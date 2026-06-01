"""Audit API routes."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health-complete")
async def health_complete() -> dict[str, str]:
    """Complete health check for the audit module."""
    return {"status": "ok"}
