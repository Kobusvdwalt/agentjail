# Security boundaries

## Control plane

Every HTTP REST/MCP request requires the service bearer credential, except the
fixed `/health` response. HTTP startup fails without `AGENTJAIL_API_TOKEN` of at
least 32 characters. The middleware also covers state, docs and file downloads.
Use a randomly generated credential and TLS; possession of the credential grants
administrative control over every workspace. Never expose it to models, commands,
workspace files, public artifact links or untrusted API callers.

This is service authentication, not user/organization authorization. The caller
must authorize the current organization membership and resolve the correct
workspace before invoking Agentjail. Resource globs and opaque sandbox IDs do not
replace those checks. Direct administrative MCP access is unsuitable for Vigil
models, regardless of a tool allowlist.

## Execution authority

Persistent shell execution requires a workspace-scoped lease with a server-side
monotonic deadline. Lease tokens are random, never persisted, and absent from
inspection/state responses. An active lease cannot be overwritten by acquire.
Stop/expiry revokes authority before terminating commands; new acquisition waits
for that cleanup. Old tokens cannot execute or renew after replacement. All
leases become invalid on service restart while persistent files remain.

Token-checked REST release validates ownership under the same workspace lock as
acquire/renew. Delayed cleanup cannot revoke a replacement lease. Caller-supplied
`not_after` timestamps cap acquire/renew to upstream authorization expiry; omitting
a renewal bound preserves its cap. Only trusted supervisors may refresh that
bound after checking current authority. Absolute bounds require synchronized
supervisor/service clocks. Stable UUID creation rejects configuration changes;
UUID secrecy is not authorization.

Timeouts, HTTP disconnect, stop, force removal and manager shutdown cancel the
registered runner task. Shared process supervision kills its POSIX process group
and awaits completion while draining bounded stdout/stderr buffers. In nsjail,
the command also runs in a PID namespace; terminating its init removes namespace
descendants. Bare mode has no such boundary: deliberately detached processes can
escape the process group. Never use bare mode for untrusted workloads.

Only one service process may own a state/storage root. The JSON file lock
protects file updates; it does not coordinate live leases or process registries
between service processes. Command admission is bounded by
`AGENTJAIL_MAX_ACTIVE_COMMANDS`. Captured output retains at most
`AGENTJAIL_MAX_OUTPUT_BYTES` raw bytes per stream while excess output is drained.

The local regression proof checks real nsjail delayed writes after HTTP abort,
stop and lease expiry, persistent file recovery, REST/MCP authentication and
Mastra tool dispatch. It does not establish a production AKS isolation profile.

## Filesystem and network

The nsjail runner mounts selected resources read-only, and an unselected resource
is absent from its mount namespace. `resources` still defaults to all resources;
supervisors should explicitly request `[]` or an approved selection. The runner
does not mount `/proc`, and supplies an explicit environment rather than copying
the supervisor's environment. Read-only `/etc` and `/sys/fs/cgroup` mounts remain;
do not store credentials in reachable paths.

Network is isolated by default. Opting into `network: true` gives commands the
service container's network access, without a destination allowlist. Bearer
authentication prevents unauthenticated control-plane calls but does not block
access to metadata endpoints or other private services. Do not use
`network: true` for untrusted code; use the egress allowlist instead.

## Network egress

`AGENTJAIL_NETWORK_ALLOW` gives sandboxes without `network: true` a filtered way
out (nsjail runner only). What it guarantees:

- The jail's network namespace still has only loopback. The only path out is the
  per-command Unix socket to `EgressProxy`, so ignoring `HTTP_PROXY` or opening
  raw sockets reaches nothing. There is no DNS inside the jail; the proxy
  resolves names.
- Only `host:port` pairs matching the allowlist are connected. Matching is on the
  name the client asked for, lowercased, without a trailing dot.
- The proxy connects to the address it resolved, after checking every resolved
  address. Link-local (including `169.254.169.254` metadata), multicast,
  unspecified and Azure's platform address `168.63.129.16` are always refused;
  private, loopback, CGNAT and other non-public addresses are refused unless
  `AGENTJAIL_NETWORK_ALLOW_PRIVATE=true`. Names resolving to a mix are refused.
- HTTPS is tunnelled with CONNECT and not decrypted, so the proxy sees the host
  and port but not paths or headers. It strips `Proxy-*` headers from plain HTTP.
- The socket exists only while its command runs; open tunnels are closed when
  the command ends.

What it does not do:

- It does not limit what an allowed host is used for. Allowlisting a host that
  accepts uploads (for example `*.googleapis.com`, which includes Cloud Storage)
  lets sandboxed code send workspace data there. Keep wildcards as narrow as the
  use allows.
- It filters TCP through HTTP proxies only. Tools that ignore proxy variables or
  need UDP do not work.
- It does not rate-limit or log request content. Decisions are logged at INFO by
  host and port under `agentjail.sandbox.egress` when logging is configured.
- One client connection talks to one upstream; a plain-HTTP keep-alive request
  for a different host on the same connection still reaches the first host.

## Remaining work before hostile tenant execution

- Verify nested user namespaces, seccomp/AppArmor policy and storage mounts on
  the actual AKS runtime. The reference nsjail config is not loaded by the runner;
  it does not enable a syscall policy. Do not infer required capabilities from
  the broad example Compose profile or treat namespace isolation as a VM boundary.
- Enforce organization/workspace mapping at the trusted Vigil API/worker boundary
  and bind execution leases to its current assignment/run ownership.
- Add aggregate disk/workspace quotas and retention. Per-file rlimits and bounded
  output do not bound total disk usage or prevent CPU/resource contention.
- Resolve filesystem symlink-swap races between path resolution and file use.
  `_resolve_safe()` rejects traversal at resolution time, not later mutation.
- Restrict state access to supervisors; it still exposes internal paths and
  workspace configuration to authenticated administrators.
- Pin production image/build inputs and verify recovery over the actual persistent
  volume after pod replacement. The digest-pinned verification image is a local
  regression fixture, not a production release.

Authentication, execution leases and process cleanup address the demonstrated
control-plane/cancellation gaps. These remaining controls are required before
enabling Vigil agents to execute arbitrary code in production.
