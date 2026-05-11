FROM ubuntu:24.04 AS nsjail-builder

RUN apt-get update && apt-get install -y \
    autoconf bison flex gcc g++ git \
    libprotobuf-dev libnl-route-3-dev \
    libtool make pkg-config protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/google/nsjail.git /nsjail \
    && cd /nsjail && make -j$(nproc)

FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    libc6 libstdc++6 libprotobuf32t64 libnl-route-3-200 \
    python3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=nsjail-builder /nsjail/nsjail /usr/local/bin/nsjail

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN uv sync --no-dev

RUN mkdir -p /var/lib/agentjail/sandboxes

COPY config/ /etc/agentjail/

EXPOSE 8000

ENTRYPOINT ["uv", "run", "agentjail"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
