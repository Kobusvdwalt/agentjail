# 07 — Path Traversal Tests

**Priority: P0 — these are direct security checks.**

Tests that the filesystem API cannot be used to read, write, or manipulate files outside the sandbox root directory. Every test here must FAIL to access host data.

**Setup:** Create a sandbox.

```bash
SID=$(curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
```

---

## PT-01: Read with .. traversal

```bash
curl -s -o /dev/null -w '%{http_code}' \
  "$BASE/sandbox/$SID/fs/read?path=/../../../etc/passwd"
```

**Expected:** HTTP `400` (path escapes sandbox root)

---

## PT-02: Read with encoded .. traversal

```bash
curl -s -o /dev/null -w '%{http_code}' \
  "$BASE/sandbox/$SID/fs/read?path=%2F..%2F..%2F..%2Fetc%2Fpasswd"
```

**Expected:** HTTP `400` (path escapes sandbox root)

---

## PT-03: Read absolute host path directly

```bash
curl -s -o /dev/null -w '%{http_code}' \
  "$BASE/sandbox/$SID/fs/read?path=/etc/passwd"
```

**Expected:**
- If `/etc/passwd` exists in the sandbox chroot, it should return the sandbox copy (not the host's)
- Verify the content does NOT contain the host service user (e.g. `service:x:999`)
- If the sandbox has no /etc, should return `404`

---

## PT-04: Write with .. traversal

```bash
curl -s -o /dev/null -w '%{http_code}' -X POST $BASE/sandbox/$SID/fs/write \
  -H 'Content-Type: application/json' \
  -d '{"path": "/../../../tmp/pwned.txt", "content": "escaped"}'
```

**Expected:** HTTP `400`

**Verify host is clean:**
```bash
docker compose exec agentjail sh -c 'cat /tmp/pwned.txt 2>&1'
```
Expected: `"No such file or directory"` — the file was NOT created on the host.

---

## PT-05: Write with double-encoded traversal

```bash
curl -s -o /dev/null -w '%{http_code}' -X POST $BASE/sandbox/$SID/fs/write \
  -H 'Content-Type: application/json' \
  -d '{"path": "/home/..%2F..%2F..%2Ftmp%2Fpwned.txt", "content": "escaped"}'
```

**Expected:** HTTP `400` or `404` — must NOT create file outside sandbox

---

## PT-06: Mkdir with traversal

```bash
curl -s -o /dev/null -w '%{http_code}' -X POST $BASE/sandbox/$SID/fs/mkdir \
  -H 'Content-Type: application/json' \
  -d '{"path": "/../../../tmp/evil_dir"}'
```

**Expected:** HTTP `400`

---

## PT-07: Remove with traversal

```bash
curl -s -o /dev/null -w '%{http_code}' \
  -X DELETE "$BASE/sandbox/$SID/fs/remove?path=/../../../tmp"
```

**Expected:** HTTP `400`

---

## PT-08: List with traversal

```bash
curl -s -o /dev/null -w '%{http_code}' \
  "$BASE/sandbox/$SID/fs/list?path=/../../../"
```

**Expected:** HTTP `400`

---

## PT-09: Stat with traversal

```bash
curl -s -o /dev/null -w '%{http_code}' \
  "$BASE/sandbox/$SID/fs/stat?path=/../../../etc/passwd"
```

**Expected:** HTTP `400`

---

## PT-10: Symlink escape — create symlink pointing outside sandbox

First, create a symlink inside the sandbox that points to the host:

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "ln -s /var/lib/agentjail /home/escape_link 2>&1; echo exit=$?"}'
```

Then try to read through it via the filesystem API:

```bash
curl -s -o /dev/null -w '%{http_code}' \
  "$BASE/sandbox/$SID/fs/read?path=/home/escape_link/state.json"
```

**Expected:**
- Either the symlink creation fails (no /var/lib/agentjail in chroot) OR
- The API detects the symlink escapes and returns `400` or `404` OR
- The resolved path is within the sandbox (symlink resolves to sandbox root, not host)
- Must NOT return the actual host state.json content

---

## PT-11: Path with null bytes

```bash
curl -s -o /dev/null -w '%{http_code}' \
  "$BASE/sandbox/$SID/fs/read?path=/home/test%00/../../../etc/passwd"
```

**Expected:** HTTP `400` or `422` — null bytes in paths must be rejected

---

## PT-12: Very long path

```bash
LONG_PATH=$(python3 -c "print('/home/' + 'a/' * 500 + 'file.txt')")
curl -s -o /dev/null -w '%{http_code}' \
  "$BASE/sandbox/$SID/fs/read?path=$LONG_PATH"
```

**Expected:** HTTP `400`, `404`, or `422` — not a server crash (500)

---

**Cleanup:**

```bash
curl -s -X DELETE "$BASE/sandbox/$SID?force=true" > /dev/null
```
