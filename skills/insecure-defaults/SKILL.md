---
name: insecure-defaults
description: "Detect fail-open insecure defaults — hardcoded secrets, weak auth, permissive security."
when_to_use: "Detects fail-open insecure defaults (hardcoded secrets, weak auth, permissive security) that allow apps to run insecurely in production. Use when auditing security, reviewing config management, or analyzing environment variable handling. Do NOT use for general code review (use /differential-review), dependency scanning (use /semgrep), or runtime security monitoring."
allowed-tools: Read Grep Glob Bash AskUserQuestion
effort: high
argument-hint: "[file-path or directory to scan]"
metadata:
  author: example-security-engineering
  version: "1.0"
---

# Insecure Defaults Detection

Finds **fail-open** vulnerabilities where apps run insecurely with missing configuration. Distinguishes exploitable defaults from fail-secure patterns that crash safely.

- **Fail-open (CRITICAL):** `SECRET = env.get('KEY') or 'default'` → App runs with weak secret
- **Fail-secure (SAFE):** `SECRET = env['KEY']` → App crashes if missing


> **Runtime policy:** Resolve the effective model and preserve refusal/fallback provenance per `../_shared/model-runtime-policy.md`.

## When to Use

- **Security audits** of production applications (auth, crypto, API security)
- **Configuration review** of deployment files, IaC templates, Docker configs
- **Code review** of environment variable handling and secrets management
- **Pre-deployment checks** for hardcoded credentials or weak defaults

## When NOT to Use

Do not use this skill for:
- **Test fixtures** explicitly scoped to test environments (files in `test/`, `spec/`, `__tests__/`)
- **Example/template files** (`.example`, `.template`, `.sample` suffixes)
- **Development-only tools** (local Docker Compose for dev, debug scripts)
- **Documentation examples** in README.md or docs/ directories
- **Build-time configuration** that gets replaced during deployment
- **Crash-on-missing behavior** where app won't start without proper config (fail-secure)
- **Git worktree copies** (`.claude/worktrees/`, `.git/worktrees/`) — disposable copies, not production code. Grep results from worktrees produce false positives against already-fixed code

When in doubt: trace the code path to determine if the app runs with the default or crashes.

## Rationalizations to Reject

- **"It's just a development default"** → If it reaches production code, it's a finding
- **"The production config overrides it"** → Verify prod config exists; code-level vulnerability remains if not
- **"This would never run without proper config"** → Prove it with code trace; many apps fail silently
- **"It's behind authentication"** → Defense in depth; compromised session still exploits weak defaults
- **"We'll fix it before release"** → Document now; "later" rarely comes

## Workflow

Follow this workflow for every potential finding:

### 1. SEARCH: Perform Project Discovery and Find Insecure Defaults

Determine language, framework, and project conventions. Use this information to further discover things like secret storage locations, secret usage patterns, credentialed third-party integrations, cryptography, and any other relevant configuration. Further use information to analyze insecure default configurations.

**Example**
Search for patterns in `**/config/`, `**/auth/`, `**/database/`, and env files:
- **Fallback secrets:** `getenv.*\) or ['"]`, `process\.env\.[A-Z_]+ \|\| ['"]`, `ENV\.fetch.*default:`
- **Hardcoded credentials:** `password.*=.*['"][^'"]{8,}['"]`, `api[_-]?key.*=.*['"][^'"]+['"]`
- **Weak defaults:** `DEBUG.*=.*true`, `AUTH.*=.*false`, `CORS.*=.*\*`
- **Crypto algorithms:** `MD5|SHA1|DES|RC4|ECB` in security contexts

> **Full pattern library**: 12 categories with ready-to-run greps per language
> (fallback secrets, hardcoded creds, fail-open flags, weak crypto, permissive
> access, TLS-disabled, SQLi/cmdi/deserialization/path-traversal/open-redirect,
> secrets-in-logs) live in `references/grep-patterns.md`. Copy-paste from there
> instead of re-inventing patterns per project.

Tailor search approach based on discovery results.

**Framework-first discovery (before pattern greps):**

Before running the patterns above, discover HOW this codebase declares credentials and config defaults. Search the codebase's own declaration idioms first — they catch language-specific instances that generic patterns miss:
- **Rust**: `defvar!` macros with PASS/SECRET/KEY/TOKEN in the variable name; `env::var().unwrap_or()` fallbacks; `const` declarations
- **Nix**: `mkOption { default = ...; }` blocks with password/secret/token in the option name
- **Python**: `os.getenv('X', 'default')` with non-empty defaults
- **Config files**: embedded PEM keys, base64 tokens in JSON/YAML

Value-pattern greps are the second pass, not the first.

**Semantic search augmentation:** For indexed repos, supplement grep patterns with
`/code-explore`'s multi-phrasing search (Step 1.5). Phrasing queries as hypothetical
insecure code (e.g., `mkOption type str default secret token oidc_client_secret`) finds
40-60% more results than natural language alone on Nix/Rust codebases. Use dual-model
consensus when both `voyage` and `voyage-context` indexes exist for the target path.
See `code-explore/references/search-strategies.md` for phrasing templates.

Focus on production-reachable code, not test fixtures or example files.

### 2. VERIFY: Actual Behavior
For each match, trace the code path to understand runtime behavior.

**Questions to answer:**
- When is this code executed? (Startup vs. runtime)
- What happens if a configuration variable is missing?
- Is there validation that enforces secure configuration?

### 3. CONFIRM: Production Impact
Determine if this issue reaches production:

If production config provides the variable → Lower severity (but still a code-level vulnerability)
If production config missing or uses default → CRITICAL

### 4. REPORT: with Evidence

**Example report:**
```
Finding: Hardcoded JWT Secret Fallback
Location: src/auth/jwt.ts:15
Pattern: const secret = process.env.JWT_SECRET || 'default';

Verification: App starts without JWT_SECRET; secret used in jwt.sign() at line 42
Production Impact: Dockerfile missing JWT_SECRET
Exploitation: Attacker forges JWTs using 'default', gains unauthorized access
Secure Alternative: const secret = process.env.JWT_SECRET; if (!secret) throw new Error('JWT_SECRET required'); — fail-closed at startup instead of using a guessable fallback. Also recommend rotating the previously-deployed default and adding the env var to the deploy config.
```

Every finding MUST include the `Secure Alternative` line — Success Criteria
require it, and downstream remediation work depends on a concrete suggested fix.

## Quick Verification Checklist

**Fallback Secrets:** `SECRET = env.get(X) or Y`
→ Verify: App starts without env var? Secret used in crypto/auth?
→ Skip: Test fixtures, example files

**Default Credentials:** Hardcoded `username`/`password` pairs
→ Verify: Active in deployed config? No runtime override?
→ Skip: Disabled accounts, documentation examples

**Fail-Open Security:** `AUTH_REQUIRED = env.get(X, 'false')`
→ Verify: Default is insecure (false/disabled/permissive)?
→ Safe: App crashes or default is secure (true/enabled/restricted)

**Weak Crypto:** MD5/SHA1/DES/RC4/ECB in security contexts
→ Verify: Used for passwords, encryption, or tokens?
→ Skip: Checksums, non-security hashing

**Permissive Access:** CORS `*`, permissions `0777`, public-by-default
→ Verify: Default allows unauthorized access?
→ Skip: Explicitly configured permissiveness with justification

**Debug Features:** Stack traces, introspection, verbose errors
→ Verify: Enabled by default? Exposed in responses?
→ Skip: Logging-only, not user-facing

For detailed examples and counter-examples, see [examples.md](references/examples.md).

## Deterministic verification (harness)

After the report draft is ready, encode findings as `findings.json`
(one entry per finding with `id`, `file`, `line`, `pattern`, `claim`,
optional `env_var` + `probe_cmd`) and run:

```bash
python3 scripts/verify_defaults.py findings.json --root . --ndjson run.ndjson --strict
python3 scripts/defaults_history.py append run.ndjson --repo "<repo>"
```

The Tier-1 oracle (`finding_locates` + `not_test_fixture` +
`fail_open_classify`) gates against stale reports and test-fixture FPs. The Tier-2 sandbox executor
(`startup_probe`) confirms fail-open by running the code with the env
var cleared. See [references/harness-pattern.md](references/harness-pattern.md)
for the eight-component map.
## Examples

**Example 1: Python service audit**
User says: "/insecure-defaults" on an MCP server codebase
Actions: SEARCH phase discovers framework patterns (FastMCP config, env var loading), VERIFY phase traces each default to determine fail-open vs fail-secure, CONFIRM checks production deployment configs, REPORT presents findings.
Result: Findings table with fail-open defaults ranked by production impact.

**Example 2: Terraform config check**
User says: "/insecure-defaults" on mcp-infra
Actions: Search for security group rules, IAM policies, encryption settings with weak defaults (0.0.0.0/0, *, unencrypted). Verify each against actual deployment state.
Result: Infrastructure security defaults report with remediation recommendations.
## Success Criteria

- Fail-open vs fail-secure correctly distinguished for every finding
- Framework-first discovery before generic pattern greps (per search-efficiency.md)
- Each finding includes: the default value, what happens in production with that default, and the secure alternative
- No findings from grep matches alone — each verified by reading the actual code path
