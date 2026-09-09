FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.10.7 /uv /uvx /usr/local/bin/

WORKDIR /app

ARG EXTRAS=all
ARG SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${SETUPTOOLS_SCM_PRETEND_VERSION}

COPY app/pyproject.toml app/uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project --extra ${EXTRAS}

COPY app/ ./
RUN uv sync --no-dev --frozen --no-editable --extra ${EXTRAS}

ENV PATH="/app/.venv/bin:${PATH}"

COPY ci/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN groupadd --gid 1000 review_sentinel && \
    useradd --uid 1000 --gid review_sentinel --create-home review_sentinel && \
    mkdir -p /workspace /tmp/review_sentinel && \
    chown -R review_sentinel:review_sentinel /app /workspace /tmp/review_sentinel

ENTRYPOINT ["/entrypoint.sh"]
