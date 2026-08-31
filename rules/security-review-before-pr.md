---
paths:
  - "**/.github/workflows/**"
  - "**/Dockerfile*"
  - "**/auth*"
  - "**/middleware*"
  - "**/opa*"
  - "**/*.rego"
  - "**/templates/**"
---

# Security Review Before PR

## Reviewing untrusted / external repos (before you even open them)

When reviewing a PR or auditing a repo you did NOT author — anything cloned from
outside our orgs — the repo's own `.claude/` is attacker-controllable: a committed
`.claude/settings.json` can define hooks, and project settings can carry MCP/trust
config. The disclosed pre-trust-consent execution vulns (hooks running BEFORE the
"Do you trust this folder?" prompt) are PATCHED as of our v2.1.177 — fixed across
v2.1.169–172 ("untrusted project settings being able to set OTEL client-cert paths
without trust confirmation"; "background agents reading another directory's project
settings/trust on a pre-warmed worker"). Defense-in-depth regardless:

- Launch untrusted-repo review with **`--safe-mode`** (v2.1.169, env
  `CLAUDE_CODE_SAFE_MODE`) — starts Claude Code with ALL customizations (CLAUDE.md,
  plugins, skills, hooks, MCP servers) disabled, so a malicious `.claude/` in the
  cloned repo cannot execute or inject. Re-enable after inspecting the repo's `.claude/`.
- Or review the diff WITHOUT `cd`-ing into the clone (read it from a trusted cwd) so
  the repo's project settings never load.
- Reference: Anthropic "How we contain Claude" (2026-05-25) — persistent injection
  via product memory / CLAUDE.md / mounted workspaces is the stated next frontier;
  session-startup classifiers are the mitigation direction.

---

Before creating any PR (`gh pr create`), check if the changes include security-sensitive files:

- Scripts that take user input (`scripts/*.sh`, `scripts/*.py` with `sys.argv` or `argparse`)
- CI/CD workflows (`.github/workflows/*.yml`)
- Dockerfiles
- Policy files (Rego, OPA config, Conftest)
- Auth/middleware code (`**/auth*.py`, `**/middleware*.py`, `**/opa*.py`)
- Template files used for code generation (`templates/`)

If ANY security-sensitive files are in the diff, perform these checks BEFORE creating the PR:

## Input Handling (scripts and templates)
- [ ] User-controlled input is validated against a strict allowlist pattern BEFORE any use
- [ ] No shell-to-interpreter string interpolation with user input (use env vars or argparse instead of `python3 -c "...$VAR..."`)
- [ ] No path traversal possible (validate no `/`, `..`, or matching critical directory names)
- [ ] sed/awk patterns use safe delimiters that user input cannot contain

### FAIL/PASS Examples (Input Handling)

**FAIL** — string interpolation with user input:
```python
user_input = sys.argv[1]
os.system(f"python3 -c \"process('{user_input}')\"")  # Shell injection
```

**PASS** — env var or subprocess with argument list:
```python
user_input = sys.argv[1]
subprocess.run(["python3", "process.py", user_input], check=True)  # No shell
```

**FAIL** — path traversal unchecked:
```python
filename = request.args["file"]
return send_file(f"/data/{filename}")  # ../../etc/passwd
```

**PASS** — validated against allowlist:
```python
filename = request.args["file"]
if not re.match(r'^[a-zA-Z0-9_-]+\.csv$', filename):
    abort(400, "Invalid filename")
return send_file(Path("/data") / filename)
```

## CI/CD Workflows
- [ ] New job names are added to org ruleset required status checks if they must block merge (or all checks are steps in an existing required job)
- [ ] All GitHub Actions are SHA-pinned (not tag references)
- [ ] Downloaded binaries have checksum verification
- [ ] Permissions block uses least privilege (no `write-all`)
- [ ] AWS pagination is handled for any `aws` CLI calls that return lists
- [ ] **New gate/check/guard steps come with a known-positive AND known-negative proof in the PR description** — show the gate passing on a known-good artifact and failing (or taking the guarded branch) on a known-bad one, run against the SAME pipeline that will execute it. A gate that has never been seen passing is indistinguishable from one that works; both 2026-06-12 born-broken guards shipped without this: the OPA bundle gate was authored against a different builder's layout (never passed once — production policy froze 18 days), and the ecr-check rerun guard called an IAM action its role didn't have, with the error swallowed (silently rebuilt + collided for weeks). If the gate's failure path swallows errors (`>/dev/null 2>&1`, bare `except`), distinguish "expected negative" from "instrument failure" — instrument failures must fail loud, not take the negative branch.

## Containers
- [ ] Dockerfile has a `USER` directive (non-root default)
- [ ] Base image is SHA-pinned or version-pinned
- [ ] No secrets in build args or ENV statements

## Slack/Webhook Notifications
- [ ] JSON payloads are constructed with `jq`, not string interpolation
- [ ] User-controlled data is escaped before inclusion in payloads

## Policy
- [ ] Dev/local environments match production security settings (OPA auth, TLS, etc.)
- [ ] Policy bypass classifications (batch, proxy, etc.) are explicitly documented and minimal

## CI/CD Security (additional)
- [ ] `actions/checkout` uses `persist-credentials: false` to prevent token leakage to
  later steps. (alex/Gaynor pattern — supply chain attack mitigation)

If any check fails, fix it before creating the PR. Do not create the PR with known security issues and a plan to "fix later."

## Security Triage Classification

When triaging a reported bug or crash, classify it before assigning severity:

| Classification | Definition | Severity |
|---------------|------------|----------|
| **Memory unsafety** | Use-after-free, buffer overflow, data race, undefined behavior | **Security vulnerability** — CVE-worthy |
| **Panic / crash / abort** | Rust panic, Python SystemExit, unhandled exception | **Bug** — not a security vulnerability |
| **Logic error** | Wrong output, incorrect behavior, missing validation | **Bug** — may be security-relevant if at a trust boundary |

**Panics are bugs, not security vulnerabilities.** A Rust panic terminates the process
in a well-defined state — no memory corruption, no undefined behavior. Triage it as a
reliability bug, not a security incident. Don't waste security response cycles on crashes
that aren't exploitable.

(alex/Gaynor — pyca/cryptography explicit security policy, 2026-04-04)

## Environment Variable Handling
- [ ] No fail-open defaults (`env.get('KEY') or 'default'` where default allows insecure operation)
- [ ] Missing required env vars cause startup failure (crash), not silent fallback to weak values
- [ ] Secrets are loaded via `os.environ['KEY']` (KeyError on missing), not `os.environ.get('KEY', 'default')`
- [ ] For deeper configuration audit, invoke `/insecure-defaults` on the changed files

### FAIL/PASS Examples (Environment Variables)

**FAIL** — fail-open default allows insecure operation:
```python
auth_enabled = os.environ.get("AUTH_ENABLED", "false")  # Runs without auth
db_password = os.environ.get("DB_PASSWORD", "changeme")  # Works with weak cred
```

**PASS** — crash on missing, no insecure fallback:
```python
auth_enabled = os.environ["AUTH_ENABLED"]  # KeyError if missing
db_password = os.environ["DB_PASSWORD"]    # KeyError if missing
```

## Known Secrets in Committed Files
- No known hardcoded secrets. The Confluence API token was migrated to Windows user env var (`CONFLUENCE_API_TOKEN`) and is loaded dynamically via `os.environ` in `session-start.py` lines 60-65.
- If gitleaks flags historical commits, add the commit SHA to the repo's `.gitleaks.toml` allowlist rather than suppressing the check.
- **NEW test data / fixtures with secret-shaped values: DEFANG, don't allowlist.** When you author a fixture, sample payload, or test transcript that needs to *look* like it contains a credential (to exercise a detector, parser, or scanner), use an obviously-fake placeholder that does NOT match a real secret regex — `AKIAEXAMPLE_NOT_A_REAL_KEY`, `EXAMPLE_redacted_placeholder_value`, `sk-ant-EXAMPLE`. A real-SHAPED value (even a fake one you invented) trips gitleaks/secrets-scan and BLOCKS the PR; allowlisting a `tests/`/`fixtures/` path to permit it is the wrong fix for NEW data (it widens the allowlist and trains the scanner to ignore a real leak later). For a detector that keys on *structure or surrounding context* (`AWS_SECRET_ACCESS_KEY=`, the credential-handling meaning) rather than the literal token, a defanged `EXAMPLE`-marked value tests identically. **EXCEPTION — a detector with its OWN placeholder filter** (credential scanners like `otel_secrets.scan_text`, gitleaks/trufflehog themselves) DROPS `EXAMPLE`/`PLACEHOLDER`/`xxxx`/`your-key-here` values BY DESIGN — so an `EXAMPLE`-marked fixture tests NOTHING against it: the detector rejects your fixture as a placeholder *before* matching. A detector-RECALL fixture therefore needs a real-SHAPED fake (no `EXAMPLE` marker) that survives the placeholder filter — which then trips push protection. Reconcile BOTH by ASSEMBLING the value from fragments in source — `_a("AKI","<16 more>")`, `_a("xox","b-<rest>")`, `_a("sk-","ant-","<rest>")` — so the runtime string is intact (detector matches) but no contiguous secret-pattern literal sits in the file (nothing for gitleaks/push-protection to catch; keep the fragmented example in rules/docs too, as this bullet does). Path-allowlisting in `.gitleaks.toml` is for unavoidable pre-existing fixtures; defanging is for anything you write now. WHY: 2026-06-17 PR #557 (mcp-servers) — judge-eval fixtures used a real-shaped AWS key + secret; gitleaks blocked the merge twice, and because the introducing commit's diff carried the token, the fix required squashing to a clean single commit (a later commit removing it does not clear a range scan). WHY (EXCEPTION, 2026-07-04 recall-census): `EXAMPLE`-marked known-positive fixtures scored 0/5 on `scan_text` — correctly dropped as placeholders, caught by the instrument-validation probe *before* the real run; real-shaped fakes matched 5/5 but a defanged Slack-token shape then tripped GitHub push protection; fragment-assembly satisfied both (5/5 detector match + clean push). Defang at authoring time avoids the whole cycle. (`github-secret-scanning.md` covers the historical/triage side; this is the author-time rule.)

## A tool that PROCESSES secrets must assert its own no-value contract IN CODE

Defanging (above) governs fixtures you author. This governs a scanner/auditor you write
that reads REAL credential-bearing data — a pool scan, a leak census, a redaction check.

**A docstring promising "counts and family labels only" is not a control.** Put the
assertion in the code path that EMITS, because that is where the contract is kept or
broken — and a truncation fallback is the classic breaker:

```python
fam = f[0] if isinstance(f, (tuple, list)) else str(f)   # field 0, never str(f)[:N]
assert not _looks_secret(fam)                            # cheap entropy/prefix check
```

- **Never `str(match)[:N]` as a fallback label.** Detector APIs commonly return
  `(family, value)` tuples, so truncating the TUPLE prints the value's first N chars —
  and N is routinely enough for a key ID or the head of a URL password.
- **Assert, don't intend.** If output must be value-free, check it before printing:
  reject any token matching the scanner's own patterns or exceeding an entropy bound.
- **Scrub on discovery.** If values reached a file, delete it immediately and grep for
  other copies before continuing.

WHY: 2026-07-30 — a credential scan over 130MB of untracked session-transcript pools was
written with the docstring *"COUNTS AND FAMILY LABELS ONLY -- no value, no phrase, no
session id is printed"*; its `str(f)[:40]` fallback then printed two truncated AWS key
IDs, an ELB auth-cookie prefix, and the head of a credentials-in-URL. The same
stated-contract-vs-code defect the session had spent hours auditing elsewhere, committed
inside the tool built to detect it. The finding was real and serious (the pools held a
known-live unremediated admin key), which is what made the leak easy to miss — the output
looked like the finding.

### Redact by OUTPUT SHAPE, not by key name — a name-keyed redactor misses one nesting level and prints the value

The section above governs a truncation fallback. This is its structural sibling and it is
easier to write by accident: a redactor that decides what to hide by inspecting KEY NAMES
at one level of a document, then prints everything else verbatim. Any credential one level
deeper is emitted in full, and the code reads as careful — it has a redaction branch.

```python
# WRONG — only top-level keys are examined; nested dicts print raw
for k, v in doc.items():
    print(f"{k} = {'<redacted>' if 'TOKEN' in k.upper() else v!r}")

# RIGHT — gate the OUTPUT, whatever produced it
def emit(k, v):
    s = str(v)
    assert not _looks_secret(s), f"refusing to print credential-shaped value for {k}"
    print(f"{k} = {s}")
```

- **The assertion belongs on the string about to be printed**, not on the key that owns it.
  A key-name allowlist cannot see through a nested dict, a JSON string, a list element, or
  a key you did not anticipate.
- **Know your credential's shape and assert its absence.** If the secret is a 48-char
  token, refuse to print any 40+ char high-entropy run. That check is one function and it
  fires regardless of where in the structure the value lives.
- **A `<<'PY'` heredoc that dumps a config for inspection is exactly this code path.** Ad-hoc
  "just let me see the keys" probes are where it happens, because they are not reviewed.

WHY: 2026-08-29 — a probe printing the key names of `/Library/Managed Preferences/
com.anthropic.claudecode.plist` redacted on `"Bearer" in v or "HEADERS" in k`, but
`OTEL_EXPORTER_OTLP_HEADERS` sits inside the plist's nested `env` dict, so the loop hit
`env` (a dict, not matching either test) and printed it whole — leaking a live-in-Secrets-
Manager bearer into the transcript on a task where every prior read had been
fingerprint-only. Mitigating facts do not excuse it but do bound it: the value was the
already-evicted February token (measured 401), it is write-only telemetry ingest, and the
same file is world-readable without sudo on ~885 managed Macs. The tell that this class is
live: the *same session* also mis-parsed that field two other ways, and a 48-char length
assertion would have caught all three.
