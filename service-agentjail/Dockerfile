# ── Stage 1: Build nsjail ────────────────────────────────────────────────────
FROM ubuntu:24.04 AS nsjail-builder

RUN apt-get update && apt-get install -y \
    autoconf bison flex gcc g++ git \
    libprotobuf-dev libnl-route-3-dev \
    libtool make pkg-config protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/google/nsjail.git /nsjail \
    && cd /nsjail && make -j$(nproc)

# Collect nsjail's non-standard runtime libs so they can be bundled
RUN apt-get update && apt-get install -y --no-install-recommends patchelf \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /nsjail-libs \
    && for lib in libprotobuf libnl-route-3 libnl-3; do \
        ldd /nsjail/nsjail | grep "$lib" | awk '{print $3}' | xargs -I{} cp -L {} /nsjail-libs/; \
    done \
    && patchelf --set-rpath /opt/agentjail/lib /nsjail/nsjail

# ── Stage 2: Build agentjail Python package ─────────────────────────────────
FROM ubuntu:24.04 AS agentjail-builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Keep uv-managed Python inside /opt/agentjail so it's all one tree
ENV UV_PYTHON_INSTALL_DIR=/opt/agentjail/python

WORKDIR /opt/agentjail
COPY pyproject.toml .
COPY src/ src/
COPY config/ config/

RUN uv sync --no-dev --no-editable --python 3.14

# Copy nsjail binary + its runtime libs into the tree
COPY --from=nsjail-builder /nsjail/nsjail /opt/agentjail/bin/nsjail
COPY --from=nsjail-builder /nsjail-libs/ /opt/agentjail/lib/

# ── Stage 3: Runtime ────────────────────────────────────────────────────────
# Users can ALSO just: COPY --from=agentjail:latest /opt/agentjail /opt/agentjail
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Self-contained agentjail tree: Python + venv + nsjail + libs + config
COPY --from=agentjail-builder /opt/agentjail /opt/agentjail

# Create non-root service user
RUN groupadd --system service-group \
    && useradd --system --gid service-group --create-home --shell /bin/bash service

# Prepare state directory
RUN mkdir -p /var/lib/agentjail/sandboxes \
    && chown -R service:service-group /var/lib/agentjail

USER service

EXPOSE 8000

ENTRYPOINT ["/opt/agentjail/.venv/bin/agentjail"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
