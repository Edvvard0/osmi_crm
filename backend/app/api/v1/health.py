from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> JSONResponse:
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return JSONResponse(
        {"status": "ok" if db_ok else "degraded", "db": db_ok},
        status_code=200 if db_ok else 503,
    )
