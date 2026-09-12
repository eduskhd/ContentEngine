# secure-dependencies

**Type:** Project skill  
**Scope:** Dependency security and maintenance review  
**When to use:** When adding new dependencies, before production milestones, periodically (monthly)

---

## Purpose

Review Python and JavaScript dependencies for known vulnerabilities, abandonment risk, and supply-chain concerns. Does NOT auto-update major versions — prioritizes security over freshness.

---

## Trigger

```
/secure-dependencies
```

---

## Dependency Files

| File | Type | Tool |
|------|------|------|
| `requirements.txt` | Python | pip-audit, safety |
| `package.json` | Node/JS | npm audit |
| `package-lock.json` | Node/JS (lockfile) | npm audit |

---

## Audit Procedure

### Phase 1 — Python Dependencies (`requirements.txt`)

**Current dependencies:**
```
opencv-python>=5.0.0
numpy>=2.0.0
librosa>=0.11.0
soundfile>=0.14.0
faster-whisper>=1.0.0
openai-whisper>=20250625
rich>=15.0.0
requests>=2.32.0
yt-dlp>=2024.1.0
fastapi>=0.115.0
uvicorn>=0.34.0
python-multipart>=0.0.20
aiofiles>=24.0.0
anthropic>=0.40.0
```

For each package:
1. **CVE check:** Search for known vulnerabilities in the specified version range minimum
2. **Maintenance check:** Is the package actively maintained? Last release within 12 months?
3. **Supply chain check:** Is the package from a trusted source (PyPI, known maintainer)?
4. **Scope check:** Is this package actually used? Remove unused dependencies.

**High-risk packages to check carefully:**
- `yt-dlp` — frequently updated for security and anti-bot patches; old versions may fail or have bypass vulnerabilities
- `opencv-python` — C extension with complex dependency chain; check for known media parsing CVEs
- `faster-whisper` — ML library; check for deserialization vulnerabilities in model loading
- `requests` — network library; ensure SSRF mitigations aren't bypassed by library version
- `python-multipart` — file upload parsing; check for multipart parsing CVEs
- `anthropic` — API SDK; check for credential handling issues

**Run if available:**
```powershell
pip-audit -r requirements.txt
# or
safety check -r requirements.txt
```

### Phase 2 — JavaScript Dependencies (`package.json`)

**Current dependencies:**
```json
{ "devDependencies": { "playwright": "^1.63.0" } }
```

- `playwright` — browser automation; check for known CVEs, verify version is current
- Only devDependency — not in production bundle

**Run:**
```powershell
npm audit
```

### Phase 3 — Unnecessary Dependencies

- [ ] Is every package in `requirements.txt` actually imported somewhere in the codebase?
- [ ] Is `openai-whisper` used alongside `faster-whisper`? (Both present — verify which is active)
- [ ] Any test-only packages in production `requirements.txt`?

### Phase 4 — Supply Chain Risk

For any package added in the last session or flagged as unfamiliar:
1. Verify package name matches the PyPI/npm canonical name (typosquatting check)
2. Check PyPI page for maintainer identity and download count
3. Check if package has a GitHub repo with recent commits
4. Verify install scripts don't run arbitrary code (`setup.py` inspection if concerned)

### Phase 5 — Version Pinning Strategy

Current strategy: `>=minimum.version` (floor pinning).

- [ ] Floor versions are above known CVEs for each package
- [ ] Floor versions tested and stable
- [ ] No packages pinned to exact version unnecessarily (prevents security patches)

**Update recommendation criteria:**
- Security patch available → recommend patch version bump (e.g., `>=1.0.1` → `>=1.0.2`)
- Major version bump → do NOT recommend automatically; require explicit testing
- Minor version bump with security fix → recommend with note to test

---

## Risk Classification

| Risk | Description | Action |
|------|-------------|--------|
| **Critical** | Active CVE with exploit in use, CVSS ≥ 9.0 | Update floor version immediately |
| **High** | CVE with exploit available, CVSS ≥ 7.0 | Update floor version, test before deploy |
| **Medium** | CVE without public exploit, CVSS 4.0–6.9 | Plan update in next sprint |
| **Low** | Outdated but no known CVE | Note for maintenance cycle |
| **Info** | Package unmaintained (>1yr no release) | Evaluate replacement |

---

## What NOT to do

- Do NOT run `pip install --upgrade` across all packages
- Do NOT bump `opencv-python` or `numpy` to latest without testing the pipeline
- Do NOT remove `openai-whisper` vs `faster-whisper` without verifying which is actually used
- Do NOT update `yt-dlp` to a pre-release or beta version

---

## Output Format

```
## secure-dependencies Report — [date]

### Python Dependencies
| Package | Current Min | Latest | CVEs | Risk | Recommendation |
|---------|------------|--------|------|------|----------------|
| yt-dlp | 2024.1.0 | x.y.z | none | Low | Update floor to 2025.1.0 |
...

### JS Dependencies
| Package | Current | Latest | CVEs | Risk | Recommendation |
|---------|---------|--------|------|------|----------------|
...

### Unnecessary Dependencies
(none / list with evidence)

### Supply Chain Notes
(none / list)

### Actions Required
1. [High priority items]

### Actions Recommended (non-urgent)
1. [Lower priority items]
```

---

## Notes

- `pip-audit` must be installed: `pip install pip-audit`
- `safety` is an alternative: `pip install safety && safety check`
- If neither is available, manually cross-reference minimum versions against https://osv.dev or https://nvd.nist.gov
- `yt-dlp` releases very frequently — check their GitHub releases for security-related changes
- `faster-whisper` and `openai-whisper` both present in requirements: verify in `engine/transcription.py` which is actually used; the unused one should be removed.
