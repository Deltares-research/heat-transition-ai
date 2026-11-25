# Build context: repository root
#   docker build -f docker/backend.Dockerfile -t heat-transition-backend .
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Install dependencies first so this layer is cached independently of source changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

# Add the source and install the project itself.
COPY src ./src
COPY apps ./apps
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["python", "-m", "apps.api"]
