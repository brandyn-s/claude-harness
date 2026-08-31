# Step 3b: Installed-Version Regression Sweep

After CHANGELOG parse, immediately check for open regressions against the
**currently installed version** (captured in Step 1). This catches bugs that
affect us *right now* — not bugs we might hit in the future.

```bash
# Replace {installed} with the exact version from `claude --version`
gh issue list --repo anthropics/claude-code --state open --limit 20 \
  --json number,title,labels,updatedAt \
  --search "{installed} regression"

gh issue list --repo anthropics/claude-code --state open --limit 20 \
  --json number,title,labels,updatedAt \
  --search "{installed} broken"
```

Any match is a HIGH-priority finding. Tag these `[INSTALLED-VERSION-REGRESSION]`
in the report. Example: if `claude --version` returns `2.1.113`, and #50252
("v2.1.113 native binary regression") is open, that's a Phase A finding
regardless of the rest of the audit.

**Rationale (2026-04-17):** The 2026-04-17 run caught #50252 only because
Phase B's general bug search happened to surface it. Making this a mandatory
Phase A step ensures it's always caught.
