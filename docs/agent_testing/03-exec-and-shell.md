# 03 — Shell Tests

Tests for running commands inside persistent sandboxes via the `shell` endpoint.

**Setup:** Create a sandbox before running these tests.

```bash
SID=$(curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
```

---

## EX-01: Shell — simple command

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo hello"}'
```

**Expected:**
- HTTP 200
- `exit_code` == 0
- `stdout` == `"hello\n"`
- `timed_out` == false

---

## EX-02: Shell — pipes and redirects

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo abc def ghi | tr \" \" \"\\n\" | sort | head -2"}'
```

**Expected:**
- HTTP 200
- `exit_code` == 0
- `stdout` == `"abc\ndef\n"`

---

## EX-03: Shell — working directory is /home by default

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "pwd"}'
```

**Expected:**
- `exit_code` == 0
- `stdout` == `"/home\n"`

---

## EX-04: Shell — per-command timeout

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "sleep 60", "timeout": 2}'
```

**Expected:**
- HTTP 200
- `timed_out` == true
- Response returns within ~3 seconds

---

## EX-08: State persists between shell commands

```bash
# Write a file
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo persistent > /home/state_test.txt"}'

# Read it back in a separate command
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "cat /home/state_test.txt"}'
```

**Expected:**
- First call: `exit_code` == 0
- Second call: `exit_code` == 0, `stdout` == `"persistent\n"`

---

## EX-09: User identity inside sandbox

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "id -u && id -g"}'
```

**Expected:**
- `exit_code` == 0
- `stdout` contains `"1000\n1000\n"` — sandbox user is uid/gid 1000

---

**Cleanup:**

```bash
curl -s -X DELETE "$BASE/sandbox/$SID?force=true" > /dev/null
```
