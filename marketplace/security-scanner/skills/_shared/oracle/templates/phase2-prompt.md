<!--
Phase 2 agent prompt template — root-cause fix for cause 5 (false
positives at Phase 2 discovery time).

The May 2026 Phase 2 audit found ~5 of 49 behavior-fix findings were
hallucinated (LLM asserted bugs that weren't real). The
ROOT FIX is structural: every finding the agent emits must come
with a Reproducer that THE AGENT ITSELF has run and observed firing
BEFORE emitting the finding. Findings without a verified Reproducer
are rejected by the orchestrator.

Use this template when dispatching Phase 2 agents. Substitute
`<SKILL>` with the target skill name.
-->

# Phase 2 audit task — `<SKILL>`

You are running Phase 2 of `/audit-skill` against `skills/<SKILL>/`.
READ-ONLY for the target. You may create temp files for verification
under `/tmp` but MUST NOT modify the target skill.

## Mandatory inputs

Read in this order:

1. `skills/audit-skill/SKILL.md` — the audit procedure.
2. `skills/_shared/oracle/SPEC.md` — verdict semantics + tier
   classification per oracle layer.
3. `skills/audit-skill/audit-context.md` — repo-wide ground truth
   (env vars that ARE set, real MCP tool names, paths that resolve).
4. **`AUDIT-TRACKERS/campaign-context.md`** — campaign-wide context
   you MUST load. Names known-external file-system paths (sibling
   repos + local user-data caches) so you do NOT treat them as
   phantom; documents M2-scope (mcp tools only, not built-ins);
   describes the `triage_status` schema; flags multi-mode skills.
5. **`skills/audit-skill/known-external-paths.yaml`** — the
   canonical external-path registry. ANY cited path matching one
   of its `pattern:` entries is a valid external dependency, not
   a phantom citation. Do NOT emit a phantom-path finding (D3a /
   H1 / G1) for these.
6. `skills/<SKILL>/audit-suppress.yaml` if present.
7. `skills/<SKILL>/SKILL.md`, every `references/*.md`, every
   `scripts/*.py`.

## Phase 2 procedure

For each candidate finding you would report:

1. **Construct the Reproducer first, narrative second.** The
   Reproducer is a deterministic predicate (grep / bash / python /
   file_exists / file_missing) that returns True iff the bug is
   present. The narrative description comes AFTER you've constructed
   the predicate — not before.

2. **Run the Reproducer against the live tree.** Use the Bash tool.
   Confirm it returns True (the bug fires). If it returns False,
   STOP — your finding is either stale or hallucinated; do NOT
   emit it.

3. **Record the actual command output as evidence.** The Reproducer
   field in your YAML output must include the literal command +
   the observed exit code / matched line. This is what Layer A
   reverifies later.

4. **If you cannot construct a deterministic Reproducer**, mark the
   finding `type: manual` AND label `[unverified]`. The
   orchestrator will route it to human review, not to a fix-batch.
   You may not emit `[behavior-fix]` or `[doc-fix]` labels on
   findings you have not verified.

## Output format (REQUIRED)

Emit YAML to stdout. The orchestrator parses this directly. Any
other format gets rejected at the boundary.

```yaml
findings:
  - skill: <SKILL>
    code: <H1|H4|D3a|...|A1|A3|B1|...|D1|D2|D4|F2|F3|G1>
    severity: drift | info | error
    label: behavior-fix | doc-fix | unverified
    description: <one-line summary of what is wrong>
    source: <path>:<line>      # optional but recommended
    reproducer:
      type: grep | grep_absent | bash | python | file_exists | file_missing | manual
      command: |
        <the literal bash/python command you ran>
      # OR:
      path: <relative path for file_exists/file_missing>
      expected_exit: 0          # for bash: the code that means "bug is present"
      description: <reproducer-level note, optional>
    extra:
      verified_at: <ISO 8601 timestamp when you ran the reproducer>
      observed_evidence: <verbatim line(s) the Reproducer surfaced>
```

## Categories to cover (Phase 2 only — Phase 1 is mechanical)

**A. External contract verification**

- A1 — literal commands in fenced bash blocks run as documented
  (cd to the deployed path if needed; report any non-zero exit
  or traceback). Reproducer: `bash -c '<command>'` with
  expected_exit=0.
- A3 — prose invariant claims ("X is idempotent", "X refuses
  when Y"). Construct a minimal scenario that would expose a
  violation; run it; confirm the invariant holds OR fails.

**B. Error paths**

For each CLI mentioned, invoke with no args, missing file,
malformed input. Report any raw traceback or silent success
on bad input. Reproducer: bash on the invocation + check stderr.

**D. Cross-component contracts**

- D1 — writer/reader format alignment (a script produces shape
  S; another script's parser expects shape S'). Reproducer:
  diff between writer output and reader's expected.
- D2 — schema vs consumer alignment (manifest declares field X;
  consumer reads field Y). Reproducer: grep for the field in
  the consumer.
- D4 — references describe current code. Reproducer: file_missing
  or grep_absent against the cited file/section.

**F. Real-data integration / G. Deployment context**

- F3 — variant outputs documented but missing.
- G1 — deployed-path resolution (verify the literal documented
  path resolves at deployment time).

## Critical scope notes (read before emitting findings)

These scope rules eliminate the false-positive classes the May 2026
campaign produced. Violating them produces wrong fixes downstream
even when the local file checks out:

- **External-path citations are NOT phantom.** Before emitting any
  H1 / D3a / D4 / G1 finding against a cited path, check the path
  against `skills/audit-skill/known-external-paths.yaml`. If the
  path matches a registered pattern (e.g.,
  `~/Documents/knowledge-base/`, `~/Documents/obsidian-infra/`,
  `~/Documents/api-docs/`), the file lives in a sibling repo or
  local user-data cache — DO NOT emit a phantom-finding for it. If
  you believe the pattern is genuinely missing FROM the operator's
  expected install, file a different finding code with explicit
  rationale (e.g., "sibling repo not cloned at expected location"),
  not a phantom-citation finding.

- **M2 scope is `mcp__*__*` only.** The M2 check (dead allowed-tool
  declaration) applies ONLY to MCP tools matching the
  `mcp__<server>__<tool>` shape. Built-in tools — `AskUserQuestion`,
  `Bash`, `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Skill`, `Task`,
  `WebFetch` — may appear in `allowed-tools` frontmatter without a
  greppable invocation in the body (the model dispatches them via
  natural-language steps at runtime). Emitting M2 against a built-in
  tool is a false positive; do not.

- **Multi-mode skills need mode-scoped grading.** If the target
  skill supports multiple operating modes (discovery vs rubric,
  Phase 1 vs Phase 2, etc.), identify the mode the finding applies
  to and grade against THAT mode's success criterion. Do not apply
  a single-mode rubric across all modes. See
  `rules/red-team-rubric-discipline.md` for the explicit framework.

## Rejection guarantee — and the label contract

Findings that violate any of the following are rejected by the
orchestrator (you don't have to enforce — `oracle/validate.py` +
`audit-skill-oracle.py contract-check --strict` do — but if you
emit them, the orchestrator will tell the operator about the
rejection, and your work is wasted):

**The pairing contract (enforced by `contract-check`):**

| reproducer.type | required label |
|---|---|
| `manual` | `unverified` (always) |
| anything else (grep / bash / python / file_exists / file_missing) | `behavior-fix` OR `doc-fix` (NEVER `unverified`) |

Violations the contract-check CLI catches:

- `MANUAL_NOT_UNVERIFIED`: type=manual paired with doc-fix or
  behavior-fix. The oracle can't verify; route to human review.
- `AUTO_BUT_UNVERIFIED`: auto-checkable reproducer paired with
  unverified. The reproducer IS the verification; relabel.

Other rejections:

- Missing `extra.verified_at`
- Missing `extra.observed_evidence`
- Reproducer command that doesn't actually fire when run

**If you cannot produce an auto-checkable reproducer**, that is OK —
emit `type: manual` AND `label: unverified` together. The orchestrator
routes those to human review. Lying about verification (emitting
type=manual with label=doc-fix as a shortcut) is the contract
violation we caught and reverse-fixed in the May 2026 campaign.

**Shell-divergence findings must name their shell.** The oracle runs
`bash`/`grep` reproducers under bash, but the production Bash tool is
zsh — a probe for zsh-specific behavior (non-word-splitting, glob
NOMATCH, `${VAR:+...}`) can never fire under bash and will false-STALE.
Wrap such probes explicitly: `command: zsh -c '...'` (see
skills/audit-skill/references/new-check-checklist.md §10; 2026-06-12
campaign rescued 5 false-STALEs this way).

## Budget

≤300 findings per skill (most skills produce 0-5). Stop when
you've covered the categories above with rigor — Phase 2 is
quality, not quantity.

## Reporting

After emitting YAML to stdout, also emit a short prose summary
("3 behavior-fix, 1 doc-fix, 2 unverified") so the orchestrator
can log the counts. The YAML is the source of truth; the prose
is informational only.
