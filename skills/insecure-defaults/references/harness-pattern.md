# Eight-component harness map — insecure-defaults

Fourth reference implementation of the harness pattern. Same eight-
component structure as `audit-skill`, `mcp-forge-build`,
`variant-analysis`. Domain: classifying fail-open vs fail-secure
defaults in production codepaths.

## Entry test

The verification asymmetry that justifies the harness:

- **Generation** = framework-aware discovery (Rust `defvar!` / Nix
  `mkOption` / Python `os.getenv`), grep over 12 pattern categories,
  per-finding code-path tracing, prod-impact assessment, secure-
  alternative authoring. Hundreds to thousands of LLM tokens per find.
- **Verification** = AST / regex check that the claimed file:line still
  contains the claimed pattern (Tier 1), regex-driven classification of
  the surrounding lines as fail-open vs fail-secure (Tier 1), and —
  when opt-in — a **Tier-2 sandbox executor** that runs the code with
  the env var cleared and observes whether it crashes or starts.

The sandbox-executor oracle is the key lift over prose-only auditing:
the prompt "trace whether the app starts without the env var" becomes
"clear the env var, run the probe command, check the exit code." No
interpretive room — exit 0 = fail-open, non-zero = fail-secure.

## Per-component map

### 1. Proposer

Claude reads the codebase, performs framework-first discovery (per
`SKILL.md` Step 1 "Framework-first discovery"), runs the 12-category
grep library (`references/grep-patterns.md`), traces each candidate
through to its use site, and emits per-finding entries with: file,
line, pattern, classification claim, optional probe command, env var
name.

The proposer is the heavy lift; the oracle gates only what the proposer
claims, not what it should have looked for.

### 2. Oracle / verifier (stratified)

`scripts/verify_defaults.py` runs the verification suite
deterministically:

- **finding_locates** (Tier 1, mechanical) — file exists, line still
  contains the claimed pattern. Catches stale reports against moved or
  fixed code.
- **fail_open_classify** (Tier 1, regex) — read +/- 3 lines around the
  finding; classify the window as fail-open (hits one of `or "x"`,
  `|| 'x'`, `unwrap_or`, `getenv(K, default)`, `mkOption { default = ... }`)
  vs fail-secure (`expect`, `throw`, `raise KeyError`, `panic!`,
  `sys.exit`). Verdict compared against the claim if provided.
- **not_test_fixture** (Tier 1, path exclusion) — paths matching
  `tests?/`, `spec/`, `__tests__/`, `examples?/`, `fixtures?/`,
  `.example`, `.sample`, `.template`, or `.claude/worktrees/` /
  `.git/worktrees/` are dropped. Encodes the "When NOT to Use" list
  from `SKILL.md` mechanically.
- **startup_probe** (Tier 2, sandbox executor) — when the finding
  provides a `probe_cmd` and `env_var`, run the probe with the env var
  cleared and observe the exit code. Exit 0 confirms fail-open; non-
  zero confirms fail-secure. Stderr tail is captured for the audit
  trail.

The Tier-2 sandbox executor is the same kind of authority as
mcp-forge-build's FastMCP-runtime check: there's no room for
interpretation. The interpreter either crashes or it doesn't.

What's *not* in the oracle: exploitability (what the secret is used
for — JWT signing vs CSRF nonce vs encryption-at-rest) and remediation
text. The skill still owns the Secure Alternative line.

### 3. Context engineering

Three reference files feed the proposer:

- `references/grep-patterns.md` — 12 pattern categories with ready-to-
  run greps per language. The proposer copies from here rather than
  reinventing patterns.
- `references/examples.md` — fail-open / fail-secure exemplars
  side-by-side, used for the Verify and Confirm phases.
- The framework-first discovery list inside `SKILL.md` ("Rust:
  `defvar!` macros … Nix: `mkOption` blocks …"). Generic value-pattern
  greps are second-pass.

The findings.json shape is the proposer/oracle contract: one entry per
candidate insecure default with file, line, pattern, claim, env var,
probe.

### 4. Tool surface (minimal)

The skill declares: `Read`, `Grep`, `Glob`, `Bash`, `AskUserQuestion`.
No specialized linters — POSIX + framework-idiom greps + a subprocess
sandbox carry the verification.

### 5. Orchestration / parallelism

Per-finding verification is independent: findings can be checked in
parallel via the findings.json list. The skill already supports
parallel grep dispatch through framework-first discovery; the harness
extends that to verification.

When findings.json has hundreds of entries (a large codebase audit),
the script iterates findings serially; the orchestrator can shard by
finding.id and merge via the NDJSON event log on completion. Per-
finding cost is dominated by the optional Tier-2 probe (subprocess
startup ~50-500ms) — well within budget for parallel dispatch.

### 6. Memory / skill library

`defaults-history.jsonl` accumulates one row per scan.
`scripts/defaults_history.py {append,diff,summary}` surfaces patterns:

- **`append`** — write one summary row (run_id, repo, n_findings,
  n_fail_open, n_fail_secure, git_sha, finding IDs).
- **`diff`** — compare last two scans for the same repo: did fail-open
  count drop after the fix PR? Did a regression introduce a new
  finding ID?
- **`summary`** — most-recurrent finding IDs across all scans (e.g.,
  "`jwt-secret-fallback` appears in 5 of 7 repos — add to the org-wide
  Semgrep rule").

This is Voyager-style accumulation in a constrained domain: per-repo
finding patterns get remembered between audits.

### 7. Failure-detection middleware

- **`finding_locates` as kernel gate** — a finding referencing a moved
  or deleted line fails fast, before fail-open classification wastes
  cycles. Catches stale reports automatically.
- **`not_test_fixture`** — the FP source most commonly cited in
  `SKILL.md`'s "Rationalizations to Reject" gets machine-enforced.
  Findings in test/example paths are flagged, not promoted.
- **`defaults_history.py diff` as a CI gate** — post-fix CI runs the
  scan and diffs against the prior scan. A regression (new finding ID
  introduced) fails the build.

### 8. Observability / audit trail

`verify_defaults.py --ndjson PATH` emits one record per check:

```json
{"run_id": "2026-05-30T...", "check": "finding_locates", "id": "jwt-secret-fallback", "file": "src/auth/jwt.ts", "line": 15, "passed": true}
{"run_id": "2026-05-30T...", "check": "fail_open_classify", "id": "jwt-secret-fallback", "verdict": "fail_open", "passed": true}
{"run_id": "2026-05-30T...", "check": "not_test_fixture", "id": "jwt-secret-fallback", "passed": true}
{"run_id": "2026-05-30T...", "check": "startup_probe", "id": "jwt-secret-fallback", "verdict": "fail_open", "passed": true, "reason": "probe succeeded without JWT_SECRET — fail-open confirmed"}
```

Replayable. Grep-able. The `--json` output is the per-report summary;
the NDJSON is the per-check event log feeding `defaults_history.py`.
