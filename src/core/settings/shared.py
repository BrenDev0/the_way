from src.core.exceptions import InternalServerError

from .base import AppSettings


class SharedSettings(AppSettings):
    """What the api and the worker both need. In docker-compose.yml this is the environment
    both services get (`x-shared-environment`). The worker runs the api's app (taskiq_fastapi
    starts it), so whatever the app's start-up builds is needed by both."""

    # --- database --------------------------------------------------------------------
    DATABASE_URL: str
    # Connections per process. A conversation turn holds its session for the whole turn,
    # so the worker needs about one per task it runs at once (TASKIQ_MAX_ASYNC_TASKS);
    # SQLAlchemy's default of 5 + 10 timed turns out at 15. Every process's pool together
    # must stay under Postgres's max_connections (100 by default). The worker is given its
    # own values for these two (compose: WORKER_DATABASE_POOL_SIZE / _MAX_OVERFLOW).
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    # Each process brings the database to the code's schema as it starts (one at a time,
    # under a lock). Off where the schema is built some other way -- the test suites.
    DATABASE_MIGRATE_ON_STARTUP: bool = True

    # --- redis and the task queue (the producer side; the worker's own knobs are worker.py)
    REDIS_URL: str
    TASKIQ_BROKER_URL: str
    TASKIQ_RESULT_BACKEND_URL: str | None = None
    TASKIQ_RESULT_TTL_SECONDS: int = 60 * 60
    TASKIQ_STREAM_NAME: str = "taskiq:stream"
    TASKIQ_CONSUMER_GROUP: str = "taskiq:workers"

    def taskiq_result_backend_url(self) -> str:
        return self.TASKIQ_RESULT_BACKEND_URL or self.TASKIQ_BROKER_URL

    # --- secrets ---------------------------------------------------------------------
    CRYPTOGRAPHY_FERNET_KEY: str
    # Signs every request the front end makes (fastapi/signing.py); it is also what image
    # links fall back to when they have no secret of their own (FILE_LINK_SECRET).
    REQUEST_SIGNING_SECRET: str

    # --- mail ------------------------------------------------------------------------
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None

    # --- the file store --------------------------------------------------------------
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

    # --- links the pages the app writes carry ------------------------------------------
    # The API's address as clients reach it (http://localhost:8000 locally). An image an
    # HTML page uses is linked through it, so the page shows it wherever it is opened.
    # Unset, pages keep their relative image paths: they still export with their images,
    # but show none when opened.
    PUBLIC_API_URL: str | None = None
    # Signs those image links. They never expire -- the page that holds one must keep
    # working -- so changing this breaks every link already written. Unset, the request
    # signing secret is used.
    FILE_LINK_SECRET: str | None = None

    # --- the render service, as its callers reach it ----------------------------------------
    # A real Chromium for screenshots, page checks and single-page PDFs (src/render). Unset,
    # those fall back to WeasyPrint or are reported unavailable. The service has its own
    # settings (render.py); RENDER_SHARED_SECRET must be the same value on both sides.
    RENDER_URL: str | None = None
    RENDER_SHARED_SECRET: str | None = None

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


settings = SharedSettings()
