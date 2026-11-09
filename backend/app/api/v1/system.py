from fastapi import APIRouter

from app.api.deps import Director, SessionDep
from app.schemas.system import SystemStatus
from app.services import system_status

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status", response_model=SystemStatus)
async def get_status(_: Director, session: SessionDep) -> SystemStatus:
    """Состояние системы для блока «Система» на D-01 (только руководитель)."""
    return await system_status.build_status(session)
