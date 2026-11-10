import importlib
import pkgutil

from app.models.audit import AuditLog
from app.models.catalog import Part, Service, ServiceCategory, ServiceLocationPrice, WorkPost
from app.models.client import Client, Vehicle
from app.models.enums import Role
from app.models.location import Location
from app.models.user import RefreshSession, User, UserLocation

__all__ = [
    "AuditLog",
    "Client",
    "Location",
    "Part",
    "RefreshSession",
    "Role",
    "Service",
    "ServiceCategory",
    "ServiceLocationPrice",
    "User",
    "UserLocation",
    "Vehicle",
    "WorkPost",
]


# Авто-регистрация моделей: новый файл в app/models подхватывается без правки этого модуля.
for _info in pkgutil.iter_modules(__path__):
    # Имя модуля берётся из списка файлов пакета (pkgutil), не из ввода пользователя.
    importlib.import_module(f"{__name__}.{_info.name}")  # nosemgrep
