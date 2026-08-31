# Enterprise Fallback — Full Query Sequence (Phase 1)

For internal/private developers: when public repos return <10 non-fork but `gh`
authenticates against enterprise orgs, run this sequence.

First, discover accessible orgs dynamically:
```
gh api user/orgs --jq '.[].login'
```
This returns all orgs the current `gh` token can access (e.g., example-org,
example-apps-org, and any future orgs). Do NOT hardcode org names — discover them.

Then search across discovered orgs:
1. `gh search prs --author=<username> --owner=<org1> --owner=<org2> ... --limit=25`
   — discover which repos the target contributes to
2. `gh search commits --author=<username> --owner=<org1> --owner=<org2> ... --limit=25`
   — discover commit activity
3. If PRs or commits are found: proceed to Phase 2 using those org repos as the evidence
   source instead of personal repos. Note in Phase 3 preamble: "This profile is based on
   enterprise org activity, not public repos."
4. If no PRs or commits found across enterprise orgs either: fire the insufficient signal gate.
