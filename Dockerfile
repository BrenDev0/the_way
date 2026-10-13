FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# WeasyPrint lays out text with Pango (HTML to PDF and PNG). The fonts are fallbacks for a
# page whose web fonts cannot be fetched, so it still renders legibly.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fontconfig \
        fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

RUN useradd --create-home --uid 1000 app && chown -R app:app /app /opt/venv
USER app


# The render service (src/render): the same code plus Playwright (137 MB, with its own
# Node driver) and headless Chromium (266 MB) and its system libraries. Only the `render` compose service uses this stage; api, worker and migrate
# never carry a browser. Build it with `--target render`.
FROM base AS render

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# As the app user, so the venv keeps its owner without copying it again; and without
# recompiling bytecode, which rewrites every .pyc in the venv into a second large layer.
RUN UV_COMPILE_BYTECODE=0 uv sync --frozen --group render

# Only the headless shell: the full Chromium beside it is a second browser never launched.
USER root
RUN playwright install --with-deps --only-shell chromium \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/*
USER app

EXPOSE 8100

CMD ["uvicorn", "src.render.app:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]


# The API image, and what `docker build .` gives: last, so it stays the default target.
FROM base AS app

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
