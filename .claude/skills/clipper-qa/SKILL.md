# clipper-qa

**Type:** Project skill  
**Scope:** Full functional QA — ContentEngine dashboard  
**When to use:** After any feature addition, workflow change, or API modification

---

## Purpose

Perform a complete functional review of the ContentEngine dashboard. Tests real app behavior — not just code review. Follows the AUDIT → TEST → FIX → RETEST cycle.

---

## Trigger

```
/clipper-qa
```

Or invoked by Claude when a feature-level change requires validation.

---

## What it covers

### Navigation & Layout
- Sidebar links (Library, New Job, Creators, Publishing Center)
- Active state highlighting
- Responsive layout at 1280px, 1024px, 768px
- Dark mode consistency

### New Job Flow
- Source tabs (URL / File Upload)
- URL validation and duplicate detection feedback
- File upload (drag & drop + browse)
- Creator dropdown (suggest existing, create new)
- Series field
- Submit button state (disabled when empty, loading when processing)
- SSE progress stream (step updates, progress bar)
- Job completion → clips available

### Library
- Creator cards display (name, clip count, avatar)
- Unassigned bucket visibility
- Collections panel (create, rename, delete)
- Collection assignment drag or button
- Filter chips (platform, status, creator, date)
- Sort options (date, virality, duration)
- Search by title/slug
- Saved filters persistence across page reload
- Pagination / infinite scroll
- Empty state messages

### Videos
- Video list per creator
- Thumbnail display
- Click → video detail / clips
- Delete video → confirm modal → cascade to clips

### Clips
- Clip cards (thumbnail, score, platform badges, status)
- Clip modal: video preview, caption display, metadata
- Caption editor: word edit, preset change, re-render trigger
- Download single clip
- Download all (ZIP)
- Review notes field
- Status change (approve / reject)
- Prepublish decision badge

### Creators
- Creator list
- Create creator form (name, slug, platform targets)
- Edit creator
- Delete creator → confirm modal
- Creator stats (videos, clips, published count)

### Collections & Bulk Actions
- Multiselect (checkbox per card)
- Select all on page
- Bulk assign to collection
- Bulk delete → confirm modal with count
- Bulk status change
- Deselect all

### Filters & Sorting
- Filter by status (all, approved, rejected, pending)
- Filter by platform (TikTok, Instagram, Reels, Shorts)
- Filter by creator
- Sort by score descending/ascending
- Sort by date
- Filters persist across navigation

### Publishing Center
- Clip queue list
- Mark as ready
- Mark as published
- Platform badge display
- Publication state persistence

### Captions
- Caption preset selector (Bold, Minimal, Neon, etc.)
- Per-word editing in caption editor
- Style preview in modal
- Re-render with updated captions → new file generated
- Caption settings persisted in DB

### Export
- Single clip download (.mp4)
- Download all ZIP (per creator or global)
- ZIP cleanup after download (no temp file leak)

---

## Test Procedure

### Step 1 — AUDIT
Read `dashboard/index.html` and `api/main.py` to map all interactive elements and endpoints.

### Step 2 — TEST
If server is running at `http://localhost:8000`:
- Use Playwright (`npx playwright`) or `Invoke-WebRequest` to probe endpoints
- Exercise each UI flow listed above
- Check browser console for JS errors
- Check Network tab for 4xx/5xx responses

If server is not running:
- Static audit only: trace each button → event handler → API call → response handler
- Flag any broken handler chains

### Step 3 — FIX
For each issue found:
- Classify: Critical (blocks workflow) / High (feature broken) / Medium (UX degraded) / Low (cosmetic)
- Fix Critical and High issues immediately
- Document Medium and Low in `docs/KNOWN_ISSUES.md`

### Step 4 — RETEST
After each fix, retest the specific flow that was broken.  
Spot-check adjacent flows for regressions.

---

## Output Format

```
## clipper-qa Report — [date]

### ✅ Passing
- [list of flows tested and confirmed working]

### ❌ Issues Found
| ID | Severity | Area | Description | Status |
|----|----------|------|-------------|--------|
| QA-001 | Critical | New Job | ... | Fixed |

### ⚠️ Not Tested (reason)
- [flows skipped and why]

### Summary
X flows tested. Y issues found (A critical, B high, C medium, D low). Z fixed.
```

---

## Notes

- Do NOT use this skill after one-line config changes — overhead is not justified.
- Caption re-render test requires a clip with `caption_data` already populated.
- Publishing Center tests require at least one clip in `approved` status.
- Always check the browser console — JS errors are not always visible in UI.
