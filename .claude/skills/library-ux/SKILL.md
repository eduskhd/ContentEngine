# library-ux

**Type:** Project skill  
**Scope:** Library UX audit — usability at scale (50 creators, 1,000 videos, 10,000 clips)  
**When to use:** After any Library feature change, after adding filtering/sorting/bulk-action capabilities, before UX milestones

---

## Purpose

Ensure the Library remains fast and easy to manage as data volume grows. Specifically targets the friction of too many clicks, poor discoverability, and performance degradation at scale.

---

## Trigger

```
/library-ux
```

---

## Scale Targets

The Library must remain usable at:
- 50 creators (active content producers)
- 1,000 videos (ingested long-form sources)
- 10,000 clips (generated shorts ready for review)

Any flow that becomes untenable at this scale is a UX defect, not a future concern.

---

## Audit Areas

### 1 — Creator Organization

- [ ] Creators visible at a glance without scrolling past 10+ cards
- [ ] Creator search (by name or slug) works
- [ ] Creators sorted meaningfully (most recent activity, most clips, alphabetical — user's choice)
- [ ] Creator cards show clip count, video count, last activity date
- [ ] "Unassigned" bucket always visible, never hidden below the fold
- [ ] No creator requires more than 2 clicks to view their clips

**At 50 creators:** can the user find a specific creator in under 5 seconds?

### 2 — Collections

- [ ] Collections panel visible without extra navigation
- [ ] Create collection: 1 click + name input
- [ ] Rename collection: double-click or inline edit
- [ ] Delete collection: 1 confirm modal, not multi-step
- [ ] Assign clips to collection: bulk action from multiselect
- [ ] Collection filter updates clip list instantly (no page reload)
- [ ] Empty collection shows helpful empty state
- [ ] Collection clip count displayed on collection card

**At 20 collections:** can the user find a specific collection in under 3 seconds?

### 3 — Unassigned Clips

- [ ] Unassigned bucket always accessible from Library nav
- [ ] Shows count of unassigned clips
- [ ] Bulk assign unassigned clips to creator: 2 clicks max (select all → assign)
- [ ] Assigning from Unassigned removes clip from Unassigned immediately (optimistic UI)

### 4 — Search

- [ ] Global search covers clip titles, video titles, creator names, tags
- [ ] Search results appear within 300ms (client-side filter or fast API)
- [ ] Search clears easily (X button or Escape)
- [ ] Search result count shown
- [ ] No search returns a clear "no results" state, not a blank screen

### 5 — Filters

- [ ] Filter chips: platform (TikTok, Reels, Shorts), status (approved, rejected, pending, all), creator, date range
- [ ] Filters combine correctly (AND logic: platform=TikTok AND status=approved)
- [ ] Filter count badge shows how many filters are active
- [ ] Clear all filters: 1 click
- [ ] Filter state persists across navigation (back button doesn't reset filters)
- [ ] Saved filters: user can save a filter set with a name and recall it
- [ ] Saved filters visible in filter panel (not buried in settings)

**At 10 saved filters:** still readable without scrolling?

### 6 — Sorting

- [ ] Sort options: virality score (high → low), date created (newest first), duration, status
- [ ] Sort direction toggleable (ascending/descending)
- [ ] Current sort displayed clearly in UI
- [ ] Sort persists within session

### 7 — Multiselect & Bulk Actions

- [ ] Checkbox appears on hover (not always visible, to reduce clutter)
- [ ] Clicking checkbox selects clip without opening modal
- [ ] Select all on current page: 1 click
- [ ] Select all matching filter (not just current page): available when > page size results
- [ ] Bulk action bar appears when any clip is selected
- [ ] Bulk actions: assign to collection, change status, delete, download
- [ ] Bulk delete requires confirmation with count ("Delete 47 clips?")
- [ ] Bulk action bar dismisses when selection is cleared
- [ ] Selection count shown in bulk action bar
- [ ] Selecting 200+ clips doesn't freeze the UI

### 8 — Bulk Delete Safety

- [ ] Confirmation modal shows exact count
- [ ] Confirmation modal names what will be deleted (clips, or videos + clips)
- [ ] No undo — user must understand this is permanent
- [ ] Progress indicator for large bulk deletes (not a spinner that freezes at 99%)
- [ ] If some deletes fail, report partial success clearly

### 9 — Pagination / Infinite Scroll

- [ ] Initial load: ≤ 50 clips rendered (not 10,000)
- [ ] Scroll or "Load more" loads next batch
- [ ] Scroll position preserved when navigating to clip and back
- [ ] Total count shown ("Showing 50 of 1,247 clips")
- [ ] Filters + pagination work together correctly (filters reset pagination to page 1)

### 10 — Performance

- [ ] Library initial load: ≤ 2s at 1,000 clips (API response + render)
- [ ] Filter change: ≤ 500ms to updated result
- [ ] Bulk select 200 clips: ≤ 200ms UI response
- [ ] `GET /clips?limit=50` returns in ≤ 500ms (check via DevTools Network or API call)
- [ ] No N+1 queries visible in server logs when loading Library

### 11 — Responsive

- [ ] Library usable on 1280px (laptop)
- [ ] Library usable on 1024px (smaller laptop / tablet landscape)
- [ ] Cards reflow correctly at each breakpoint
- [ ] Bulk action bar visible on narrower screens
- [ ] Filter panel collapsible on narrow screens (not always visible)

---

## Click-Count Audit

For each of these flows, count the clicks required. Flag any that exceed the target:

| Flow | Target | Measured | Pass/Fail |
|------|--------|----------|-----------|
| Find a specific creator | ≤ 2 clicks | | |
| View all clips for a creator | ≤ 2 clicks | | |
| Apply a saved filter | ≤ 1 click | | |
| Bulk assign 10 clips to collection | ≤ 4 clicks | | |
| Bulk delete 10 clips | ≤ 3 clicks | | |
| Create a new collection | ≤ 2 clicks + name | | |
| Download a single clip | ≤ 2 clicks | | |
| Open caption editor for a clip | ≤ 2 clicks | | |

---

## Anti-Patterns to Flag

- Requiring page reload after filter change
- "Apply" button for filters that should be instant
- No empty state when a filter returns no results
- Modal chains (confirm → another confirm → another confirm)
- Filters that reset when navigating away
- Search that only searches current visible page
- Bulk actions that don't show progress for >5 items
- Card hover state missing on touch/tablet

---

## Output Format

```
## library-ux Audit — [date]

### Click-Count Results
[table as above]

### Issues Found
| ID | Area | Severity | Description | Recommendation |
|----|------|----------|-------------|----------------|
| LUX-001 | Filters | High | ... | ... |

### Performance Findings
[API response times, render times]

### Scale Projection
At 10,000 clips with current implementation: [assessment]

### Summary
X areas audited. Y issues found. Z high-priority.
```

---

## Notes

- If server is running, use `GET /clips?limit=1000` to observe response time and payload size.
- Check `api/main.py` for clips endpoint — verify `limit` and `offset` params are enforced.
- Check `dashboard/index.html` for how clips are rendered — virtual scroll vs DOM-all.
- When suggesting UX improvements, prefer additive changes (new button, new filter option) over restructuring existing flows.
