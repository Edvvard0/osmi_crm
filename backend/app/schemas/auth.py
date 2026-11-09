from pydantic import Field

from app.core.types import Login
from app.schemas.common import Strict
from app.schemas.user import UserRead


class LoginRequest(Strict):
    login: Login
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(Strict):
    access_token: str
    expires_in: int
    user: UserRead


class ChangePassword(Strict):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)
