# Claude Skills — ContentEngine

Active skills and when to use them.  
Last updated: 2026-09-12

---

## Project Skills (`.claude/skills/`)

These skills are scoped to ContentEngine and versioned with the repository.

---

### clipper-qa

| Field | Value |
|-------|-------|
| **Type** | Project skill |
| **Purpose** | Full functional QA of the dashboard — buttons, flows, modals, Library, New Job, Clips, Captions, Publishing Center |
| **Source** | `.claude/skills/clipper-qa/SKILL.md` |
| **When to use** | After any feature addition, workflow change, or API modification that affects user-visible behavior |
| **Scope** | Project |
| **Command** | `/clipper-qa` |

**Covers:** New Job flow, Library, Collections, Unassigned, Bulk actions, Clip modal, Caption editor, Export, Publishing Center, Creators, Filters, Sorting.  
**Cycle:** AUDIT → TEST → FIX → RETEST. Tests real app when server is running.

---

### video-security

| Field | Value |
|-------|-------|
| **Type** | Project skill |
| **Purpose** | Security audit for video ingestion, media processing, and storage |
| **Source** | `.claude/skills/video-security/SKILL.md` |
| **When to use** | After changes to URL ingestion, file upload, FFmpeg args, auth, storage paths, or API endpoints; before production milestones |
| **Scope** | Project |
| **Command** | `/video-security` |

**Covers:** SSRF via URL ingestion, path traversal in file upload, MIME bypass, FFmpeg command injection, ASS path injection, IDOR, stored XSS, upload size limits, yt-dlp security, secrets in code/logs, future OAuth token storage, webhook validation, dependency CVEs, concurrent race conditions.

---

### production-readiness

| Field | Value |
|-------|-------|
| **Type** | Project skill |
| **Purpose** | Structured pre-release assessment — emits a readiness verdict |
| **Source** | `.claude/skills/production-readiness/SKILL.md` |
| **When to use** | Before milestone releases, before exposing to external users, after architectural changes |
| **Scope** | Project |
| **Command** | `/production-readiness` |

**Covers:** Job system, queue/workers, retries, idempotency, crash recovery, storage lifecycle, database, performance, observability, security gates, E2E repeatability.  
**Verdicts:** NOT READY / INTERNAL ALPHA READY / LIMITED BETA READY / PRODUCTION READY  
**Baseline:** Phase 2.5 assessment in `docs/PRODUCTION_READINESS.md` (INTERNAL ALPHA READY as of 2026-09-10).

---

### library-ux

| Field | Value |
|-------|-------|
| **Type** | Project skill |
| **Purpose** | Library UX audit at scale — 50 creators, 1,000 videos, 10,000 clips |
| **Source** | `.claude/skills/library-ux/SKILL.md` |
| **When to use** | After Library feature changes (filters, bulk actions, collections, sorting, pagination) |
| **Scope** | Project |
| **Command** | `/library-ux` |

**Covers:** Creator organization, Collections, Unassigned, search, filters, saved filters, sorting, multiselect, select all, bulk actions, bulk delete safety, pagination, performance at scale, responsive behavior.  
**Special focus:** Flows requiring too many clicks. Click-count targets for common operations.

---

### frontend-visual-qa

| Field | Value |
|-------|-------|
| **Type** | Project skill |
| **Purpose** | Visual and responsive QA across breakpoints |
| **Source** | `.claude/skills/frontend-visual-qa/SKILL.md` |
| **When to use** | After substantial frontend changes: layout restructuring, new modals, CSS changes, new components |
| **Scope** | Project |
| **Command** | `/frontend-visual-qa` |

**Covers:** Desktop (1440px), Laptop (1280px), Small laptop (1024px), Tablet (768px). Layout overflow, spacing, alignment, modals, dropdowns, buttons, empty states, loading states, text wrapping, responsive grid, dark mode consistency, basic accessibility.

---

### secure-dependencies

| Field | Value |
|-------|-------|
| **Type** | Project skill |
| **Purpose** | Dependency security and maintenance review |
| **Source** | `.claude/skills/secure-dependencies/SKILL.md` |
| **When to use** | When adding new dependencies; before production milestones; monthly maintenance check |
| **Scope** | Project |
| **Command** | `/secure-dependencies` |

**Covers:** Python dependencies (`requirements.txt`), Node.js dependencies (`package.json`), CVE checks, abandonment risk, supply-chain review, unnecessary dependency detection, version pinning strategy.  
**Tools:** `pip-audit`, `safety`, `npm audit`.

---

## Global Skills (`~/.claude/skills/`)

These skills are installed globally and available across all projects.

| Skill | Purpose |
|-------|---------|
| `content-autopsy` | Post-mortem analysis of content performance |
| `hook-anatomy` | Dissects video opening hooks |
| `platform-fluency` | Scores content fit across TikTok/Reels/Shorts |
| `repurpose-engine` | Transforms clips into multiple content formats |
| `trend-radar` | Identifies trending formats and sounds |
| `video-analyzer` | Deep semantic analysis of video content |
| `video-review` | Visual and production quality review |
| `virality-analyzer` | Virality scoring 0–100 |

These global skills are content analysis tools used within the ContentEngine pipeline. They do not overlap with the project-specific QA/security/readiness skills above.

---

## Installed Plugins

No MCP plugins are currently installed for this project.

The global Claude Code settings do not include any marketplace plugins for frontend design or security guidance at this time. The project skills above cover these domains directly.

**Evaluated and not installed:**
- No official Anthropic plugin marketplace was available for direct programmatic inspection. Plugin catalog was not accessible via CLI at audit time. Project skills created instead.
- No third-party security or design plugins were installed — none were evaluated as sufficiently trusted or non-redundant with existing coverage.

---

## When to Use Which Skill

```
Feature addition (any area)
  → /clipper-qa

Frontend changes (layout, modals, CSS, components)
  → /frontend-visual-qa
  → /clipper-qa (if interactive behavior also changed)

Changes touching: URLs, file upload, FFmpeg, auth, storage, API security
  → /video-security

Library UX changes (filters, bulk actions, collections)
  → /library-ux
  → /clipper-qa

Before milestone release / exposing to new users
  → /production-readiness
  → /video-security (if any security-relevant change since last audit)

New dependency added / monthly check
  → /secure-dependencies
```

**Do not run all skills after every change.** Each skill has context overhead — use it only when the change touches its domain.

---

## Maintenance

Update this file when:
- A new project skill is added or removed
- A skill's scope or trigger changes
- A plugin is installed or uninstalled
- Global skills relevant to the project change
