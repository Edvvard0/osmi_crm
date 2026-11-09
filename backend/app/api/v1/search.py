from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import SessionDep, Staff
from app.core.errors import AppError
from app.schemas.client import SearchHit
from app.services import search as svc

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[SearchHit])
async def global_search(
    _: Staff,
    session: SessionDep,
    q: Annotated[str, Query(max_length=100)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[SearchHit]:
    term = svc.clean_term(q)
    if len(term) < 2:
        raise AppError(422, "validation_error", {"q": "too_short"})
    return await svc.global_search(session, term, limit)
