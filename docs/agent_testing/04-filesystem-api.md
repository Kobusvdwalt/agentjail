# 04 — Filesystem API Tests

Tests for the sandbox filesystem endpoints: read, write, list, mkdir, remove, stat.

**Setup:** Create a sandbox.

```bash
SID=$(curl -s -X POST $BASE/sandbox \
  -H 'Content-Type: application/json' \
  -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
```

---

## FS-01: Write a file

```bash
curl -s -X POST $BASE/sandbox/$SID/fs/write \
  -H 'Content-Type: application/json' \
  -d '{"path": "/home/hello.txt", "content": "hello world"}'
```

**Expected:**
- HTTP 200
- `status` == `"written"`
- `path` == `"/home/hello.txt"`

---

## FS-02: Read a file

```bash
curl -s "$BASE/sandbox/$SID/fs/read?path=/home/hello.txt"
```

**Expected:**
- HTTP 200
- `path` == `"/home/hello.txt"`
- `content` == `"hello world"`

---

## FS-03: Create a directory

```bash
curl -s -X POST $BASE/sandbox/$SID/fs/mkdir \
  -H 'Content-Type: application/json' \
  -d '{"path": "/home/projects/deep/nested"}'
```

**Expected:**
- HTTP 200
- `status` == `"created"`
- `path` == `"/home/projects/deep/nested"`

---

## FS-04: Write into nested directory

```bash
curl -s -X POST $BASE/sandbox/$SID/fs/write \
  -H 'Content-Type: application/json' \
  -d '{"path": "/home/projects/deep/nested/data.json", "content": "{\"key\": \"value\"}"}'
```

**Expected:**
- HTTP 200
- `status` == `"written"`

---

## FS-05: List directory contents

```bash
curl -s "$BASE/sandbox/$SID/fs/list?path=/home"
```

**Expected:**
- HTTP 200
- Response is a JSON array
- Contains entries with `name` == `"hello.txt"` (kind `"file"`) and `name` == `"projects"` (kind `"directory"`)
- Each entry has fields: `name`, `path`, `kind`, `size`, `mode`, `modified`

---

## FS-06: List root directory

```bash
curl -s "$BASE/sandbox/$SID/fs/list?path=/"
```

**Expected:**
- HTTP 200
- Response is a JSON array
- Contains entries for standard sandbox directories: `home`, `tmp`, `usr`, `etc`, `bin` (or symlink entries)

---

## FS-07: Stat a file

```bash
curl -s "$BASE/sandbox/$SID/fs/stat?path=/home/hello.txt"
```

**Expected:**
- HTTP 200
- `name` == `"hello.txt"`
- `kind` == `"file"`
- `size` == 11 (length of `"hello world"`)
- `mode` is an octal string (e.g. `"0o644"`)
- `modified` is a valid ISO timestamp

---

## FS-08: Stat a directory

```bash
curl -s "$BASE/sandbox/$SID/fs/stat?path=/home/projects"
```

**Expected:**
- HTTP 200
- `name` == `"projects"`
- `kind` == `"directory"`

---

## FS-09: Remove a file

```bash
curl -s -X POST $BASE/sandbox/$SID/fs/write \
  -H 'Content-Type: application/json' \
  -d '{"path": "/home/to_delete.txt", "content": "gone soon"}'

curl -s -X DELETE "$BASE/sandbox/$SID/fs/remove?path=/home/to_delete.txt"
```

**Expected (remove):**
- HTTP 200
- `status` == `"removed"`

**Verify:** Reading the file should return 404:

```bash
curl -s -o /dev/null -w '%{http_code}' "$BASE/sandbox/$SID/fs/read?path=/home/to_delete.txt"
```

Expected: `404`

---

## FS-10: Remove a directory recursively

```bash
curl -s -X DELETE "$BASE/sandbox/$SID/fs/remove?path=/home/projects"

# Verify it's gone
curl -s -o /dev/null -w '%{http_code}' "$BASE/sandbox/$SID/fs/stat?path=/home/projects"
```

**Expected:**
- Remove returns HTTP 200
- Stat returns HTTP `404`

---

## FS-11: Write creates parent directories automatically

```bash
curl -s -X POST $BASE/sandbox/$SID/fs/write \
  -H 'Content-Type: application/json' \
  -d '{"path": "/home/auto/parent/file.txt", "content": "autocreated"}'

curl -s "$BASE/sandbox/$SID/fs/read?path=/home/auto/parent/file.txt"
```

**Expected:**
- Write returns HTTP 200
- Read returns `content` == `"autocreated"`

---

## FS-12: Read non-existent file

```bash
curl -s -o /dev/null -w '%{http_code}' "$BASE/sandbox/$SID/fs/read?path=/home/does_not_exist.txt"
```

**Expected:** HTTP `404`

---

## FS-13: Files written via API are readable via shell (and vice versa)

```bash
# Write via API
curl -s -X POST $BASE/sandbox/$SID/fs/write \
  -H 'Content-Type: application/json' \
  -d '{"path": "/home/api_file.txt", "content": "from-api"}'

# Read via shell
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "cat /home/api_file.txt"}'
```

**Expected:**
- Shell command returns `stdout` == `"from-api\n"` or `"from-api"`

```bash
# Write via shell
curl -s -X POST $BASE/sandbox/$SID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo from-shell > /home/shell_file.txt"}'

# Read via API
curl -s "$BASE/sandbox/$SID/fs/read?path=/home/shell_file.txt"
```

**Expected:**
- Read returns `content` == `"from-shell\n"`

---

**Cleanup:**

```bash
curl -s -X DELETE "$BASE/sandbox/$SID?force=true" > /dev/null
```
