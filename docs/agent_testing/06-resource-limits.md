# 06 — Resource Limits Tests

Tests for timeout enforcement, memory limits, and process count limits.

**Setup:** Create a sandbox.

```bash
SID=$(curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
```

---

## RL-01: Default timeout kills long-running command

The default `time_limit` is 30 seconds. A command exceeding it should be killed.

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "sleep 120", "timeout": 3}'
```

**Expected:**
- HTTP 200
- `timed_out` == true
- Response returns within ~4-5 seconds
- `exit_code` != 0

---

## RL-02: Command completes within timeout

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "sleep 1 && echo done", "timeout": 10}'
```

**Expected:**
- `timed_out` == false
- `exit_code` == 0
- `stdout` == `"done\n"`

---

## RL-03: Memory limit kills greedy process

Create a sandbox with a low memory limit:

```bash
SID_MEM=$(curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{"memory_limit": 32}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
```

Try to allocate more memory than allowed:

```bash
curl -s -X POST $BASE/sandbox/$SID_MEM/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "dd if=/dev/zero bs=1M count=100 of=/dev/null 2>&1; echo exit=$?"}'
```

**Expected:**
- The command should either fail or be killed
- `exit_code` != 0 OR the process is terminated

**Alternative memory test (if dd succeeds because it streams):**

```bash
curl -s -X POST $BASE/sandbox/$SID_MEM/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "head -c 50000000 /dev/zero | cat > /dev/null 2>&1; echo exit=$?"}'
```

**Cleanup:**
```bash
curl -s -X DELETE "$BASE/sandbox/$SID_MEM?force=true" > /dev/null
```

---

## RL-04: Process limit prevents fork bomb

Create a sandbox with a very low pids limit:

```bash
SID_PID=$(curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{"pids_limit": 8}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
```

Try to create many processes:

```bash
curl -s -X POST $BASE/sandbox/$SID_PID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "for i in $(seq 1 50); do sleep 10 & done; wait 2>&1; echo exit=$?", "timeout": 5}'
```

**Expected:**
- Most background processes should fail to fork (resource limit)
- `exit_code` != 0 OR `stderr` contains fork/resource errors
- The sandbox runner process must not crash

**Cleanup:**
```bash
curl -s -X DELETE "$BASE/sandbox/$SID_PID?force=true" > /dev/null
```

---

## RL-05: File size limit prevents filling disk

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "dd if=/dev/zero of=/home/bigfile bs=1M count=200 2>&1; echo exit=$?"}'
```

**Expected:**
- The write should fail at some point (RLIMIT_FSIZE or disk quota)
- `exit_code` != 0 OR `stderr` contains "File size limit exceeded" or similar
- `/home/bigfile` should be smaller than 200MB

---

## RL-06: Ephemeral run respects custom time limit

```bash
curl -s -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"command": "sleep 60", "time_limit": 2}'
```

**Expected:**
- `result.timed_out` == true
- Response arrives within ~3 seconds

---

## RL-07: Service remains healthy after resource-intensive tests

After all the above tests, verify the service is responsive:

```bash
curl -s -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo still-alive"}'
```

**Expected:**
- `result.exit_code` == 0
- `result.stdout` == `"still-alive\n"`

---

**Cleanup:**

```bash
curl -s -X DELETE "$BASE/sandbox/$SID?force=true" > /dev/null
```
