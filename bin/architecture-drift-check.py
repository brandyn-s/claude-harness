#!/usr/bin/env python3
"""Architecture drift gate — fail loudly when the system's self-image diverges
from reality. Run against the repo checkout; the repo is the source of truth.

Why this exists: ARCHITECTURE.md, README.md, and settings.json drifted apart
repeatedly (documented-but-unwired hooks, "we use bypassPermissions" while the
config ran `auto`, manifest/topic/rule counts off by 30-50%). The existing
`audit-architecture` skill audits prose coverage but is not a CI gate and is
hardcoded to the ~/.claude deploy layout. This is the gate: a small set of
hard contracts that keep intent == reality, wired into CI.

Contracts:
  A. Hook wiring  — every hook ARCHITECTURE.md's Layer-5 tables present as
                    active is wired in settings.json (HARD). Wired hooks the
                    doc never lists are reported (ADVISORY — doc completeness).
  B. Settings     — curated settings ARCHITECTURE.md states as *current* match
                    settings.json (HARD).
  C. Counts       — curated component-count claims match filesystem counts (HARD).
  D. Guard liveness — blocking guards with telemetry but zero blocks in the
                    window are flagged as maybe-obsolete (ADVISORY; skipped
                    when no telemetry, e.g. CI).
  G. Model runtime — configured request/fallback/effort/switch policy matches
                    the machine-readable provider/entrypoint/context/retention
                    ledger (HARD). Effective model/effort remain runtime facts.

Exit 1 if any HARD finding; 0 otherwise. Advisories never fail the build.

Usage:
  python bin/architecture-drift-check.py            # human report, repo root auto
  python bin/architecture-drift-check.py --json
  python bin/architecture-drift-check.py --liveness-days 30
"""
import argparse
import ast
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _read(rel):
    p = REPO / rel
    return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""


def _direct_wired_hooks(settings_text):
    """Return scripts registered directly in shell-string or exec form."""
    direct = set(re.findall(r'run-hook\\?"\s+([a-z0-9_-]+\.py)', settings_text)) | \
        set(re.findall(r'/hooks/([a-z0-9_-]+\.sh)', settings_text))
    try:
        settings = json.loads(settings_text)
    except (TypeError, json.JSONDecodeError):
        return direct

    for groups in (settings.get("hooks") or {}).values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            for hook in group.get("hooks", []) or []:
                if not isinstance(hook, dict) or hook.get("type") != "command":
                    continue
                command = hook.get("command", "")
                args = hook.get("args", [])
                if Path(command).name == "run-hook" and isinstance(args, list):
                    direct.update(
                        Path(arg).name for arg in args
                        if isinstance(arg, str) and arg.endswith(".py")
                    )
                elif (
                    isinstance(args, list)
                    and args
                    and isinstance(args[0], str)
                    and Path(args[0]).name == "run-hook"
                ):
                    direct.update(
                        Path(arg).name for arg in args[1:]
                        if isinstance(arg, str) and arg.endswith(".py")
                    )
                elif Path(command).suffix == ".sh":
                    direct.add(Path(command).name)
    return direct


def wired_hooks(settings_text):
    """Hook script basenames that are LIVE — wired directly in
    settings.json, OR loaded by a wired dispatcher's import list.

    The dispatcher half exists because "wired" used to mean settings.json
    text only, which read dispatcher-loaded guards as dead: that blind spot
    fooled the 2026-06-09 hooks audit AND PR #1147 (which standalone-wired
    rule-size-guard "because it was never registered" — it was already live
    via write-edit-dispatcher, creating double execution). B1/F1 + B9.
    """
    wired = _direct_wired_hooks(settings_text)
    # Guards loaded by a dispatcher that is itself wired count as wired.
    for dispatcher in ("write-edit-dispatcher.py", "bash-pretooluse-dispatcher.py"):
        if dispatcher in wired:
            disp_path = REPO / "hooks" / dispatcher
            if disp_path.exists():
                src = disp_path.read_text(encoding="utf-8", errors="ignore")
                # GUARDS entries: ("name", "file-name.py"[, "open"|"closed"|"warn"])
                # — the optional third element is the per-guard fail posture
                # (B2/F4, 2026-06-10; "warn" added with the Bash dispatcher).
                wired |= set(re.findall(
                    r'\(\s*"[a-z0-9_-]+"\s*,\s*"([a-z0-9_-]+\.py)"'
                    r'(?:\s*,\s*"[a-z]+")?\s*\)', src))
    return wired


_HOOKS_HEADING_RE = re.compile(r"^## (?:Layer 5\b|\d+\.\s*Hooks\b).*$", re.MULTILINE)


def _hooks_section(arch):
    """The hooks section of ARCHITECTURE.md, whichever heading style it uses.

    Old style: "## Layer 5" up to "### Rules". Current style (2026-09): "## 1. Hooks
    — programmable enforcement" up to the next "## " heading. The old anchors
    matched nothing in the current document, so the segment was empty and every
    wired hook read as undocumented (2026-09-04 fix)."""
    m = _HOOKS_HEADING_RE.search(arch)
    if not m:
        return ""
    start = m.end()
    nxt = re.compile(r"^(?:## |### Rules\b)", re.MULTILINE).search(arch, start)
    return arch[start:nxt.start()] if nxt else arch[start:]


def layer5_documented_hooks(arch):
    """Hooks ARCHITECTURE.md's hooks section presents as active (excludes the
    'Not Yet Used' subsection)."""
    seg = _hooks_section(arch)
    nyu = seg.find("#### Not Yet Used")
    if nyu != -1:
        nxt = seg.find("####", nyu + 1)
        seg = seg[:nyu] + (seg[nxt:] if nxt != -1 else "")
    return set(re.findall(r'`([a-z0-9-]+\.py)`', seg))


def readme_documented_hooks(readme):
    """Hooks listed in hooks/README.md's inventory tables. ARCHITECTURE.md is a
    representative table by design; the README is the full registry, so a hook
    documented there is documented."""
    return set(re.findall(r'^\|\s*`([a-z0-9-]+\.py)`', readme, re.MULTILINE))


# ── Check B: curated settings the doc states as the CURRENT value ──
# Each: (label, settings.json getter, ARCHITECTURE.md extractor regex, normalizer)
def _norm_tokens(v):
    v = v.strip().replace("tokens", "").strip()
    m = re.match(r'(\d+)\s*[Kk]$', v)
    if m:
        return str(int(m.group(1)) * 1000)
    return v


SETTINGS_CONTRACTS = [
    ("Minimum version",
     lambda s: s.get("minimumVersion", ""),
     r'\|\s*Minimum version\s*\|\s*([^|]+?)\s*\|',
     lambda v: v.strip()),
    ("Permission mode",
     lambda s: s["permissions"].get("defaultMode", ""),
     r'\|\s*Permission mode\s*\|\s*([^|]+?)\s*\|',
     lambda v: v.strip()),
    ("ToolSearch (ENABLE_TOOL_SEARCH)",
     lambda s: s["env"].get("ENABLE_TOOL_SEARCH", ""),
     r'\|\s*ToolSearch\s*\|\s*([^|]+?)\s*\|',
     lambda v: v.strip()),
    ("MCP output (MAX_MCP_OUTPUT_TOKENS)",
     lambda s: (
         s["env"]["MAX_MCP_OUTPUT_TOKENS"]
         if "MAX_MCP_OUTPUT_TOKENS" in s["env"]
         else "native 25K-token default"
     ),
     r'\|\s*MCP output\s*\|\s*([^|]+?)\s*\|',
     _norm_tokens),
    ("File read (CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS)",
     lambda s: s["env"].get(
         "CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS", "platform default"
     ),
     r'\|\s*File read\s*\|\s*([^|]+?)\s*\|',
     _norm_tokens),
    ("Skill listing budget",
     lambda s: f'{s.get("skillListingBudgetFraction", 0) * 100:g}% context window',
     r'\|\s*Skill listing\s*\|\s*([^|]+?)\s*\|',
     lambda v: v.strip()),
    ("Dynamic workflow guideline",
     lambda s: f'{s.get("workflowSizeGuideline", "") } guideline',
     r'\|\s*Dynamic workflows\s*\|\s*([^|]+?)\s*\|',
     lambda v: v.strip()),
    ("Agent budgets",
     lambda s: (
         f'{s["env"].get("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS", "")} concurrent; '
         f'{s["env"].get("CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION", "")} per session; '
         f'depth {s["env"].get("CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH", "")}'
     ),
     r'\|\s*Agent budgets\s*\|\s*([^|]+?)\s*\|',
     lambda v: v.strip()),
]


# ── Check C: curated count claims. (label, doc file, regex, actual fn) ──
def _count(pattern):
    return len(glob.glob(str(REPO / pattern)))


def _skill_count():
    return len(glob.glob(str(REPO / "skills/*/SKILL.md")))


def _agent_count():
    return len([f for f in os.listdir(REPO / "agents")
                if f.endswith(".md") and f not in ("README.md", "TEMPLATE.md")])


def _plugin_skills(plugin):
    return lambda: _count(f"marketplace/{plugin}/skills/*/SKILL.md")


def _hooks_count():
    """Top-level hook scripts (Python + shell, incl. shared libs) — what the
    README inventory row counts."""
    return (len(glob.glob(str(REPO / "hooks/*.py")))
            + len(glob.glob(str(REPO / "hooks/*.sh"))))


def _safety_net_hooks():
    """Hook scripts shipped in safety-net, excluding shared import-only libs
    (hook_input.py, atomic_write.py) — README counts enforcement hooks."""
    libs = {"hook_input.py", "atomic_write.py"}
    return len([f for f in glob.glob(str(REPO / "marketplace/safety-net/hooks/*.py"))
                if os.path.basename(f) not in libs])


def _tracked_topic_count():
    """Tracked topic files only. ARCHITECTURE.md documents the tracked set;
    live machines also carry hook-managed gitignored topics (e.g.
    recent-sessions.md, Stop-hook episodic memory) that CI/worktrees never
    see — counting disk files makes the gate fail ONLY on live machines
    (claims 50, actual 51, 2026-06-12). Fall back to the raw glob count
    when git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "agent-memory/topics/*.md"],
            capture_output=True, timeout=10)
        if out.returncode == 0:
            return len([l for l in out.stdout.decode("utf-8").splitlines() if l.strip()])
    except Exception:
        pass
    return _count("agent-memory/topics/*.md")


COUNT_CONTRACTS = [
    # EMPTY BY DESIGN (2026-07-29). Every entry here was a HARDCODED COUNT in
    # prose, and a hand-maintained count is a DRIFT GENERATOR: it is wrong the
    # moment anyone adds a file, so the "gate" mostly enforced a chore. The
    # docs were changed to say what each thing IS rather than how many there
    # are — a mermaid node's siblings already describe themselves without
    # counting, a table's parenthetical INVARIANT ("one per hook script") is
    # the load-bearing part, and a plugin row's named examples are the
    # description. Nothing a reader acts on was lost; anyone who wants a count
    # can count the files, which is authoritative in a way prose never is.
    #
    # DO NOT re-add a count contract. Adding one means adding a number to a doc
    # that a future file will falsify, and the failure lands on whoever is
    # unlucky enough to add that file. If you need a count to be visible,
    # GENERATE it (the KB does this — tools/kb.py emits README/Home from the
    # corpus) rather than asserting it in hand-edited prose.
    #
    # check_counts() iterates this list, so an empty list is a no-op and the
    # gate's OTHER contracts (hook wiring, settings example, blocking-guard
    # efficacy) are untouched — those check STRUCTURE, which does not drift on
    # a file add.
]

BLOCKING_HOOKS = {
    "bash-security-guard.py", "search-path-guard.py", "block-partial-read.py",
    "config-guard.py", "config-change-validate.py", "memory-write-guard.py",
    "destructive-ops-guard.py",
    "git-empty-push-guard.py", "bash-tail-buffering-guard.py",
}


def check_hooks(arch, settings_text, readme_text=""):
    hard, advisory = [], []
    wired = wired_hooks(settings_text)
    documented = layer5_documented_hooks(arch)
    documented_anywhere = documented | readme_documented_hooks(readme_text)
    # Guards loaded via a dispatcher are documented by the DISPATCHER's
    # Layer-5 row (which names them in prose, deliberately not as
    # backticked .py — see the B1 consolidation). Don't advisory-flag them
    # as undocumented; they're wired AND documented, just indirectly.
    dispatcher_loaded = wired - _direct_wired_hooks(settings_text)
    for h in sorted(documented - wired):
        hard.append(f"[A] hook `{h}` is in ARCHITECTURE.md's Layer-5 tables (active) "
                    f"but is NOT wired in settings.json")
    for h in sorted({w for w in wired if w.endswith('.py')} - documented_anywhere - dispatcher_loaded):
        advisory.append(f"[A] hook `{h}` is wired in settings.json but documented neither in "
                        f"ARCHITECTURE.md's hooks table nor in hooks/README.md's inventory (undocumented)")
    return hard, advisory


def check_settings(arch, settings):
    hard = []
    for label, getter, pattern, norm in SETTINGS_CONTRACTS:
        m = re.search(pattern, arch)
        if not m:
            continue  # claim absent → not gated (avoids brittleness)
        doc_val = norm(m.group(1))
        actual = norm(str(getter(settings)))
        if doc_val != actual:
            hard.append(f"[B] {label}: ARCHITECTURE.md says `{m.group(1).strip()}` "
                        f"but settings.json has `{getter(settings)}`")
    return hard


PROVIDER_MODEL_PREFIXES = (
    "us.anthropic.", "us-gov.anthropic.", "eu.anthropic.",
    "apac.anthropic.", "arn:aws",
)


def check_global_model(settings):
    """HARD: every model surface in the global settings.json must be 1P-format.

    A provider-prefixed ID (us.anthropic.*, us-gov.anthropic.*, arn:aws:*) in
    the global settings is inherited by the first-party launchers (claude,
    claude-ws) and misroutes them onto Bedrock (profile-misroute 2026-06-18;
    recurrences 2026-06-21, 2026-06-26, 2026-08-18). Provider-specific models
    belong only in a launcher's own exports (iterm-config / the claude-gov
    block). Three vectors are gated, each of which has shipped the misroute:
      - `model` (the #1411 recurrence),
      - `fallbackModel` (same field family, same launcher inheritance),
      - the `env` block (2026-08-18: `ANTHROPIC_DEFAULT_OPUS_MODEL` set to a
        us-gov.* ID remapped the /model Opus rows in 1P sessions onto a
        GovCloud ID, forcing fallback to Sonnet. settings.json env is injected
        by the CLI into EVERY session after a launcher's subshell scrub runs,
        so no launcher unset can defend against this vector).

    The 2026-08-09 SAVED_PROVIDER_DEFAULT allowlist (#1950) is deliberately
    removed: allowlisting the committed poison instead of fixing it kept the
    misroute latent for every 1P session (operator directive 2026-08-18:
    GovCloud IDs only in GovCloud launchers, 1P models everywhere else).
    """
    hard = []

    def flag(surface, value):
        hard.append(
            f"[F] settings.json {surface} = `{value}` is a provider-specific "
            f"(Bedrock/GovCloud) ID; global settings must use 1P-format "
            f"`claude-*` IDs. Provider-specific models belong only in a "
            f"launcher's own ANTHROPIC_MODEL (iterm-config); reset via /model "
            f"from a plain `claude` (1P) session."
        )

    model = settings.get("model")
    if isinstance(model, str) and model.startswith(PROVIDER_MODEL_PREFIXES):
        flag("`model`", model)

    fallback = settings.get("fallbackModel")
    fallbacks = fallback if isinstance(fallback, list) else [fallback]
    for fb in fallbacks:
        if isinstance(fb, str) and fb.startswith(PROVIDER_MODEL_PREFIXES):
            flag("`fallbackModel`", fb)

    for key, value in (settings.get("env") or {}).items():
        if isinstance(value, str) and value.startswith(PROVIDER_MODEL_PREFIXES):
            flag(f"env `{key}`", value)

    return hard


MODEL_RUNTIME_CONTRACT = "contracts/model-runtime.json"
MODEL_ENTRYPOINT_FIELDS = {
    "id",
    "owner",
    "provider",
    "modelSource",
    "contextClass",
    "retentionClass",
    "retentionEvidence",
}
MODEL_RECEIPT_FIELDS = {
    "requestedModel",
    "effectiveModel",
    "requestedEffort",
    "effectiveEffort",
    "provider",
    "entrypoint",
    "contextClass",
    "switchReason",
    "refusalState",
    "cliVersion",
}
MANAGED_MODEL_SETTINGS = {"enforceAvailableModels"}


def check_managed_model_policy(managed):
    """Validate Anthropic's managed-only default-model allowlist extension."""

    hard = []
    if not isinstance(managed, dict):
        return ["[G] managed settings template root must be an object"]
    if "enforceAvailableModels" not in managed:
        return hard
    enforce = managed.get("enforceAvailableModels")
    allowlist = managed.get("availableModels")
    if not isinstance(enforce, bool):
        hard.append("[G] managed `enforceAvailableModels` must be boolean")
    if enforce and (
        not isinstance(allowlist, list)
        or not allowlist
        or any(not isinstance(item, str) or not item for item in allowlist)
    ):
        hard.append(
            "[G] managed `enforceAvailableModels: true` requires a nonempty "
            "string-only `availableModels` allowlist"
        )
    return hard


def _implemented_receipt_fields():
    """Read the literal hook implementation contract without executing hooks."""

    source = _read("hooks/session_runtime.py")
    if not source:
        return set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name)
            and target.id == "REQUIRED_PROVENANCE_FIELDS"
            for target in targets
        ):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (TypeError, ValueError):
            return set()
        return set(value) if isinstance(value, (tuple, list, set)) else set()
    return set()


def check_model_runtime_contract(settings, contract=None):
    """HARD: settings intent must match the runtime provenance ledger."""
    hard = []
    for key in MANAGED_MODEL_SETTINGS:
        if key in settings:
            hard.append(
                f"[G] `{key}` is a managed-only setting; it must "
                "not be placed in user settings.json"
            )
    if contract is None:
        text = _read(MODEL_RUNTIME_CONTRACT)
        if not text:
            return [f"[G] missing {MODEL_RUNTIME_CONTRACT}"]
        try:
            contract = json.loads(text)
        except json.JSONDecodeError as exc:
            return [f"[G] {MODEL_RUNTIME_CONTRACT} is invalid JSON: {exc}"]
    if not isinstance(contract, dict):
        return [f"[G] {MODEL_RUNTIME_CONTRACT} root must be an object"]

    defaults = contract.get("settingsDefaults")
    if not isinstance(defaults, dict):
        return [f"[G] {MODEL_RUNTIME_CONTRACT} settingsDefaults must be an object"]

    expected = {
        "requestedModel": settings.get("model"),
        "fallbackModels": settings.get("fallbackModel", []),
        "requestedEffort": settings.get("effortLevel"),
        "switchModelsOnFlag": settings.get("switchModelsOnFlag"),
    }
    for field, actual in expected.items():
        if defaults.get(field) != actual:
            hard.append(
                f"[G] model runtime `{field}` is {defaults.get(field)!r} but "
                f"settings.json resolves to {actual!r}"
            )
    for field in ("effectiveModel", "effectiveEffort"):
        if defaults.get(field) != "runtime-unknown":
            hard.append(
                f"[G] `{field}` must remain `runtime-unknown`; configured intent "
                "is not evidence of the effective runtime"
            )

    entrypoints = contract.get("entrypoints")
    if not isinstance(entrypoints, list) or not entrypoints:
        hard.append("[G] model runtime contract must declare at least one entrypoint")
    else:
        seen = set()
        for index, entry in enumerate(entrypoints):
            if not isinstance(entry, dict):
                hard.append(f"[G] entrypoints[{index}] must be an object")
                continue
            missing = sorted(
                field for field in MODEL_ENTRYPOINT_FIELDS if not entry.get(field)
            )
            if missing:
                hard.append(
                    f"[G] entrypoint {entry.get('id', index)!r} missing fields: "
                    + ", ".join(missing)
                )
            entry_id = entry.get("id")
            if entry_id in seen:
                hard.append(f"[G] duplicate model runtime entrypoint id `{entry_id}`")
            seen.add(entry_id)

    receipt_fields = set(contract.get("requiredReceiptFields") or [])
    missing_receipt = sorted(MODEL_RECEIPT_FIELDS - receipt_fields)
    if missing_receipt:
        hard.append(
            "[G] model runtime receipt contract missing fields: "
            + ", ".join(missing_receipt)
        )
    receipt_contract = contract.get("receiptContract")
    if not isinstance(receipt_contract, dict):
        hard.append("[G] model runtime contract missing receiptContract")
    else:
        expected_receipt_contract = {
            "schemaVersion": 3,
            "object": "runtime_provenance",
            "unknownValue": "runtime-unknown",
        }
        for field, expected_value in expected_receipt_contract.items():
            if receipt_contract.get(field) != expected_value:
                hard.append(
                    f"[G] receiptContract.{field} must be {expected_value!r}"
                )
        phases = receipt_contract.get("capturePhases")
        if not isinstance(phases, dict) or phases.get("SessionEnd") != []:
            hard.append(
                "[G] receiptContract must record that SessionEnd exposes no "
                "model provenance fields"
            )
    implemented = _implemented_receipt_fields()
    if implemented != receipt_fields:
        hard.append(
            "[G] SessionStart/SessionEnd receipt implementation fields differ "
            f"from the model runtime contract: declared={sorted(receipt_fields)!r} "
            f"implemented={sorted(implemented)!r}"
        )
    session_end_source = _read("hooks/session-end.py")
    enricher_source = _read("bin/enrich-session-end-receipts.py")
    if "runtime_provenance" not in session_end_source:
        hard.append("[G] SessionEnd does not emit the declared runtime provenance object")
    if "runtime_provenance" not in enricher_source:
        hard.append("[G] receipt enricher does not update the declared provenance object")
    return hard


def check_counts():
    hard = []
    texts = {}
    for label, fname, pattern, actual_fn in COUNT_CONTRACTS:
        text = texts.setdefault(fname, _read(fname))
        m = re.search(pattern, text)
        if not m:
            continue
        claimed, actual = int(m.group(1)), actual_fn()
        if claimed != actual:
            hard.append(f"[C] {label}: {fname} claims {claimed}, actual {actual}")
    return hard


def check_example_settings(settings_text):
    """HARD: settings.example.json must mirror the live hook wiring.

    The example is the documented interface for adopters; it fell six hook
    event types and dozens of hooks behind the live config before 2026-06-10
    because nothing checked it. Contract: every hook EVENT key in
    settings.json exists in settings.example.json, and every hook script
    wired in settings.json is referenced in the example. Env/permissions may
    diverge by design (org-specific); hook wiring may not.
    """
    hard = []
    example_text = _read("settings.example.json")
    if not example_text:
        return ["[E] settings.example.json missing from repo root"]
    try:
        example = json.loads(example_text)
    except json.JSONDecodeError as e:
        return [f"[E] settings.example.json is not valid JSON: {e}"]
    live = json.loads(settings_text)

    live_events = set((live.get("hooks") or {}).keys())
    example_events = set((example.get("hooks") or {}).keys())
    for ev in sorted(live_events - example_events):
        hard.append(f"[E] hook event `{ev}` is wired in settings.json but absent "
                    f"from settings.example.json — regenerate the example")

    missing_scripts = wired_hooks(settings_text) - wired_hooks(example_text)
    for h in sorted(missing_scripts):
        hard.append(f"[E] hook `{h}` is wired in settings.json but not in "
                    f"settings.example.json — regenerate the example")

    hard.extend(_check_blocking_timeouts(live, example))
    return hard


#: A PreToolUse guard that TIMES OUT never returns its blocking decision, so the
#: operation proceeds UNGUARDED (documented in hooks/run-hook). Measured wrapper
#: start-up on this host spans 1.4-4.1s, so any blocking guard budgeted at or below
#: this is at real risk of being killed before its body runs.
MIN_BLOCKING_TIMEOUT = 10

#: Events whose hooks can BLOCK an action. Drift here is a security regression, not
#: a cosmetic one.
BLOCKING_EVENTS = ("PreToolUse", "PreCompact", "ConfigChange")


def _hook_timeouts(cfg, event):
    """{script: timeout} for one event in a parsed settings dict."""
    out = {}
    for entry in (cfg.get("hooks") or {}).get(event, []) or []:
        for h in entry.get("hooks", []) or []:
            cmd = str(h.get("command", ""))
            if not cmd:
                continue
            args = h.get("args", [])
            script = next(
                (
                    Path(arg).name for arg in args
                    if isinstance(arg, str) and arg.endswith(".py")
                ),
                cmd.split()[-1].strip('"'),
            ) if isinstance(args, list) else cmd.split()[-1].strip('"')
            out[script] = h.get("timeout")
    return out


def _check_blocking_timeouts(live, example):
    """HARD: a blocking guard's example timeout must not be lower than live's.

    Audit finding H4, fixed 2026-07-26. This check did not exist, which is why the
    gate reported OK while 44 of 57 shared hook registrations had timeout drift --
    including EVERY blocking security guard at 30s live vs 3s in the example
    (bash-security-guard, destructive-ops-guard, pre-agent-dispatch,
    security-write-confirm, write-edit-dispatcher, staged-additions-guard, ...).

    Why it matters: a timed-out PreToolUse hook never returns its decision, so the
    operation proceeds UNGUARDED. With wrapper start-up measured at 1.4-4.1s on this
    host, a 3s budget can kill the guard before its body executes -- making a
    fresh/example-based install materially weaker than the live host in exactly the
    security layer that is supposed to be strongest.

    Two conditions are enforced, both only for BLOCKING events:
      * the example's timeout must be >= the live timeout (no silent weakening);
      * no blocking guard may sit at or below MIN_BLOCKING_TIMEOUT in either file.
    Non-blocking events (loggers, fixers) may legitimately differ and are ignored.
    """
    hard = []
    for event in BLOCKING_EVENTS:
        live_t = _hook_timeouts(live, event)
        ex_t = _hook_timeouts(example, event)
        for script in sorted(set(live_t) & set(ex_t)):
            lv, ev = live_t[script], ex_t[script]
            if not isinstance(lv, int) or not isinstance(ev, int):
                continue
            if ev < lv:
                hard.append(
                    f"[E] blocking hook `{script}` ({event}) has timeout {ev}s in "
                    f"settings.example.json but {lv}s live — a fresh install would "
                    f"run this guard on a shorter budget; a timed-out PreToolUse "
                    f"hook returns NO decision and the action proceeds unguarded"
                )
            elif ev <= MIN_BLOCKING_TIMEOUT:
                hard.append(
                    f"[E] blocking hook `{script}` ({event}) timeout is {ev}s in "
                    f"settings.example.json — below the {MIN_BLOCKING_TIMEOUT}s floor "
                    f"(measured wrapper start-up alone is 1.4-4.1s)"
                )
            if isinstance(lv, int) and lv <= MIN_BLOCKING_TIMEOUT:
                hard.append(
                    f"[E] blocking hook `{script}` ({event}) timeout is {lv}s in "
                    f"settings.json — below the {MIN_BLOCKING_TIMEOUT}s floor "
                    f"(measured wrapper start-up alone is 1.4-4.1s)"
                )
    return hard


def check_liveness(days):
    """ADVISORY: blocking guards with telemetry but zero blocks in the window."""
    advisory = []
    audit_dir = Path(os.environ.get("HOME") or os.environ.get("USERPROFILE") or Path.home()) / ".claude" / "audit"
    files = sorted(glob.glob(str(audit_dir / "hook-fires-*.jsonl")))
    if not files:
        return advisory  # no telemetry (e.g. CI) — skip silently
    import datetime as dt
    cutoff = (dt.date.today() - dt.timedelta(days=days)).strftime("%Y%m%d")
    invokes, blocks, stamps = {}, {}, set()
    for f in files:
        stamp = Path(f).stem.replace("hook-fires-", "")
        if stamp.isdigit() and stamp < cutoff:
            continue
        stamps.add(stamp)
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            h = e.get("hook", "?")
            invokes[h] = invokes.get(h, 0) + 1
            if e.get("exit") == 2:
                blocks[h] = blocks.get(h, 0) + 1
    if len(stamps) < 2:
        return advisory  # not enough of a window to judge
    for h in sorted(BLOCKING_HOOKS):
        if invokes.get(h, 0) > 0 and blocks.get(h, 0) == 0:
            advisory.append(f"[D] blocking guard `{h}` fired {invokes[h]}x but blocked "
                            f"0 times in the last {days}d — verify it still earns its keep")
    return advisory


def main():
    ap = argparse.ArgumentParser(description="Architecture drift gate.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--liveness-days", type=int, default=30)
    args = ap.parse_args()

    arch = _read("ARCHITECTURE.md")
    settings_text = _read("settings.json")
    if not arch or not settings_text:
        print("ERROR: ARCHITECTURE.md or settings.json not found at repo root", file=sys.stderr)
        sys.exit(2)
    settings = json.loads(settings_text)

    hard, advisory = [], []
    readme_path = ROOT / "hooks" / "README.md" if "ROOT" in globals() else Path(__file__).resolve().parents[1] / "hooks" / "README.md"
    readme_text = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    h, a = check_hooks(arch, settings_text, readme_text); hard += h; advisory += a
    hard += check_settings(arch, settings)
    hard += check_global_model(settings)
    hard += check_model_runtime_contract(settings)
    managed_text = _read("templates/managed-settings.json")
    if managed_text:
        try:
            hard += check_managed_model_policy(json.loads(managed_text))
        except json.JSONDecodeError as exc:
            hard.append(f"[G] templates/managed-settings.json is invalid JSON: {exc}")
    hard += check_counts()
    hard += check_example_settings(settings_text)
    advisory += check_liveness(args.liveness_days)

    if args.json:
        print(json.dumps({"hard": hard, "advisory": advisory}, indent=2))
        sys.exit(1 if hard else 0)

    if hard:
        print(f"ARCHITECTURE DRIFT — {len(hard)} contract violation(s):")
        for f in hard:
            print(f"  FAIL {f}")
    else:
        print("Architecture drift gate: OK — hooks and settings match reality.")
    if advisory:
        print(f"\n{len(advisory)} advisory (non-blocking):")
        for f in advisory:
            print(f"  warn {f}")
    sys.exit(1 if hard else 0)


if __name__ == "__main__":
    main()
