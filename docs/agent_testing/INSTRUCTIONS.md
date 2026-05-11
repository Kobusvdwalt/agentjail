# Agent Testing Instructions — agentjail

## Purpose

This directory contains a suite of test specifications designed to be executed by an AI agent against a running `agentjail` service. Each markdown file describes a set of tests with expected outcomes. Run the full suite after any significant change to the codebase to catch regressions, security holes, and behavioral drift.

## Prerequisites

The service must be running and accessible before executing any tests.

### Start the service

```bash
cd /path/to/get-agentjail
docker compose up --build -d
```

Wait for the health endpoint or a successful response:

```bash
# Poll until the server is ready (up to 15 seconds)
for i in $(seq 1 15); do
  curl -sf http://localhost:8000/api/v1/state > /dev/null 2>&1 && echo "Ready" && break
  sleep 1
done
```

### Base URL

All tests use the REST API at:

```
BASE_URL=http://localhost:8000/api/v1
```

### Runner configuration

The service supports two sandbox runners controlled by `AGENTJAIL_RUNNER`:

| Runner   | Value    | Requires                          | Default in Docker |
|----------|----------|-----------------------------------|-------------------|
| nsjail   | `nsjail` | `CAP_SYS_ADMIN`, seccomp/apparmor off | Yes             |
| chroot   | `chroot` | User namespace support only       | No (for K8s)      |

When testing the chroot runner, set `AGENTJAIL_RUNNER=chroot` in `service-agentjail/default.env` and rebuild.

**Run the full suite once for each runner** if you are testing both.

## How to execute tests

### For an AI agent

1. Read this file first to understand conventions.
2. Open each test file in order (or as directed by priority).
3. For each test case:
   - Execute the curl command(s) listed.
   - Compare the actual response against the **Expected** section.
   - A test **passes** if the assertions in the Expected section hold.
   - A test **fails** if any assertion is violated.
4. Record results as PASS / FAIL with a brief note if failed.
5. **Always clean up**: delete any sandboxes you created during testing.

### Conventions used in test files

- `$BASE` is shorthand for `http://localhost:8000/api/v1`.
- `$SID` is a sandbox ID obtained from a previous create step.
- `jq` expressions show which fields to check and what values to expect.
- When a test says "assert `exit_code == 0`", extract that field from the JSON response.
- HTTP status codes are checked with `curl -o /dev/null -w '%{http_code}'`.

### Cleanup

After the full suite completes:

```bash
# Force-remove all sandboxes
for sid in $(curl -s $BASE/sandbox | python3 -c "import sys,json; [print(s['id']) for s in json.load(sys.stdin)]"); do
  curl -s -X DELETE "$BASE/sandbox/$sid?force=true" > /dev/null
done
```

## Test files

Execute in this order:

| #  | File                              | Focus                                    | Priority |
|----|-----------------------------------|------------------------------------------|----------|
| 01 | `01-sandbox-lifecycle.md`         | Create, inspect, list, stop, remove      | P0       |
| 02 | `02-ephemeral-run.md`             | One-shot sandbox/run endpoint            | P0       |
| 03 | `03-exec-and-shell.md`            | Exec, shell commands in persistent boxes | P0       |
| 04 | `04-filesystem-api.md`            | Read, write, list, mkdir, remove, stat   | P0       |
| 05 | `05-security-isolation.md`        | Filesystem, network, PID, user isolation | P0       |
| 06 | `06-resource-limits.md`           | Timeouts, memory, process limits         | P1       |
| 07 | `07-path-traversal.md`            | Directory escape and path injection      | P0       |
| 08 | `08-error-handling.md`            | 404s, 409s, bad input, edge cases        | P1       |

## Reporting format

After running all tests, produce a summary table:

```
| File                     | Total | Pass | Fail | Notes          |
|--------------------------|-------|------|------|----------------|
| 01-sandbox-lifecycle.md  |     6 |    6 |    0 |                |
| 02-ephemeral-run.md      |     5 |    5 |    0 |                |
| ...                      |       |      |      |                |
| **Total**                |   N   |   N  |   0  |                |
```

If any test fails, include the test ID (e.g. `SEC-03`), the actual response, and a brief diagnosis.
