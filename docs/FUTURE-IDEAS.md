# Future ideas / parking lot

Things considered but deferred. Save for later, don't act now.

---

## TermuxHub integration (parked 2026-05-15)

`kadster007/TermuxHub` (fork of `maazm7d/TermuxHub`, 244★) is a Kotlin/Android app that indexes Termux tools from a JSON metadata file. Its data shape:

```json
{
  "tools": [
    {
      "id": "0001",
      "name": "seeker",
      "description": "...",
      "category": "Social Engineering",
      "install": "git clone ...",
      "repo": "https://github.com/...",
      "requireRoot": false,
      "publishedAt": "11-12-2025"
    }
  ]
}
```

Sibling files: `metadata/stars.json` (star counts), `metadata/readme/<id>.md` (per-tool docs).

**Relevance.** Same conceptual shape as our `tools/*.json` registry, but:
- TermuxHub's per-tool metadata is shallow (install + repo). Ours has flag types, presets, playbooks, target profile schema.
- TermuxHub's execution model is "install tool locally in Termux, run there" — the **opposite** of ShadowOps' "tools live on kadx, traffic exits through phone."

**Possible integrations (future):**
1. **As discovery surface** — derive a `metadata.json` (TermuxHub-format) from our richer `tools/*.json`, point a TermuxHub instance at our repo, get a native Android tool browser for free. Doesn't replace the pivot workflow.
2. **Fork TermuxHub into a native ShadowOps client** — replace "install in Termux" actions with "execute via SSH to kadx through pivot." Real native Android UI. Significant Kotlin/Android work.
3. **Borrow the UI patterns** but don't fork — build a smaller HTML/JS UI that lives on kadx (current direction).

We're going with option 3-ish: web UI on kadx. Revisit TermuxHub if/when we want a native Android client and the maintenance cost of option 2 becomes attractive.
