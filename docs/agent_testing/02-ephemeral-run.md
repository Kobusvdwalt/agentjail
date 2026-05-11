# 02 — Ephemeral Run Tests

Tests for the `POST /sandbox/run` endpoint which creates a temporary sandbox, runs a single command, and destroys it.

---

## ER-01: Simple echo command

```bash
curl -s -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo hello world"}'
```

**Expected:**
- HTTP 200
- `result.exit_code` == 0
- `result.stdout` == `"hello world\n"`
- `result.stderr` is empty or contains only runner log lines (nsjail `[I]` lines are acceptable)
- `result.timed_out` == false
- `sandbox_id` is a non-empty string

---

## ER-02: Command that fails

```bash
curl -s -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"command": "exit 42"}'
```

**Expected:**
- HTTP 200
- `result.exit_code` == 42
- `result.timed_out` == false

---

## ER-03: Command with stderr output

```bash
curl -s -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo out && echo err >&2"}'
```

**Expected:**
- HTTP 200
- `result.exit_code` == 0
- `result.stdout` contains `"out\n"`
- `result.stderr` contains `"err\n"` (may also contain runner log lines)

---

## ER-04: Ephemeral sandbox is destroyed after run

```bash
# Capture the sandbox_id
SID=$(curl -s -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo disposable"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['sandbox_id'])")

# Try to inspect it — should not exist
curl -s -o /dev/null -w '%{http_code}' $BASE/sandbox/$SID
```

**Expected:**
- The `sandbox/run` returns exit_code 0 and stdout `"disposable\n"`
- The inspect returns HTTP `404` — the ephemeral sandbox was cleaned up

---

## ER-05: Custom environment variables

```bash
curl -s -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo $GREETING $TARGET", "env": {"GREETING": "hello", "TARGET": "world"}}'
```

**Expected:**
- HTTP 200
- `result.exit_code` == 0
- `result.stdout` == `"hello world\n"`

---

## ER-06: Custom time limit (short timeout)

```bash
curl -s -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"command": "sleep 30", "time_limit": 2}'
```

**Expected:**
- HTTP 200
- `result.timed_out` == true
- `result.exit_code` != 0 (typically -1)
- Response returns within ~3 seconds, not 30

---

## ER-07: Multi-line shell script

```bash
curl -s -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"command": "for i in 1 2 3; do echo $i; done"}'
```

**Expected:**
- HTTP 200
- `result.exit_code` == 0
- `result.stdout` == `"1\n2\n3\n"`
