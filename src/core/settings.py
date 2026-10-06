
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
    DESKTOP_SESSION_TTL_SECONDS: int = 60 * 60 * 24 * 30
    DESKTOP_LOGIN_WINDOW_SECONDS: int = 60 * 15
    DESKTOP_LOGIN_MAX_FAILURES_PER_EMAIL: int = 5
    DESKTOP_LOGIN_MAX_FAILURES_PER_IP: int = 30
    REDIS_URL: str

    REQUEST_SIGNING_SECRET: str
    REQUEST_SIGNATURE_WINDOW_SECONDS: int = 30

    TASKIQ_BROKER_URL: str
    TASKIQ_RESULT_BACKEND_URL: str | None = None
    TASKIQ_RESULT_TTL_SECONDS: int = 60 * 60
    TASKIQ_STREAM_NAME: str = "taskiq:stream"
    TASKIQ_CONSUMER_GROUP: str = "taskiq:workers"
    # How long XREADGROUP waits on Redis for a message, and how long a read on that socket
    # may take. The read must outlast the wait by a wide margin: redis-py's default (5s)
    # left 3s, and one stretch of synchronous work in a task was enough to time the read
    # out -- which kills the worker process and the turn it was running.
    TASKIQ_XREAD_BLOCK_MS: int = 2000
    TASKIQ_SOCKET_TIMEOUT_SECONDS: float = 60

    def taskiq_result_backend_url(self) -> str:
        return self.TASKIQ_RESULT_BACKEND_URL or self.TASKIQ_BROKER_URL

    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None

    BUCKET_NAME: str | None = None
    BUCKET_PREFIX: str = "the_way"
    BUCKET_ENDPOINT: str | None = None
    # The bucket's address as a client reaches it, which presigned URLs are signed for.
    # Inside Docker the server reaches the bucket at a name no client can resolve
    # (http://s3:9090); locally this is http://localhost:9090, deployed the bucket's real
    # address. Unset, URLs are signed for BUCKET_ENDPOINT -- right for real S3.
    BUCKET_PUBLIC_ENDPOINT: str | None = None
    BUCKET_REGION: str | None = None
    BUCKET_ACCESS_KEY_ID: str | None = None
    BUCKET_SECRET_ACCESS_KEY: str | None = None

    CORS_ALLOWED_ORIGINS: list[str] = []

    # The API's address as clients reach it (http://localhost:8000 locally). An image an
    # HTML page uses is linked through it, so the page shows it wherever it is opened.
    # Unset, pages keep their relative image paths: they still export with their images,
    # but show none when opened.
    PUBLIC_API_URL: str | None = None
    # Signs those image links. They never expire -- the page that holds one must keep
    # working -- so changing this breaks every link already written. Unset, the request
    # signing secret is used.
    FILE_LINK_SECRET: str | None = None

    INVITATION_ACCEPT_URL: str | None = None
    BUCKET_PUBLIC_ENDPOINT: str
    PUBLIC_API_URL: str

    def require_invitation_accept_url(self) -> str:
        if not self.INVITATION_ACCEPT_URL:
            raise InternalServerError(
                message="Unable to process request at this time",
                code="invitation_accept_url_not_configured",
            )
        return self.INVITATION_ACCEPT_URL

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
