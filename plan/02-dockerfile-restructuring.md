# Plan 02: Dockerfile Restructuring — Base Image Pattern

## Goal

Restructure agentjail so it ships as a **base Docker image** that users extend with their own Dockerfile. The agentjail layer provides nsjail + the MCP/API server. The user layer adds their language runtime, tools, and any extra bind-mount paths they want exposed inside sandboxes.

## Why

Currently the Dockerfile bundles Python 3.14 as both the server runtime AND the sandbox runtime. Users who want Go, Bun, Rust, or a different Python inside sandboxes must rebuild the entire image. A layered approach lets them just write `FROM agentjail:latest` and add their own tools.

## Architecture

```
┌─────────────────────────────────┐
│  User Dockerfile                │  ← adds language runtimes, tools
│  FROM agentjail:latest          │
│  RUN apt-get install nodejs     │
│  COPY agentjail.yaml /etc/...  │  ← optional config overrides
├─────────────────────────────────┤
│  agentjail base image           │  ← nsjail + agentjail server
│  Ubuntu 24.04                   │
│  Python 3.14 + uv (server only)│
│  nsjail binary                  │
│  agentjail package              │
└─────────────────────────────────┘
```

## Files to Change / Create

### 1. Restructure `service-agentjail/Dockerfile` (the production image)

This becomes the **base image**. Changes:

```dockerfile
FROM ubuntu:24.04 AS nsjail-builder
# ... (existing nsjail build stage — keep as-is)

FROM ubuntu:24.04

# Install minimal runtime deps + Python for the agentjail server
RUN apt-get update && apt-get install -y --no-install-recommends \
    libc6 libstdc++6 libprotobuf32t64 libnl-route-3-200 \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=nsjail-builder /nsjail/nsjail /usr/local/bin/nsjail
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create non-root service user (P0 security fix)
RUN groupadd --system service-group \
    && useradd --system --gid service-group --create-home --shell /bin/bash service

# Install agentjail
WORKDIR /opt/agentjail
COPY pyproject.toml .
COPY src/ src/
RUN uv sync --no-dev

# Prepare state directory
RUN mkdir -p /var/lib/agentjail/sandboxes \
    && chown -R service:service-group /var/lib/agentjail

# Copy default config
COPY config/ /etc/agentjail/

USER service

EXPOSE 8000

ENTRYPOINT ["uv", "run", "agentjail"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
```

Key changes vs current:
- **Adds non-root `USER service`** (P0 security fix from audit)
- **Installs to `/opt/agentjail`** instead of `/app` — leaves `/app` free for user code
- **No language runtimes for sandboxes** — users add their own

### 2. Create `service-agentjail/dev.dockerfile` (keep mostly as-is)

Keep the dev dockerfile largely unchanged but align the user/paths pattern.

### 3. Create example Dockerfiles in `docs/examples/`

#### `docs/examples/Dockerfile.python`
```dockerfile
FROM agentjail:latest

USER root

# Add Python 3.12 for sandbox use (agentjail server uses its own Python)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Optional: pre-install packages available inside sandboxes
RUN pip3 install numpy pandas

# Optional: custom agentjail config
COPY agentjail.yaml /etc/agentjail/agentjail.yaml

USER service
```

#### `docs/examples/Dockerfile.go`
```dockerfile
FROM agentjail:latest

USER root

# Add Go for sandbox use
RUN apt-get update && apt-get install -y --no-install-recommends wget \
    && wget -q https://go.dev/dl/go1.23.0.linux-amd64.tar.gz \
    && tar -C /usr/local -xzf go1.23.0.linux-amd64.tar.gz \
    && rm go1.23.0.linux-amd64.tar.gz \
    && apt-get purge -y wget && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Optional: custom agentjail config
COPY agentjail.yaml /etc/agentjail/agentjail.yaml

USER service
```

#### `docs/examples/Dockerfile.bun`
```dockerfile
FROM agentjail:latest

USER root

# Add Bun for sandbox use
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip \
    && curl -fsSL https://bun.sh/install | bash \
    && mv /root/.bun/bin/bun /usr/local/bin/bun \
    && rm -rf /root/.bun \
    && apt-get purge -y curl unzip && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Optional: custom agentjail config
COPY agentjail.yaml /etc/agentjail/agentjail.yaml

USER service
```

### 4. Update config to support user-customizable bind mounts

The `agentjail.yaml` config (see Plan 05) should allow users to specify additional read-only bind mounts that get exposed inside sandboxes. The current `bind_mount_ro` list in `config.py` is the right mechanism — it just needs to be configurable via the YAML config file.

Example user config addition:
```yaml
sandbox:
  bind_mount_ro:
    - /usr
    - /lib
    - /lib64
    - /bin
    - /sbin
    - /etc
    # User-added:
    - /usr/local/go    # expose Go toolchain to sandboxes
```

### 5. Update `docker-compose.yml` to reference the base image

```yaml
services:
  agentjail:
    build:
      context: ./service-agentjail
      dockerfile: Dockerfile
    # ... rest stays the same
```

## How It Works End-to-End

1. We publish `agentjail:latest` as a Docker image (or users build it locally)
2. User creates their own `Dockerfile` starting with `FROM agentjail:latest`
3. User installs whatever runtimes/tools they want — these go into `/usr`, `/usr/local`, etc.
4. Since those paths are bind-mounted read-only into sandboxes by default, the tools are automatically available inside sandboxes
5. User optionally provides `agentjail.yaml` to customize limits, add extra bind mounts, etc.
6. User builds and runs their image — agentjail starts automatically via the base image's ENTRYPOINT

## Reference

- See `docs/DESIGN.md` section "Bind-mount isolation" for how mounts work
- See `service-agentjail/src/agentjail/config.py` for the `bind_mount_ro` list
- See `service-agentjail/src/agentjail/sandbox/nsjail.py` `_build_args()` for how bind mounts become nsjail flags
- The `nsjail_default.cfg` in `config/` is not currently used at runtime (args are built in Python) — it's documentation only
