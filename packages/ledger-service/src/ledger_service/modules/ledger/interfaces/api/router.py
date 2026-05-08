from fastapi import APIRouter

router = APIRouter()


@router.get("/health-complete")
async def health_complete():
    return {"status": "ok"}
