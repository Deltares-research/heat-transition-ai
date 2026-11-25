# api + webapp in one image, for a single Azure Container App.
# Build context: repository root
#   docker build -f docker/app.Dockerfile -t heat-transition-app .

FROM node:22-alpine AS frontend-build

WORKDIR /app

COPY webapp/package.json webapp/package-lock.json ./
RUN npm ci

COPY webapp/ .
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

# Install dependencies first so this layer is cached independently of source changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

# Add the source and install the project itself.
COPY src ./src
COPY apps ./apps
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

COPY --from=frontend-build /app/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# nginx (public, proxies /ask + /health to the api below) is the only port
# the Container App should expose ingress for. The api on :8000 is loopback-only.
EXPOSE 8080

CMD ["/entrypoint.sh"]
