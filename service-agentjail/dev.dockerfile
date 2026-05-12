FROM ubuntu:24.04 AS nsjail-builder

RUN apt-get update && apt-get install -y \
    autoconf bison flex gcc g++ git \
    libprotobuf-dev libnl-route-3-dev \
    libtool make pkg-config protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/google/nsjail.git /nsjail \
    && cd /nsjail && make -j$(nproc)

FROM python:3.14-slim

ENV UV_PYTHON_DOWNLOADS=0 UV_COMPILE_BYTECODE=0

RUN apt-get update && apt-get install -y --no-install-recommends \
    libprotobuf32t64 libnl-route-3-200 libcap2-bin \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=nsjail-builder /nsjail/nsjail /usr/local/bin/nsjail
# Note: Do NOT setcap on the nsjail binary here. The dev docker-compose grants
# CAP_SYS_ADMIN via cap_add, and file capabilities conflict with container
# capabilities on some kernels, causing "Operation not permitted" on exec.
# Production Dockerfile should use setcap if not using cap_add.

RUN pip install uv

RUN groupadd --system service-group && useradd --system --gid service-group --create-home --shell /bin/bash service

RUN mkdir -p /var/lib/agentjail/sandboxes && chown -R service:service-group /var/lib/agentjail

RUN mkdir -p /home/service/app && chown service:service-group /home/service/app

USER service

WORKDIR /home/service/app

COPY --chown=service:service-group ./pyproject.toml ./

RUN uv sync --no-install-project --no-dev

COPY --chown=service:service-group ./src ./src
COPY --chown=service:service-group ./config ./config

EXPOSE 8000

CMD uv run uvicorn agentjail.server:create_app --host 0.0.0.0 --port ${AGENTJAIL_PORT:-8000} --reload
