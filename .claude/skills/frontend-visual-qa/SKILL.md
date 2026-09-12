# frontend-visual-qa

**Type:** Project skill  
**Scope:** Visual and responsive QA for ContentEngine dashboard  
**When to use:** After substantial frontend changes (layout, modals, new components, CSS/style changes)

---

## Purpose

Systematic review of visual correctness, responsiveness, and accessibility across the ContentEngine SPA. Focuses on what automated linters miss: overflow, alignment regressions, empty states, and interaction states.

---

## Trigger

```
/frontend-visual-qa
```

---

## Breakpoints to Test

| Name | Width | Represents |
|------|-------|-----------|
| Desktop | 1440px | Large laptop / external monitor |
| Laptop | 1280px | Standard laptop |
| Small laptop | 1024px | Smaller laptop / tablet landscape |
| Tablet | 768px | iPad portrait / small tablet |

Priority order: 1280px first (primary use case), then 1440px, 1024px, 768px.

---

## Audit Areas

### 1 — Layout & Overflow

- [ ] Sidebar never overflows or overlaps content area
- [ ] Main content area scrolls independently of sidebar
- [ ] No horizontal scrollbar at 1280px+ (unless expected for wide tables)
- [ ] No text truncation cutting off important labels (button text, stat numbers)
- [ ] Long creator names / video titles truncate with ellipsis, not overflow
- [ ] Long filenames in upload area truncate correctly

### 2 — Spacing & Alignment

- [ ] Card grid uses consistent gap (no orphaned single card spanning full row)
- [ ] Buttons within cards have consistent padding
- [ ] Modal padding consistent on all 4 sides
- [ ] Form labels aligned with their inputs
- [ ] Icon + text pairs vertically centered
- [ ] Action buttons in consistent positions across similar cards

### 3 — Modals & Dialogs

- [ ] Clip modal opens without layout shift in background
- [ ] Modal scrollable when content taller than viewport
- [ ] Modal closes on Escape key
- [ ] Modal closes on backdrop click (or has explicit close button)
- [ ] Confirmation dialogs (delete, bulk delete) centered and readable at all breakpoints
- [ ] No modal appears off-screen or partially off-screen
- [ ] Caption editor modal handles long transcripts without layout break

### 4 — Dropdowns & Selects

- [ ] Creator dropdown opens above or below depending on available space (not clipped by viewport)
- [ ] Filter dropdowns don't clip behind sidebar or content area
- [ ] Platform selector badges visible in dropdown options
- [ ] Selected state clearly indicated
- [ ] Dropdown closes on outside click

### 5 — Buttons & Interactivity

- [ ] All buttons have hover state
- [ ] All buttons have focus ring (keyboard navigation)
- [ ] Disabled buttons visually distinct and not clickable
- [ ] Loading states: spinner or skeleton shown while async action in progress
- [ ] Submit buttons disable during form submission (no double-submit)
- [ ] Destructive buttons (delete, reject) visually distinct (red or warning color)
- [ ] Icon-only buttons have tooltip or aria-label

### 6 — Empty States

- [ ] No clips: shows message, not blank white space
- [ ] No creators: shows prompt to create first creator
- [ ] Filter returns no results: shows "no results" state with option to clear filter
- [ ] Unassigned with 0 clips: shows empty state, not broken layout
- [ ] New Job with no prior jobs: shows instructional state

### 7 — Loading States

- [ ] Initial page load: spinner or skeleton cards (not flash of broken layout)
- [ ] Pipeline progress: step name and progress bar visible, not overlapping other content
- [ ] Clip thumbnail: placeholder shown while loading (not broken image icon)
- [ ] Long API calls (>1s): loading indicator shown
- [ ] SSE stream: in-progress state clearly visible, not frozen-looking

### 8 — Text Wrapping

- [ ] Video titles wrap cleanly in cards (max 2 lines, then ellipsis)
- [ ] Creator slugs don't overflow their container
- [ ] Caption text in clip modal wraps correctly
- [ ] Review notes textarea expands correctly
- [ ] Long platform names don't break badge layout

### 9 — Responsive Grid

- [ ] Clip cards reflow to fewer columns at 1024px and 768px
- [ ] Creator cards reflow correctly
- [ ] No cards overlap at any breakpoint
- [ ] Bulk action bar reflows on narrow screens (buttons stack or wrap)
- [ ] Filter chips wrap to multiple lines on narrow screens (no overflow)

### 10 — Dark Mode Consistency

- [ ] All new UI elements use CSS variables (not hardcoded `#ffffff` or `#000000`)
- [ ] Text on dark backgrounds meets minimum contrast (4.5:1 for normal text)
- [ ] Status badges (approved=green, rejected=red, pending=yellow) readable in dark mode
- [ ] Hover states visible in dark mode
- [ ] Modals have consistent dark background (no flash of white modal on dark page)
- [ ] Input focus rings visible in dark mode

### 11 — Accessibility (basic)

- [ ] All interactive elements reachable by Tab key
- [ ] Tab order logical (follows visual flow, left-to-right, top-to-bottom)
- [ ] Focus ring always visible (not hidden by `outline: none`)
- [ ] Form inputs have associated `<label>` or `aria-label`
- [ ] Images have `alt` text (or `alt=""` for decorative)
- [ ] Error messages associated with their input (not just a red border)
- [ ] Color not the sole indicator of status (badge has icon or text, not just color)

### 12 — Production Values

- [ ] No TODO or placeholder text visible in production UI
- [ ] No console.log statements with debug output visible in browser console
- [ ] No broken asset references (404 on CSS, JS, images, fonts)
- [ ] App version or build info visible (if applicable)

---

## Testing Approach

### If server is running (`http://localhost:8000`)

1. Open dashboard in browser
2. Test at each breakpoint using DevTools responsive mode
3. Screenshot or note specific issues
4. Check browser console (F12 → Console) for JS errors and warnings
5. Check Network tab for failed requests

### If server is not running (static audit)

1. Read `dashboard/index.html`
2. Trace CSS classes → check for responsive classes (grid, flex, overflow)
3. Check for media queries
4. Check for `.innerHTML` usage that could cause layout issues with long strings
5. Note any hardcoded dimensions that would break at different viewports

---

## Output Format

```
## frontend-visual-qa Report — [date]

### Breakpoints Tested
[list which were tested live vs static review]

### Issues Found
| ID | Breakpoint | Area | Severity | Description |
|----|-----------|------|----------|-------------|
| VQA-001 | 768px | Cards | Medium | ... |

### Dark Mode Issues
(none / list)

### Accessibility Issues
(none / list)

### Summary
X areas reviewed at Y breakpoints. Z issues found (A critical, B high, C medium, D low).
```

---

## Notes

- This skill reviews visual correctness. For functional correctness (buttons doing the right thing), use `/clipper-qa`.
- CSS variable audit: search `dashboard/index.html` for `#[0-9a-fA-F]{3,6}` to find hardcoded colors that should be variables.
- The dashboard is a single-file SPA (`dashboard/index.html`). All CSS, JS, and HTML are in that file.
- Playwright is available (`npx playwright`) for automated screenshot comparison if needed.
