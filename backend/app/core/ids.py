import uuid

import uuid_utils


def new_id() -> uuid.UUID:
    """UUIDv7: упорядочен по времени, хорошо индексируется."""
    return uuid.UUID(bytes=uuid_utils.uuid7().bytes)
