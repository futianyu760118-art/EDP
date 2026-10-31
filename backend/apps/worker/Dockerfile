# 构建上下文必须为 backend/（uv workspace 根，需要根 pyproject.toml + uv.lock）

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /workspace
COPY . .
RUN uv sync --frozen --no-dev --package edp-worker

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /workspace
COPY --from=builder /workspace /workspace
ENV PYTHONUNBUFFERED=1 \
    PATH="/workspace/.venv/bin:$PATH"
CMD ["python", "-m", "edp_worker.main"]
