import uuid

from fastapi import APIRouter

from app.api.deps import Client, Director, SessionDep, Staff
from app.schemas.catalog import CategoryCreate, CategoryRead, CategoryUpdate, Department
from app.services import catalog as svc

router = APIRouter(prefix="/service-categories", tags=["catalog"])


@router.get("", response_model=list[CategoryRead])
async def list_categories(
    _: Staff,
    session: SessionDep,
    department: Department | None = None,
    is_active: bool | None = None,
) -> list[CategoryRead]:
    return await svc.list_categories(session, department=department, is_active=is_active)


@router.post("", response_model=CategoryRead, status_code=201)
async def create_category(
    data: CategoryCreate, actor: Director, session: SessionDep, client: Client
) -> CategoryRead:
    return await svc.create_category(session, actor, data, client)


@router.patch("/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: uuid.UUID,
    data: CategoryUpdate,
    actor: Director,
    session: SessionDep,
    client: Client,
) -> CategoryRead:
    return await svc.update_category(session, actor, category_id, data, client)
