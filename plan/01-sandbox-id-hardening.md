# Plan 01: Sandbox ID Hardening

## Goal

Replace `uuid4()` sandbox IDs with high-entropy `secrets.token_urlsafe(32)` tokens (43 characters, 256 bits of entropy) to make sandbox IDs unguessable.

## Why

UUID4 has 122 bits of entropy. `secrets.token_urlsafe(32)` provides 256 bits — making brute-force enumeration infeasible even without authentication. Since sandbox IDs are used in URL paths and as the sole access control, they must be cryptographically strong.

## Files to Change

### `service-agentjail/src/agentjail/sandbox/manager.py`

1. **Remove import**: delete `from uuid import uuid4` (line 4)
2. **Add import**: add `import secrets`
3. **Replace both occurrences** of `sandbox_id = str(uuid4())` with `sandbox_id = secrets.token_urlsafe(32)`:
   - Line 56 (inside `sandbox_run`)
   - Line 93 (inside `sandbox_create`)

No other files reference UUID generation.

## Verification

- `secrets.token_urlsafe(32)` returns a 43-character URL-safe base64 string
- These are valid in filesystem paths (used for `sandbox_base_dir / sandbox_id`)
- These are valid in URL paths (used in `/api/v1/sandbox/{sandbox_id}`)
- URL-safe base64 uses `[A-Za-z0-9_-]` — no special chars that need escaping

## Test

After the change, run:
```bash
docker compose up --build
# Create a sandbox and confirm the ID is a 43-char token, not a UUID
curl -s -X POST http://localhost:8000/api/v1/sandbox -H 'Content-Type: application/json' -d '{}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'ID length: {len(d[\"id\"])}, ID: {d[\"id\"]}')"
```
Expected: `ID length: 43, ID: <base64url-string>`

## Reference

- See `docs/DESIGN.md` section "Two sandbox modes" for how IDs are used
- See `service-agentjail/src/agentjail/sandbox/manager.py` for the two call sites
