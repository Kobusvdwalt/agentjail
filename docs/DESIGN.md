# agentjail — Design Document

Sandboxed command execution service for AI agents. Provides isolated environments via MCP and REST API with pluggable sandbox runners.

## Documentation

| Document | Contents |
|---|---|
| [Architecture](architecture.md) | Overview, sandbox modes, runner architecture, filesystem layout, state management |
| [Runners](runners.md) | nsjail runner, chroot runner, isolation guarantees, how to add a new runner |
| [API Reference](api.md) | REST API endpoints, MCP tools, sandbox options |
| [Security](security.md) | Security audit findings, known vulnerabilities, runner-specific notes |
| [Source File Map](source-map.md) | File-by-file reference for agents modifying the codebase |
| [Operations](ops.md) | Tech stack, configuration, Docker setup, development workflow, tested features |
