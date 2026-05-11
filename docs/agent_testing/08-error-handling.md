# 08 — Error Handling and Edge Cases

Tests for proper error responses, invalid input handling, and boundary conditions.

---

## ERR-01: Inspect non-existent sandbox

```bash
curl -s -o /dev/null -w '%{http_code}' $BASE/sandbox/00000000-0000-0000-0000-000000000000
```

**Expected:** HTTP `404`

---

## ERR-02: Exec on non-existent sandbox

```bash
curl -s -o /dev/null -w '%{http_code}' -X POST \
  $BASE/sandbox/00000000-0000-0000-0000-000000000000/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo test"}'
```

**Expected:** HTTP `404`

---

## ERR-03: Exec on stopped sandbox

```bash
# Create and stop a sandbox
SID=$(curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

curl -s -X POST $BASE/sandbox/$SID/stop > /dev/null

# Try to exec
curl -s -o /dev/null -w '%{http_code}' -X POST \
  $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo test"}'
```

**Expected:** HTTP `409` — sandbox is not running

**Cleanup:**
```bash
curl -s -X DELETE "$BASE/sandbox/$SID" > /dev/null
```

---

## ERR-04: Delete running sandbox without force

```bash
SID=$(curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

curl -s -o /dev/null -w '%{http_code}' -X DELETE "$BASE/sandbox/$SID"
```

**Expected:** HTTP `409`

**Cleanup:**
```bash
curl -s -X DELETE "$BASE/sandbox/$SID?force=true" > /dev/null
```

---

## ERR-05: Delete non-existent sandbox

```bash
curl -s -o /dev/null -w '%{http_code}' \
  -X DELETE "$BASE/sandbox/00000000-0000-0000-0000-000000000000"
```

**Expected:** HTTP `404`

---

## ERR-06: Missing Content-Type header

```bash
curl -s -o /dev/null -w '%{http_code}' -X POST $BASE/sandbox/run \
  -d '{"command": "echo test"}'
```

**Expected:** HTTP `422` — FastAPI requires Content-Type: application/json for JSON body

---

## ERR-07: Malformed JSON body

```bash
curl -s -o /dev/null -w '%{http_code}' -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d 'not valid json{'
```

**Expected:** HTTP `422`

---

## ERR-08: Missing required field

```bash
curl -s -o /dev/null -w '%{http_code}' -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{}'
```

**Expected:** HTTP `422` — `command` field is required

---

## ERR-09: Extra unknown fields are ignored (or rejected)

```bash
curl -s -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo ok", "unknown_field": "should be ignored"}' | python3 -c "
import sys, json
r = json.load(sys.stdin)
print('exit_code:', r['result']['exit_code'])
"
```

**Expected:**
- Either HTTP 200 (extra fields silently ignored) or HTTP 422 (strict validation)
- Must NOT cause a 500 error

---

## ERR-10: Empty command string

```bash
curl -s -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"command": ""}'
```

**Expected:**
- Either HTTP 422 (validation rejects empty) or HTTP 200 with a non-zero exit_code
- Must NOT cause a 500 error

---

## ERR-11: Command with only whitespace

```bash
curl -s -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"command": "   "}'
```

**Expected:**
- HTTP 200 with non-zero exit_code (shell can't find command) or HTTP 422
- Must NOT cause a 500 error

---

## ERR-12: Very long command string

```bash
LONG_CMD=$(python3 -c "print('echo ' + 'A' * 100000)")
curl -s -o /dev/null -w '%{http_code}' -X POST $BASE/sandbox/run \
  -H 'Content-Type: application/json' \
  -d "{\"command\": \"$LONG_CMD\"}"
```

**Expected:**
- Either processes the command (echo with 100k chars) or returns an error
- Must NOT cause a 500 crash

---

## ERR-13: Filesystem operations on non-existent sandbox

```bash
curl -s -o /dev/null -w '%{http_code}' \
  "$BASE/sandbox/00000000-0000-0000-0000-000000000000/fs/list?path=/"
```

**Expected:** HTTP `404`

---

## ERR-14: Stop an already stopped sandbox

```bash
SID=$(curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

curl -s -X POST $BASE/sandbox/$SID/stop > /dev/null

# Stop again
curl -s -o /dev/null -w '%{http_code}' -X POST $BASE/sandbox/$SID/stop
```

**Expected:**
- Either HTTP 200 (idempotent) or HTTP 409
- Must NOT cause a 500 error

**Cleanup:**
```bash
curl -s -X DELETE "$BASE/sandbox/$SID" > /dev/null
```

---

## ERR-15: Concurrent requests to same sandbox

Run two commands simultaneously:

```bash
SID=$(curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Launch two concurrent commands
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo cmd1 && sleep 2"}' &
PID1=$!

curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo cmd2 && sleep 2"}' &
PID2=$!

wait $PID1 $PID2
```

**Expected:**
- Both commands should complete (may run sequentially or in parallel)
- Neither should return a 500 error
- Service remains healthy afterward

**Cleanup:**
```bash
curl -s -X DELETE "$BASE/sandbox/$SID?force=true" > /dev/null
```

---

## ERR-16: Rapid sandbox creation and deletion

```bash
for i in $(seq 1 10); do
  SID=$(curl -s -X POST $BASE/sandbox \
    -H 'Content-Type: application/json' \
    -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
  curl -s -X DELETE "$BASE/sandbox/$SID?force=true" > /dev/null
done

# Verify service health
curl -s -o /dev/null -w '%{http_code}' $BASE/sandbox
```

**Expected:**
- All 10 create/delete cycles complete without error
- Final health check returns HTTP `200`

---

## ERR-17: State endpoint returns valid structure

```bash
curl -s $BASE/state | python3 -c "
import sys, json
state = json.load(sys.stdin)
assert 'version' in state, 'missing version'
assert 'sandboxes' in state, 'missing sandboxes'
assert isinstance(state['sandboxes'], dict), 'sandboxes not a dict'
print('OK')
"
```

**Expected:** Prints `OK` — state has `version` (int) and `sandboxes` (dict)
