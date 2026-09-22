from typing import Any

from starlette.requests import Request

from src.core.cache.ports import CacheStore
from src.core.communications.ports import EmailSender
from src.core.cryptography.ports import EncryptionService, HashingService
from src.core.exceptions import InternalServerError
from src.core.sessions.config import SessionCookieConfig
from src.core.sessions.tokens import SessionTokenService


def _from_app_state(request: Request, attribute: str, code: str) -> Any:
    value = getattr(request.app.state, attribute, None)
    if value is None:
        raise InternalServerError(
            message="Unable to process request at this time",
            code=code,
        )
    return value


def get_encryption_service(request: Request) -> EncryptionService:
    return _from_app_state(request, "encryption_service", "encryption_service_missing")


def get_hashing_service(request: Request) -> HashingService:
    return _from_app_state(request, "hashing_service", "hashing_service_missing")


def get_session_token_service(request: Request) -> SessionTokenService:
    return _from_app_state(request, "session_token_service", "session_token_service_missing")


def get_session_cookie_config(request: Request) -> SessionCookieConfig:
    return _from_app_state(request, "session_cookie_config", "session_cookie_config_missing")


def get_cache_store(request: Request) -> CacheStore:
    return _from_app_state(request, "cache_store", "cache_store_missing")


def get_email_sender(request: Request) -> EmailSender:
    return _from_app_state(request, "email_sender", "email_sender_missing")

