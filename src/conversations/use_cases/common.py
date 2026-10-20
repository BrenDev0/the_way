from src.core.exceptions import NotFoundError


def not_found() -> NotFoundError:
    return NotFoundError(message="Conversation not found", code="conversation_not_found")
