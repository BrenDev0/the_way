from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI

from src.api.v1.routes import router as v1_router
from src.core.cache.redis.adapters import RedisCacheStore
from src.core.cryptography.bcrypt.adapters import BcryptHashingService
from src.core.cryptography.fernet.adapters import FernetEncryptionService
from src.core.exception_handlers import register_exception_handlers
from src.core.sessions.config import SessionCookieConfig
from src.core.sessions.tokens import SessionTokenService
from src.core.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.encryption_service = FernetEncryptionService(settings.CRYPTOGRAPHY_FERNET_KEY)
    app.state.hashing_service = BcryptHashingService()
    app.state.cache_store = RedisCacheStore(settings.REDIS_URL)
    app.state.session_token_service = SessionTokenService(
        session_ttl=timedelta(seconds=settings.SESSION_TTL_SECONDS),
    )
    app.state.session_cookie_config = SessionCookieConfig(
        name=settings.SESSION_COOKIE_NAME,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        max_age_seconds=settings.SESSION_TTL_SECONDS,
    )
    yield
    await app.state.cache_store.close_connection()


app = FastAPI(lifespan=lifespan)
register_exception_handlers(app)
app.include_router(v1_router, prefix="/api/v1")
