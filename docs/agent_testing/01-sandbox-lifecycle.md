# 01 — Sandbox Lifecycle Tests

Tests for creating, inspecting, listing, stopping, and removing persistent sandboxes.

---

## LC-01: Create a sandbox with defaults

```bash
curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{}'
```

**Expected:**
- HTTP 200
- Response contains `id` (non-empty string)
- `status` == `"running"`
- `config.time_limit` == 30
- `config.memory_limit` == 256
- `config.pids_limit` == 64
- `config.cwd` == `"/home"`
- `config.network` == `false`
- `root_dir` starts with `"/var/lib/agentjail/sandboxes/"`
- `created_at` and `updated_at` are valid ISO timestamps

**Cleanup:** Save the returned `id` as `$SID` for subsequent tests.

---

## LC-02: Create a named sandbox with custom config

```bash
curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "test-custom",
    "time_limit": 60,
    "memory_limit": 512,
    "pids_limit": 128,
    "cwd": "/tmp",
    "network": true,
    "env": {"MY_VAR": "hello"}
  }'
```

**Expected:**
- HTTP 200
- `name` == `"test-custom"`
- `config.time_limit` == 60
- `config.memory_limit` == 512
- `config.pids_limit` == 128
- `config.cwd` == `"/tmp"`
- `config.network` == `true`
- `config.env.MY_VAR` == `"hello"`

**Cleanup:** Save `id` as `$SID2`.

---

## LC-03: Inspect a sandbox

```bash
curl -s $BASE/sandbox/$SID
```

**Expected:**
- HTTP 200
- `id` == `$SID`
- `status` == `"running"`
- All config fields match what was returned at creation

---

## LC-04: List sandboxes

```bash
curl -s $BASE/sandbox
```

**Expected:**
- HTTP 200
- Response is a JSON array
- Array contains entries with `id` == `$SID` and `id` == `$SID2`
- Each entry has `id`, `status`, `config`, `root_dir`, `created_at`, `updated_at`

---

## LC-05: Stop a sandbox

```bash
curl -s -X POST $BASE/sandbox/$SID/stop
```

**Expected:**
- HTTP 200
- `id` == `$SID`
- `status` == `"stopped"`
- `updated_at` is later than or equal to `created_at`

---

## LC-06: Remove a stopped sandbox

```bash
curl -s -X DELETE "$BASE/sandbox/$SID"
```

**Expected:**
- HTTP 200
- Response: `{"status": "removed", "sandbox_id": "$SID"}`

**Verify:** Inspecting the same sandbox should now return 404:

```bash
curl -s -o /dev/null -w '%{http_code}' $BASE/sandbox/$SID
```

Expected: `404`

---

## LC-07: Remove a running sandbox without force (should fail)

```bash
curl -s -o /dev/null -w '%{http_code}' -X DELETE "$BASE/sandbox/$SID2"
```

**Expected:**
- HTTP 409
- Body contains `"still running"`

---

## LC-08: Force-remove a running sandbox

```bash
curl -s -X DELETE "$BASE/sandbox/$SID2?force=true"
```

**Expected:**
- HTTP 200
- Response: `{"status": "removed", "sandbox_id": "$SID2"}`

**Verify:** Listing sandboxes should no longer include `$SID2`.
