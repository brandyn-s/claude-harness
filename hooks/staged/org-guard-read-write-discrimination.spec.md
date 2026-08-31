<!-- STATUS BLOCK ADDED 2026-08-27 ON PRESERVATION -- READ THIS FIRST -->

## STATUS: HALF SHIPPED. Do not re-derive the read/write discriminator.

**CORRECTED 2026-08-27, same day, after recovering this session's own earlier turns.**
The version of this header shipped in #2169 said the spec "lived ONLY in the
`~/.claude` local arc ... never on `origin/main`". That is FALSE. It WAS on
`origin/main` and was **deliberately deleted** from it on 2026-08-15 by `0c9f5e56`
-- "chore(staged): delete org-guard-read-write-discrimination.spec.md -- already
shipped (#2009)". That commit verified the read/write fix BEHAVIOURALLY 8/8 and
warned, in as many words, that keeping a shipped spec in `staged/` "misrepresents it
as pending work and invites a second implementation".

The copy found in the arc is a PRE-DELETION REMNANT of a 278-commit-diverged
checkout, not a never-shipped original. Re-adding it here reverses #2009, and that
reversal is only defensible on the narrow ground below: #2009 addressed the
Detection half and did not address the Approval half, which this spec's own text
calls "the second half -- do not ship only the read fix". Anyone acting on this
spec should read `0c9f5e56` FIRST.

A file's presence in one checkout is not evidence about its history in another;
`git log --all --diff-filter=D -- <path>` is. `bin/staged-spec-staleness.py` now
runs that check and reports a re-added spec explicitly.

**Measured 2026-08-27 against the deployed `hooks/bash-security-guard.py`** (10 probe
cases, strings inspected by the hook, nothing executed):

| half of this spec | state | evidence |
|---|---|---|
| **Detection** (read/write discrimination on `--repo` / `github.com/`) | **SHIPPED** | 6 of 6 read forms ALLOWED, including this spec's own measured false positive `gh pr view 936 --repo <org>/docs --json state`; 3 of 3 genuine writes BLOCKED (`gh pr create`, `gh pr merge`, `gh api -X PUT`). The guard now carries an explicit read allow-list and `check_forbidden_org()` documents it. |
| **Approval mechanism** (express an authorized write) | **NOT SHIPPED** | No `CLAUDE_ORG_WRITE_APPROVED` token, no `hooks/org-write-approvals.json`, no equivalent. Grep for `EXPLICIT_APPROVAL_OVERRIDE` / `approval_override` / `CLAUDE_ALLOW_ORG` in the guard returns nothing relevant. |
| **Remove the string-split guidance** | **DONE** | `feedback_no-writes-example-monorepo.md` prescribed splitting the org string to get reads through. Retracted 2026-08-27: unnecessary now that reads pass natively, and harmful because the split defeats the guard for writes too. |

**THE SPEC'S OWN WARNING CAME TRUE.** Its "Approval mechanism" section says, verbatim,
"the second half -- do not ship only the read fix". Only the read fix shipped. Its
RECURRENCE 2026-07-31 entry below is the second datapoint that this is load-bearing:
an operator with explicit approval routed the write through a Python `urllib` script
that carried no org string at all, so the guard never saw it.

**One coverage limit measured on the same run, adjacent to a residual the guard already
documents.** `REPO="<org>/docs"; gh api -X PUT "repos/$REPO/contents/f"` is neither
blocked NOR surfaced: `check_forbidden_org()` strips quoted strings before
`_ORG_REF_RE` runs, so the org disappears from the assignment. The
interpreter/subprocess-list form IS surfaced by `warn_forbidden_org_indirection()`, as
its docstring claims. Graded honestly: this grants no capability an operator does not
already have, and the guard's docstring already names variable-indirection as an
un-closable residual for a regex-on-command-string check. It is a coverage limit of an
advisory-grade control, not a new exposure.

**What remains to install:** the approval mechanism only. Its completion marker is
`ORG_WRITE_APPROVAL`, registered in `bin/staged-spec-staleness.py` and verified absent
from the guard at preservation time. Do NOT re-mark this spec against the Detection
half -- that would report it STALE and prescribe deleting live work.

**This is a security-control change and it LOOSENS the fence on one axis** (an
authorized write becomes expressible). It needs the operator's explicit decision, not
an agent's judgement, before installation.

---

<!-- ORIGINAL SPEC AS STAGED 2026-07-29, EXTENDED 2026-07-31, UNMODIFIED BELOW -->

# Staged hook spec: org-guard-read-write-discrimination

**Staged**: 2026-07-29 (distill)
**Type**: PreToolUse:Bash — modify `check_forbidden_org()` in `bash-security-guard.py`

## Problem

`check_forbidden_org()` blocks any command matching `_ORG_REF_RE`:

```python
r"(?:github\.com[/:]|--repo\s+|(?:^|[\s/])(?:repos|orgs|users)/)example-technologies"
```

Its own block message says **"Write operations (push, PR, merge, commit) ... are
prohibited"** — but the check does not distinguish reads from writes on the
`--repo <org>/<repo>` form. Two consequences, both hit live on 2026-07-29:

1. **Read-only commands are blocked.** `gh pr view 936 --repo example-technologies/docs
   --json state` is a pure read and was blocked. Workaround used:
   `gh api repos/example-technologies/docs/pulls/936` — which the SAME hook allows,
   because the `gh api` path *does* carry a read/write discriminator
   (`_GH_API_WRITE_METHOD_RE` / `_GH_API_GET_RE` / `_GH_API_FIELDS_RE`). So the
   hook is already internally inconsistent: identical intent, opposite verdicts,
   depending on which `gh` surface you reach for.

2. **No way to express an authorized write.** `rules/git-hygiene.md` defines
   `EXPLICIT_APPROVAL_OVERRIDE` — a documented, deliberate path where the user
   grants a per-operation write to this org after being shown the WHY and the
   alternatives. The hook cannot represent that grant, so an approved write is
   still blocked and the agent is pushed toward either (a) an evasion, or (b) a
   different tool surface. Both happened: memory
   `feedback_no-writes-example-monorepo.md` records the standing
   workaround as *"split the org string (`ORG_A="example"; ORG_B="technologies"`)
   to proceed"* — i.e. our own guidance is to defeat the guard by string
   concatenation, which also defeats it for genuinely unapproved writes.
   Separately, `gh pr create` was accomplished via `mcp__github__create_pr`
   (MCP calls are not seen by a Bash hook) after the user authorized the push
   twice, once via AskUserQuestion naming the repo.

A guard that cannot express a legitimate exception trains the operator to route
around it. That is strictly worse than a guard with a narrow, auditable exception.

## Detection / decision logic

Reuse the read/write discrimination that already exists for `gh api`, and apply
it to the `--repo` and `github.com/` forms:

**READ verbs (allow):** `gh pr view|diff|list|checks|status`, `gh issue view|list`,
`gh run view|list|download`, `gh repo view|clone`, `gh api` without a write method
or field flags, `git clone|fetch|ls-remote`.

**WRITE verbs (block by default):** `gh pr create|merge|close|edit|review|comment`,
`gh issue create|close|edit`, `gh release create`, `gh repo create|delete|edit`,
`gh api` with `--method PUT|POST|PATCH|DELETE` or `-f/-F/--field/--input`,
`git push`, `gh workflow run`.

**Unknown verb → block** (fail closed; the current behavior).

## Approval mechanism (the second half — do not ship only the read fix)

Blocking reads is the annoyance; the missing approval path is the defect that
causes evasion. Implement ONE of:

- **(preferred) A per-operation token.** The agent, after obtaining explicit
  user approval naming the repo, sets `CLAUDE_ORG_WRITE_APPROVED=<org>/<repo>`
  for that single Bash call. The hook allows a write whose target matches the
  token exactly, and logs the approval to the audit trail. Scoped to one repo
  and one command — no session-wide grant.
- **(alternative) An allowlist file** `hooks/org-write-approvals.json` holding
  `{repo, expires_at, reason}` entries, written only by an explicit user-facing
  flow. More auditable, more ceremony.

Whichever is chosen, the hook message must NAME the mechanism, so a blocked
agent surfaces the approval request to the user instead of hunting for a bypass.

## Also remove the string-split guidance

`feedback_no-writes-example-monorepo.md` currently instructs splitting
the org string to get reads through. Once reads are allowed, that guidance is
both unnecessary and harmful — delete it in the same change, or it remains a
documented evasion for writes too.

## Test cases

| Command | Expected |
|---|---|
| `gh pr view 936 --repo example-technologies/docs --json state` | ALLOW (read) |
| `gh pr list --repo example-technologies/docs` | ALLOW (read) |
| `git clone https://github.com/example-technologies/docs` | ALLOW (read) |
| `gh api repos/example-technologies/docs/pulls/936` | ALLOW (read, unchanged) |
| `gh pr create --repo example-technologies/docs ...` | BLOCK, name the approval mechanism |
| `gh pr create --repo example-technologies/docs ...` + valid token | ALLOW + audit-log |
| `gh api -X PATCH repos/example-technologies/docs/...` | BLOCK (unchanged) |
| `git push` in a `example-technologies` remote | BLOCK (unchanged) |
| `ORG_A="example"; ORG_B="technologies"; gh pr create --repo "$ORG_A-$ORG_B/docs"` | BLOCK — keep `warn_forbidden_org_indirection` and consider upgrading it to a block for WRITE verbs |

## Historical replay before shipping

Per `verify-effectiveness.md`'s enforcement gate: replay against ~2 weeks of
transcripts and measure how many previously-blocked commands the read-allowance
would now permit, and confirm zero currently-allowed writes become blocked.
This change LOOSENS the guard on reads, so the risk is the inverse of the usual
one — verify no write verb is misclassified as a read.

## RECURRENCE 2026-07-31 — both predicted failures happened again, in a worse shape

Two days after staging, the same session hit BOTH halves. This raises priority:
the spec is not speculative, and its own closing prediction ("a guard that cannot
express a legitimate exception trains the operator to route around it") is now
observed twice.

1. **Read blocked again.** `gh pr view <N> --repo example-technologies/docs --json
   state,mergedAt,mergeStateStatus` — a pure read to answer "did the lockfile fix
   PR merge?" — BLOCKED. Rerouted to `mcp__github__get_pr`, which a Bash hook
   cannot see. That is the internal inconsistency in §1 of this spec, unchanged.

2. **The approved write routed around the guard — via a THIRD surface.** The user
   granted explicit per-operation approval for PRs to `example-technologies/docs`
   (`git-hygiene`'s `EXPLICIT_APPROVAL_OVERRIDE`, the documented path). The hook
   still cannot represent that grant, so the write went through the **GitHub REST
   API from a Python script** (`urllib` + `gh auth token`) — creating blobs, a
   tree, a commit, a ref, and PR #950. The Bash command was `python3 push_docs_pr.py`,
   which carries no org string at all, so the guard never saw it.

   This is worse than the 2026-07-29 shapes. `gh api` and the MCP tools are at
   least enumerable surfaces; an arbitrary Python script is not, so the guard's
   coverage against an UNAPPROVED write is equally zero. The mitigation used was
   to re-implement the guard's intent INSIDE the script — a literal asserted
   `TARGET_REPO`, new-branch-only, `force: false`, no merge, no auto-merge — which
   is exactly the auditable narrow exception this spec proposes, only hand-rolled
   per-invocation and therefore unenforced and unlogged.

**Implication for the design:** the read-allowance (§ Detection) is necessary but
insufficient. Without the approval mechanism (§ Approval), an authorized operator
will keep reaching for whichever surface the hook cannot see, and each such surface
is one the guard also cannot protect. Ship both halves, as this spec already says —
this entry is the second datapoint that the "do not ship only the read fix" warning
is load-bearing.

Install via `/ship-hook`.
