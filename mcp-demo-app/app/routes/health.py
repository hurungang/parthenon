from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings

health_router = APIRouter()


@health_router.get("/health")
async def health_check() -> JSONResponse:
    return JSONResponse({"status": "ok", "slug": settings.APP_SLUG})
