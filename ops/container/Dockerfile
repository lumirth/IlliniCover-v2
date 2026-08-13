FROM ghcr.io/astral-sh/uv:0.9.3@sha256:ecfea7316b266ba82a5e9efb052339ca410dd774dc01e134a30890e6b85c7cd1 AS uv
FROM python:3.14.7-slim-bookworm@sha256:23c59390fc717bf09f9336908199a0ae75d9c4264bf296123f94ad772fea3b52

ARG CODE_REVISION
LABEL org.opencontainers.image.title="IlliniCover backend" \
      org.opencontainers.image.revision="${CODE_REVISION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY server ./server
COPY api ./api
COPY data ./data
COPY docs/privacy-policy.md ./docs/privacy-policy.md
COPY docs/model/cover-historical-v1-evaluation.json \
    ./data/cover/recovered-cover-v1/model-selection-receipt.json

RUN test -n "${CODE_REVISION}"
RUN DJANGO_SETTINGS_MODULE=config.settings.development \
    uv run python server/manage.py collectstatic --noinput
RUN uv sync --frozen --no-dev

RUN addgroup --system illinicover \
    && adduser --system --ingroup illinicover --home /app illinicover \
    && chown -R illinicover:illinicover /app
USER illinicover

EXPOSE 8080
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --chdir server --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 25 --error-logfile -"]
