# syntax=docker/dockerfile:1
#
# api + scheduler image (§A2 — one image, two entrypoints).
#
# Built on the target server (§A1), so the base image must publish a linux/arm64
# manifest and every wheel must exist for aarch64. `--only-binary=:all:` turns
# that from a claim into a build-time assertion: if any pinned dependency would
# have to compile from source on the Oracle A1, the build fails here instead of
# timing out or producing a subtly different binary.

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt ./
RUN pip install --only-binary=:all: -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Non-root, no shell, no home clutter. uid is fixed so bind-mounted files (none
# today) keep predictable ownership.
RUN useradd --system --uid 10001 --user-group --no-create-home ct

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=ct:ct alembic.ini pyproject.toml ./
COPY --chown=ct:ct migrations ./migrations
COPY --chown=ct:ct app ./app

USER ct
EXPOSE 8000

# Readiness only — never the whole-system endpoint. /api/health is 503 while the
# scheduler is down, which says nothing about this container's ability to serve.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=4)"]

# The scheduler service overrides this with: python -m app.scheduler
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--timeout-graceful-shutdown", "20"]
