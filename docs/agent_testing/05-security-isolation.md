# 05 — Security Isolation Tests

**Priority: P0 — run after every significant change.**

These tests verify that sandboxed commands cannot see, modify, or escape the host environment. Failures here are security vulnerabilities.

**Setup:** Create a sandbox with network disabled (default).

```bash
SID=$(curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
```

---

## SEC-01: Cannot see host filesystem — /var

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "ls /var/lib/agentjail 2>&1; echo exit=$?"}'
```

**Expected:**
- `stdout` contains `"No such file or directory"` or similar error
- The sandbox must NOT be able to access `/var/lib/agentjail` (contains other sandbox roots and state)

---

## SEC-02: Cannot see host filesystem — service code

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "cat /home/service/app/src/agentjail/config.py 2>&1; echo exit=$?"}'
```

**Expected:**
- `stdout` contains `"No such file or directory"` — host application code is not mounted

---

## SEC-03: Cannot see /proc

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "ls /proc 2>&1; echo exit=$?"}'
```

**Expected (chroot runner):**
- `stdout` contains `"No such file or directory"` — /proc is not available

**Expected (nsjail runner):**
- If /proc is bind-mounted by nsjail, it should show only sandbox-local PIDs.
- `ls /proc` output should NOT contain the host PID namespace's processes.
- Validate: `ls /proc/1/cmdline` should show the sandboxed process, not the host init.

---

## SEC-04: Cannot see host processes

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "ps aux 2>&1 || echo ps-not-available"}'
```

**Expected:**
- Either `ps` is not available (exit_code != 0) or it shows only sandbox-local processes
- Must NOT show `uvicorn`, `nsjail`, or any host process names

---

## SEC-05: Network is isolated (no outbound connectivity)

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo test > /dev/tcp/8.8.8.8/53 2>&1; echo exit=$?"}'
```

**Expected:**
- The connection must fail — either `"Connection refused"`, `"Network is unreachable"`, or `"No such file or directory"`
- exit code != 0

---

## SEC-06: Network is isolated — wget/curl unavailable or fail

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "wget -q -O- http://example.com 2>&1 || curl -s http://example.com 2>&1; echo exit=$?"}'
```

**Expected:**
- Commands either not found or return network errors
- Must NOT return HTML content from example.com

---

## SEC-07: Network enabled sandbox CAN connect (if runner supports it)

```bash
SID_NET=$(curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{"network": true}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

curl -s -X POST $BASE/sandbox/$SID_NET/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo test > /dev/tcp/8.8.8.8/53 2>&1; echo exit=$?"}'
```

**Expected:**
- With `network: true`, outbound connections should be allowed (or at least not blocked by namespace isolation)
- This test may still fail if the container itself has no outbound route; that's acceptable

**Cleanup:**
```bash
curl -s -X DELETE "$BASE/sandbox/$SID_NET?force=true" > /dev/null
```

---

## SEC-08: Sandbox runs as unprivileged user (uid 1000)

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "id"}'
```

**Expected:**
- `stdout` contains `uid=1000`
- Must NOT show `uid=0` (root)

---

## SEC-09: Cannot write to system directories

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "touch /usr/bin/evil 2>&1; echo exit=$?"}'
```

**Expected:**
- `stdout` contains `"Read-only file system"` or `"Permission denied"` or `"No such file or directory"`
- The write must fail

---

## SEC-10: Cannot write to /etc

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo pwned > /etc/passwd 2>&1; echo exit=$?"}'
```

**Expected:**
- Write must fail with permission denied or read-only filesystem
- Even if it "succeeds" in the chroot runner, it must NOT affect the host /etc/passwd

**Verify host is unaffected (run OUTSIDE the sandbox):**
```bash
docker compose exec agentjail head -1 /etc/passwd
```
Expected: Should show the original first line (e.g. `root:x:0:0:root:/root:/bin/bash`), not `"pwned"`

---

## SEC-11: PID namespace isolation

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo $$"}'
```

**Expected:**
- `stdout` contains a low PID number (e.g. `1`, `2`, or a small number)
- Must NOT be a high PID (e.g. >100) which would indicate the host PID namespace leaked

---

## SEC-12: Cannot kill processes outside sandbox

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "kill -0 1 2>&1; echo exit=$?"}'
```

**Expected:**
- Either `kill` command fails (no permission, no such process, or PID 1 is the sandbox's own init)
- Must NOT be able to signal the host PID 1

---

## SEC-13: Two sandboxes cannot see each other's files

```bash
# Create a second sandbox
SID2=$(curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Write in sandbox 1
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo secret > /home/private.txt"}'

# Try to read from sandbox 2
curl -s -X POST $BASE/sandbox/$SID2/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "cat /home/private.txt 2>&1; echo exit=$?"}'
```

**Expected:**
- Sandbox 2 returns `"No such file or directory"` — sandboxes have separate filesystems

**Cleanup:**
```bash
curl -s -X DELETE "$BASE/sandbox/$SID2?force=true" > /dev/null
```

---

## SEC-14: Cannot escape chroot with .. traversal from inside sandbox

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "cat /../../../etc/hostname 2>&1; ls /../../../var/lib 2>&1; echo exit=$?"}'
```

**Expected:**
- Path traversal via `..` from within the sandbox should not escape the chroot
- `cat /../../../etc/hostname` should either fail or read the sandbox's own /etc/hostname (not the host's)

---

## SEC-15: Fork bomb is contained

```bash
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": ":(){ :|:& };:", "timeout": 5}'
```

**Expected:**
- The command should be killed or fail (resource limit reached)
- `timed_out` == true OR `exit_code` != 0
- The agentjail service must remain responsive after this test

**Verify service is still alive:**
```bash
curl -s -o /dev/null -w '%{http_code}' $BASE/sandbox
```
Expected: `200`

---

**Cleanup:**

```bash
curl -s -X DELETE "$BASE/sandbox/$SID?force=true" > /dev/null
```
