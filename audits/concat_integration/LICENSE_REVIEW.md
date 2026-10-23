# Concat License Review — AGPL-3.0

**Reviewed:** 2026-10-23  
**License:** GNU Affero General Public License v3.0  
**Use case:** Internal private tool, Concat called as external subprocess

---

## Summary

**Risk for Content Engine: LOW.**

Content Engine is a private internal tool. Concat is used as a separate process (subprocess via stdio MCP), not as a library linked into the Python codebase.

---

## When AGPL-3.0 obligations activate

AGPL-3.0 extends GPL-3.0 with a "network use is distribution" clause:

| Scenario | Obligation |
|----------|-----------|
| Modify Concat source and use internally | Must make modified source available to users of the service |
| Distribute Concat to third parties | Must include AGPL source or offer to provide it |
| Use unmodified Concat as an external process | **No obligation** (same as using curl, ffmpeg, or any GPL tool via subprocess) |
| Use Concat in a public-facing SaaS | Must offer source of any modified Concat to users |

---

## Content Engine situation

1. **Concat is not modified** — we use the official v0.2.8 binary unchanged
2. **Concat is not linked into Python** — it is a separate executable called via subprocess
3. **Content Engine is not distributed** — it is a private internal tool
4. **Content Engine is not a public service** — no external users

**Conclusion:** No AGPL obligations apply.

---

## Future caution

If Content Engine ever becomes a public service or is distributed to clients:
- Concat must not be bundled without its AGPL notice and source link
- Any modifications to Concat source would require publishing those modifications

---

## Attribution requirement

Even without redistribution obligations, the AGPL requires preserving copyright notices.  
If Concat is bundled with Content Engine for distribution, include:

```
Concat v0.2.8 — Copyright (C) jub0t and contributors
License: GNU Affero General Public License v3.0
Source: https://github.com/jub0t/Concat
```

For internal use only, no attribution requirement.

---

## Recommendation

Proceed with integration. Document that Concat is an external dependency, not a redistributed component. If Content Engine scope changes (public SaaS, client distribution), re-review this assessment.
