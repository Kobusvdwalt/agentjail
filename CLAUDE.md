# agentjail — Agent Guidelines

## Project

Sandboxed command execution service for AI agents. Python 3.14, FastAPI, FastMCP, nsjail/chroot runners.

## Build & Test

```bash
# Local dev (Docker Compose with hot-reload)
docker compose up --build --watch

# Run tests (from service-agentjail/)
uv run pytest

# Run a single test
uv run pytest tests/test_exec.py -k test_shell_echo

# Health check
curl -s http://localhost:8000/api/v1/state | python3 -c "import sys,json; print('OK' if json.load(sys.stdin).get('version') else 'FAIL')"
```

## Code Conventions

- **Runner-agnostic code**: API, MCP, state, and filesystem code must not reference a specific runner. Only `manager.py` selects the runner.
- **Adding a runner**: New module in `src/agentjail/sandbox/`, implement `setup_sandbox()` + `run_command()`, register in `manager.py`, add to `Literal` in `config.py`.
- **Config**: All settings via pydantic-settings with `AGENTJAIL_` env prefix. No hardcoded values.
- **State file**: Always use `StateManager` (filelock + atomic writes). Never write the JSON directly.
- **Path safety**: All filesystem API operations must go through `_resolve_safe()` for path traversal protection.

## Documentation Rules

**Keep docs up to date with every change.** The docs live in `docs/` and are split by concern:

| File | What goes here |
|---|---|
| `docs/architecture.md` | System design, sandbox modes, runner architecture, filesystem layout |
| `docs/runners.md` | Runner-specific details (nsjail flags, chroot flow, isolation guarantees, limitations) |
| `docs/api.md` | REST endpoints, MCP tools, sandbox options |
| `docs/security.md` | Security audit findings, vulnerabilities, runner-specific security notes |
| `docs/source-map.md` | File-by-file reference table — update when adding/removing/renaming source files |
| `docs/ops.md` | Tech stack, env var config table, Docker setup, dev workflow, tested features |
| `README.md` | User-facing overview — update when adding runners, API changes, or config changes |

When making changes:
1. If you add/remove/rename a source file → update `docs/source-map.md`
2. If you change API endpoints or MCP tools → update `docs/api.md` and `README.md`
3. If you change runner behavior or add a runner → update `docs/runners.md`, `docs/architecture.md`, and `README.md`
4. If you change config/env vars → update `docs/ops.md` and `README.md`
5. If you fix or discover a security issue → update `docs/security.md`
6. If you change Docker/K8s setup → update `docs/ops.md` and `README.md`
