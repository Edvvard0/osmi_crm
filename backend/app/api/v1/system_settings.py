from fastapi import APIRouter

from app.api.deps import Client, Director, SessionDep
from app.schemas.system_settings import SettingsPatch, SettingsRead
from app.services import settings as svc

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsRead)
async def get_settings(_: Director, session: SessionDep) -> SettingsRead:
    return await svc.read_settings(session)


@router.patch("", response_model=SettingsRead)
async def patch_settings(
    data: SettingsPatch, actor: Director, session: SessionDep, client: Client
) -> SettingsRead:
    return await svc.update_settings(session, actor.id, data, client)
