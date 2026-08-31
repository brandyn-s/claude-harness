# Plan parsing — field schema and failure modes

## What `parse_plan.py` extracts

| Field | Source in plan | Required? | Failure if missing |
|-------|----------------|-----------|--------------------|
| `demo` | `Demo:` line | yes | error: "Demo: line required" |
| `falsifiers[]` | `## Falsifiers` section, list items | yes | error: "## Falsifiers section with list items required" |
| `metric_commands[]` | `### Metric Commands` code block (preferred) or `Verification:` code block (legacy) | yes | error: "### Metric Commands or Verification: code block required" |
| `guard_commands[]` | `### Guard Commands` code block | no — warn only | stderr: "no guard_commands; supergoal only enforces metric_commands" |
| `artifact_probe[]` | `### Artifact Probe` code block | no — warn only | stderr: "Goodhart probe disabled; metric-gaming undetectable" |
| `forbidden_actions[]` | `### Forbidden Actions` list | no — warn only | stderr: "policy axis disabled" |
| `baseline` | regex on `currently <N>` + `expected <M>` | no | null in state file; budget+metric still work |
| `effort` | `Effort:` line | no — defaults to M | M-tier budgets applied |
| `metric_names[]` | regex `[A-Z][A-Z_0-9]{2,}` plus explicit short names (F1, MRR, Acc@N) | no | empty list → prior-arc check is a no-op |

## Why mandatory fields exist

- **`demo`**: without it, the /goal condition has nothing to derive from. We refuse to synthesize a default — synthesizing produces unevaluable conditions, exactly the `/goal` failure mode we're trying to fix.
- **`falsifiers`**: without explicit halt criteria, supergoal turns into a /goal that just runs forever or until budget exhaustion. Falsifiers are how the loop self-aborts on a known-bad state.
- **`metric_commands`**: the entire point of supergoal is tool-backed verification. No metric_commands = no verification, which means we're worse than plain /goal (we add overhead without adding signal).

If any are missing, supergoal exits 20 (EXIT_PARSE_FAILED) with the list of missing pieces and a recommendation to re-run `superplan` with those sections added. Do not patch in defaults.

## Why `guard_commands`, `artifact_probe`, `forbidden_actions` are warn-only

- Guard commands catch regressions: "did we break existing tests / lints while improving the metric?" Protective, not mandatory.
- Artifact probe is the Goodhart guard — observes the artifact, not the metric. Catches "metric-gamed but artifact is empty" (the space-shooter-with-3-pixels failure mode from mpt.solutions).
- Forbidden actions are a policy axis (Devin convention) — patterns the agent must not invoke.

Each warning nudges plan authors to add the section without breaking older plans that didn't.

## SHA-256 attestation

`parse_plan.py` writes the plan's SHA-256 to two locations:

- `~/.claude/supergoal/<slug>/plan.sha256` — inside the state dir, alongside `state.json`
- `<plan>.md.attestation` — sibling of the plan file, for cross-session visibility

The Stop hook re-hashes the plan each turn (mtime-keyed cache: only re-hash if mtime changed) and compares; if the hash changes, the hook returns `{ok: true, reason: "plan-tampered"}` and Step 7's terminal-doc records the tamper.

`state_io.py --resume` also re-hashes the plan before clearing `paused_at`; mismatch refuses auto-resume into a mutated plan (the user must re-run `superplan` to update + re-attest, then re-invoke `supergoal`).

This protects against:
- A teammate (or another Claude session) silently mutating the plan during the loop
- The plan being moved/copied without re-attesting
- Drift between the plan file and the parsed `state.json`

## Written but unused fields

The following fields are written to `state.json` by `parse_plan.py` but are not read by other scripts:
- `sha_path` — the path where the plan SHA-256 is stored (informational only)
- `active_started_at` — duplicate of `started_at` with identical timestamp (use `started_at`)
- `effort` — the parsed effort level (overridable via CLI flags; not consumed after parse)

Consumers should use `turn_budget_total` and `time_budget_seconds` (which are derived from effort) rather than the effort field itself.

## State directory layout

Per-plan directory at `~/.claude/supergoal/<plan-slug>/` (NOT `/tmp` — claude-code#28923 documents 369 corrupt-state backups/day from single-file concurrent writes; per-plan dir + flock + atomic rename prevent the cascade).

```
~/.claude/supergoal/
├── .active                      # one line: absolute path to active state.json
├── <plan-slug>/
│   ├── state.json               # canonical state (read/written by hook + CLI)
│   ├── state.json.lock          # fcntl lock file
│   ├── state.json.corrupt-<ts>  # archived on CorruptStateError (forensic)
│   ├── events.jsonl             # append-only event log
│   └── plan.sha256              # attestation
└── ...
```

The hook reads + writes `state.json` every turn. `events.jsonl` is append-only; never rewritten.

## `state.json` schema

```json
{
  "plan_path": "/abs/path/to/plan.md",
  "plan_slug": "2026-05-24-fix-extractor",
  "plan_sha256": "<hex>",
  "plan_mtime": 1779000000.0,
  "sha_path": "/root/.claude/supergoal/<slug>/plan.sha256",
  "events_path": "/root/.claude/supergoal/<slug>/events.jsonl",

  "demo": "<one-line>",
  "falsifiers": ["<observation+action>", "..."],
  "metric_commands": ["<bash command>", "..."],
  "guard_commands": ["<bash command>", "..."],
  "artifact_probe": ["<bash command>", "..."],
  "forbidden_actions": ["Bash(rm *)", "..."],
  "baseline": {"currently_N": 12.0, "expected_M": 30.0},
  "effort": "M",
  "metric_names": ["HTTP_CALLS"],

  "consecutive_blocks": 0,
  "consecutive_no_progress": 0,
  "max_stuck": 3,
  "scorer_broken_codes": [2, 126, 127, 137],

  "turn_budget_remaining": 20,
  "turn_budget_total": 20,
  "wallclock_used_seconds": 0,
  "time_budget_seconds": 3600,
  "tokens_used_advisory": 0,
  "token_budget_advisory": 800000,

  "last_verified_at": null,
  "started_at": "<ISO timestamp>",
  "active_started_at": "<ISO timestamp>",
  "paused_at": null,

  "force_rerun": false,
  "headless": false,
  "git_commits_enabled": false,

  "lineage": ["/abs/path/to/prior-terminal.md", "..."],
  "prior_arc_count": 0,
  "prior_arc_ledger": "<markdown table>",

  "exit_reason": null,
  "exited_at": null
}
```

`tokens_used_advisory` / `token_budget_advisory` are honest about being advisory: per-turn token usage is not reliably exposed to Claude Code skills (jthack/claude-goal documents this). The authoritative budgets are `turn_budget_remaining` + `wallclock_used_seconds`.

`paused_at` is the pause gate the hook checks first (after the `.active` resolution). Set by `state_io.py --pause`; cleared by `--resume`. On pause, the prior active interval `(now - last_verified_at)` folds into `wallclock_used_seconds`; on resume, `last_verified_at` is reset to resume-time. Paused intervals do not advance the wallclock budget.

`exit_reason` / `exited_at` are written by `write_terminal.py` when the loop exits; subsequent `--pause` calls refuse with "plan already exited."

Keep the file small (no command output, no full transcripts) so flock+read stays fast.
