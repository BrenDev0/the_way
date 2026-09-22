from typing import Annotated

from starlette.requests import Request
from taskiq import TaskiqDepends

from src.api import dependencies as api_dependencies
from src.core.cache.ports import CacheStore
from src.core.communications.ports import EmailSender
from src.core.cryptography.ports import EncryptionService, HashingService
from src.core.sessions.tokens import SessionTokenService

WorkerRequest = Annotated[Request, TaskiqDepends()]


def get_cache_store(request: WorkerRequest) -> CacheStore:
    return api_dependencies.get_cache_store(request)


def get_email_sender(request: WorkerRequest) -> EmailSender:
    return api_dependencies.get_email_sender(request)


def get_encryption_service(request: WorkerRequest) -> EncryptionService:
    return api_dependencies.get_encryption_service(request)


def get_hashing_service(request: WorkerRequest) -> HashingService:
    return api_dependencies.get_hashing_service(request)


def get_session_token_service(request: WorkerRequest) -> SessionTokenService:
    return api_dependencies.get_session_token_service(request)
