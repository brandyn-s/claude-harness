# Direct Mode

If invoked with an argument like `/pr-fix example-org/mcp-servers#201`:

1. Parse `org/repo` and `number` from the argument
2. Skip Phase 1 (discovery)
3. Perform the real-time hydration from `discovery.md`, including
   `headRefOid`, `reviewRequests`, and GraphQL `mergeQueueEntry`. Direct mode
   skips enumeration, not safety classification.
4. Go to Phase 2 (diagnose) for that specific PR
5. Continue through the matching Phase 3 path, including the dedicated repair
   worktree for any code change

Also accepts: `/pr-fix mcp-servers#201` (infer org from repo map) or `/pr-fix #285` (infer repo from current directory).

### Axis fast-path

`/pr-fix --axis <name>` runs only the named classifier path from Phase 1.
Supported names are `failing`, `conflict`, `ready`, `queued`, `review`, and
`cosmetic`. Every path still hydrates current PR and queue state before acting.
Example: `/pr-fix --axis failing` lists only authored PRs with current required
failures, then continues through Phase 2/3 on the user's selection.

---
