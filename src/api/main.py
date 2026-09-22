from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI

from src.core.cache.redis import adapter as redis_adapter
from src.core.communications.smtp import adapter as smtp_adapter
from src.core.cryptography.bcrypt import adapter as bcrypt_adapter
from src.core.cryptography.fernet import adapter as fernet_adapter
from src.core.exception_handlers import register_exception_handlers
from src.core.sessions.config import SessionCookieConfig
from src.core.sessions.tokens import SessionTokenService
from src.core.settings import settings
from src.core.tasks.broker import broker

from .v1.routes import router as v1_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.encryption_service = fernet_adapter.FernetEncryptionService(
        settings.CRYPTOGRAPHY_FERNET_KEY
    )
    app.state.hashing_service = bcrypt_adapter.BcryptHashingService()
    app.state.cache_store = redis_adapter.RedisCacheStore(settings.REDIS_URL)
    app.state.email_sender = smtp_adapter.SmtpEmailSender()
    app.state.session_token_service = SessionTokenService(
        session_ttl=timedelta(seconds=settings.SESSION_TTL_SECONDS),
    )
    app.state.session_cookie_config = SessionCookieConfig(
        name=settings.SESSION_COOKIE_NAME,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        max_age_seconds=settings.SESSION_TTL_SECONDS,
    )

    if not broker.is_worker_process:
        await broker.startup()

    yield

    if not broker.is_worker_process:
        await broker.shutdown()
    await app.state.cache_store.close_connection()


app = FastAPI(lifespan=lifespan)
register_exception_handlers(app)
app.include_router(v1_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
