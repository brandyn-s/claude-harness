# Step 11b: Adversarial Verification

For each REMOVE_WORKAROUND or UPDATE_PATTERN finding, run a lightweight
adversarial check before auto-writing:

1. **Search for regressions**:
   `gh issue list --repo anthropics/claude-code --state open --limit 10 --json number,title --search "{bug keyword} regression"`
2. **Search for "still broken"**:
   `gh issue list --repo anthropics/claude-code --state open --limit 10 --json number,title --search "{bug keyword} still"`
3. **Check Exa for community reports**:
   `web_search_exa(query="Claude Code {bug keyword} still broken regression 2026")` —
   community practitioners often report regressions before they're tracked
   in GitHub issues.

If adversarial search finds counter-evidence (open regression, "still
broken" reports):

- Downgrade from REMOVE_WORKAROUND to KNOWN_BUG
- Note the counter-evidence in the finding
- Do NOT auto-remove the workaround

This prevents false positives from CHANGELOG keyword matching. A "fix"
in the CHANGELOG may address a different aspect of the same bug, or may
have regressed in a subsequent release.
