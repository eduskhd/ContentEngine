# video-security

**Type:** Project skill  
**Scope:** Security audit for video ingestion, processing, and storage  
**When to use:** Before production milestones; after changes to URL ingestion, file upload, FFmpeg, auth, storage, or API endpoints

---

## Purpose

Specialized security audit for ContentEngine's attack surface. Covers every point where untrusted input (URLs, filenames, file content, metadata) enters the system, and every operation that touches the filesystem, subprocess execution, or network.

---

## Trigger

```
/video-security
```

---

## Threat Model: ContentEngine-Specific Risks

### T1 — SSRF via URL Ingestion
**Attack:** Attacker submits `http://169.254.169.254/` (AWS metadata), `http://10.0.0.1/admin`, `file:///etc/passwd`, or `http://localhost:6379/` to the New Job URL field.  
**Check:** `engine/downloader.py` → `validate_url()` must block private IP ranges (10.x, 172.16-31.x, 192.168.x), loopback (127.x, ::1), link-local (169.254.x.x), and `file://` scheme.  
**Verify:** All blocked ranges are in the deny list. No bypass via DNS rebinding mitigations.

### T2 — Path Traversal in File Upload
**Attack:** Upload file named `../../etc/passwd` or `..\..\Windows\System32\cmd.exe`.  
**Check:** `api/main.py` upload handler → filename sanitization uses `Path(filename).name` (strips directory components).  
**Verify:** Test with `../evil.mp4`, `..%2F..%2Fevil.mp4`, `....//evil.mp4`.

### T3 — MIME Type Bypass (Malicious Media)
**Attack:** Upload a file with `.mp4` extension that is actually a shell script, a ZIP bomb, or a malformed media file designed to exploit FFmpeg/libav vulnerabilities.  
**Check:** Does the server validate content type beyond file extension? Is there a `python-magic` or `filetype` check?  
**Verify:** Check ingest path for content-based MIME validation.

### T4 — FFmpeg Command Injection
**Attack:** A filename or metadata value containing shell metacharacters gets interpolated into an FFmpeg command string (e.g., `; rm -rf /`).  
**Check:** `engine/renderers/render_clip.py`, `engine/proxy.py`, `engine/captions/renderer.py` — all FFmpeg calls must use list-form `subprocess` (not shell=True string interpolation).  
**Verify:** Grep for `subprocess.run(..., shell=True)`. Check every variable inserted into FFmpeg argument lists.

### T5 — ASS Caption Path Injection
**Attack:** A clip path containing `:` or `\` inserted into the FFmpeg ASS filter string causes malformed filter graph or path escape.  
**Check:** `engine/renderers/render_clip.py` → `ass_path.replace("\\", "/").replace(":", "\\:")` present and applied before filter string construction.  
**Verify:** Test with a clip path containing spaces, colons, backslashes.

### T6 — IDOR on Clip/Job/Video Resources
**Attack:** User guesses UUIDs of other users' clips and accesses/deletes them via `GET /clips/{id}`, `DELETE /clips/{id}`, `POST /jobs/{id}/retry`.  
**Check:** All resource endpoints — is there any ownership check? (Current state: single-user tool, no auth. Document risk, do not add auth gate unless in scope.)  
**Verify:** Note the current authorization model and flag if scope changes.

### T7 — Stored XSS via Metadata Fields
**Attack:** A video title, creator name, or caption text containing `<script>alert(1)</script>` is stored in DB and rendered unescaped in the SPA dashboard.  
**Check:** `dashboard/index.html` — all dynamic content insertions must use `.textContent` or `innerText`, not `.innerHTML` with raw data, OR must sanitize before insertion.  
**Verify:** Search for `.innerHTML` usage with data from API responses. Check title, creator name, review_notes, captions fields.

### T8 — Upload Size Limit
**Attack:** Submit a 100GB file to exhaust disk and memory.  
**Check:** `api/main.py` upload handler → 10 GB limit with streaming check present.  
**Verify:** The limit is enforced before full file read (streaming check, not post-read).

### T9 — yt-dlp Security
**Attack:** Craft a URL that causes yt-dlp to execute arbitrary code via a malicious playlist, redirect, or plugin.  
**Check:** yt-dlp version in `requirements.txt` is current. `--no-playlist` or equivalent limits scope. No `--exec` or `--postprocessor-args` with user-supplied values.  
**Verify:** Check downloader.py for yt-dlp argument construction.

### T10 — Secrets in Code / Logs
**Attack:** API keys, tokens, or credentials accidentally committed or logged.  
**Check:** `.env.example`, `engine/config.py`, `server.py` — no hardcoded secrets. Logs (server.log, server_err.log) do not contain API keys or auth tokens.  
**Verify:** `grep -r "sk-" . && grep -r "Bearer " . && grep -r "api_key" .` for any literal secret patterns.

### T11 — Future OAuth Token Storage
**Attack:** When OAuth flows are activated for social publishing, tokens stored insecurely (plaintext DB, unencrypted logs).  
**Check:** `publishers/` adapters and `api/main.py` OAuth routes — token storage path and encryption.  
**Note:** Currently inactive — flag for when OAuth is activated.

### T12 — Webhook Endpoint Validation
**Attack:** When webhooks are added, an attacker sends forged POST requests to trigger state changes.  
**Check:** Any webhook endpoint must validate HMAC signature or shared secret.  
**Note:** Currently not implemented — flag for when webhooks are added.

### T13 — Dependency Vulnerabilities
**Attack:** Known CVE in `faster-whisper`, `yt-dlp`, `fastapi`, `opencv-python`, etc.  
**Check:** Cross-reference `requirements.txt` against known CVE databases. Run `pip-audit` if available.  
**Verify:** Versions pinned with `>=` — check minimum versions are post-known-CVE.

### T14 — Concurrent Job Race Conditions
**Attack:** Two simultaneous requests to `POST /jobs/{id}/retry` create duplicate job entries.  
**Check:** `api/main.py` retry endpoint and `engine/database.py` `create_job()` — INSERT OR IGNORE / unique constraint prevents duplicate rows.  
**Verify:** Confirm the idempotency fix from Phase 2.5 is in place.

---

## Audit Procedure

### Phase 1 — Static Analysis
1. Read `engine/downloader.py` — validate SSRF protections
2. Read `api/main.py` — upload handler, filename sanitization, size limits, CORS settings
3. Read `engine/renderers/render_clip.py` — FFmpeg arg construction (list vs shell string)
4. Read `engine/proxy.py` — FFmpeg arg construction
5. Read `engine/captions/renderer.py` — ASS path handling
6. Read `dashboard/index.html` — innerHTML usage, XSS sinks
7. Grep for `shell=True` in all Python files
8. Grep for `.innerHTML` in dashboard HTML
9. Grep for hardcoded secrets or API key patterns

### Phase 2 — Dynamic Checks (if server running)
1. Submit a private IP URL → expect 400 blocked
2. Submit `http://localhost:8000/health` → expect 400 blocked
3. Upload file named `../test.mp4` → verify stored as `test.mp4` not traversal
4. Check response headers for security headers (X-Content-Type-Options, etc.)

### Phase 3 — Report
Classify each finding:
- **Critical:** Immediate exploitation possible (RCE, data exfiltration)
- **High:** Exploitable with some effort (SSRF bypass, stored XSS)
- **Medium:** Risk present but mitigated by context (IDOR in single-user tool)
- **Low/Info:** Defense-in-depth improvement

---

## Output Format

```
## video-security Audit — [date]

### Critical
(none / list)

### High
(none / list)

### Medium
(none / list)

### Low / Info
(none / list)

### Accepted Risks (documented)
- CORS allow_origins=* — localhost-only tool, acceptable until exposed
- No auth — single operator, acceptable until external users
- IDOR — no multi-user, acceptable until workspace_id added

### Pre-Production Gate
PASS / CONDITIONAL PASS / FAIL
```

---

## Notes

- Do not add authentication gates or CORS restrictions unless this is in scope for the current milestone.
- FFmpeg CVEs are frequent — check https://nvd.nist.gov/vuln/search for `ffmpeg` before production deployments.
- yt-dlp changes frequently — pin to a tested version before deploying.
