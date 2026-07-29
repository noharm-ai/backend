"""Service: help text related operations"""

from decorators.has_permission_decorator import Permission, has_permission
from models.main import User
from repository import help_text_repository


@has_permission(Permission.READ_BASIC_FEATURES)
def get_help_text(key: str):
    """Get the help text content for a given key."""
    record = help_text_repository.get(key)

    return {"key": key, "content": record.content if record else None}


@has_permission(Permission.WRITE_HELP_TEXT)
def update_help_text(key: str, content: str | None, user_context: User):
    """Create or update the help text content for a given key."""
    record = help_text_repository.upsert(key, content, user_context.id)

    return {"key": key, "content": record.content}
