# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null

RUN apt-get update \
    && apt-get install --no-install-recommends -y git libstdc++6 libatomic1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
WORKDIR /opt/wrapper
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip check \
    && node --version

COPY .gitignore .gitattributes .editorconfig .dockerignore README.md VERSION ./
COPY src/ ./src/
COPY web/ ./web/
COPY scripts/ ./scripts/
COPY tools/ ./tools/
COPY tests/ ./tests/
COPY docs/ ./docs/
COPY deploy/ ./deploy/
COPY workflows/anima_template.json ./workflows/anima_template.json
COPY config/config.example.json ./config/config.example.json
COPY docker/tests/ ./docker/tests/

RUN groupadd --gid 10001 tester \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp tester
USER 10001:10001
ENTRYPOINT ["python", "/opt/wrapper/docker/tests/run.py"]