from pydantic_settings import BaseSettings, SettingsConfigDict

from .exceptions import InternalServerError
from .sessions.config import SameSitePolicy


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str
    CRYPTOGRAPHY_FERNET_KEY: str
    SESSION_COOKIE_NAME: str = "session"
    SESSION_COOKIE_SECURE: bool = True
    SESSION_COOKIE_SAMESITE: SameSitePolicy = "lax"
    SESSION_TTL_SECONDS: int = 60 * 60 * 24 * 7
    REGISTRATION_VERIFICATION_CODE_TTL_SECONDS: int = 60 * 15
    REGISTRATION_VERIFICATION_MAX_ATTEMPTS: int = 5
    REGISTRATION_VERIFICATION_MAX_REQUESTS: int = 3
    REGISTRATION_VERIFICATION_COOLDOWN_SECONDS: int = 60 * 15
    REDIS_URL: str

    REQUEST_SIGNING_SECRET: str
    REQUEST_SIGNATURE_WINDOW_SECONDS: int = 30

    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None

    def require_smtp_host(self) -> str:
        if not self.SMTP_HOST:
            raise InternalServerError(
                message="Unable to process request at this time",
                code="smtp_host_not_configured",
            )
        return self.SMTP_HOST

    def require_smtp_user(self) -> str:
        if not self.SMTP_USER:
            raise InternalServerError(
                message="Unable to process request at this time",
                code="smtp_user_not_configured",
            )
        return self.SMTP_USER

    def require_smtp_password(self) -> str:
        if not self.SMTP_PASSWORD:
            raise InternalServerError(
                message="Unable to process request at this time",
                code="smtp_password_not_configured",
            )
        return self.SMTP_PASSWORD


settings = Settings()
