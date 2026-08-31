#!/usr/bin/env python3
"""Skill quality validator — scores each SKILL.md against an outcome-oriented rubric.

Sources:
- https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
- https://code.claude.com/docs/en/skills
- https://github.com/anthropics/skills  (canonical example corpus)
- Empirical: Bara, "Two reliability problems" (20× odds ratio for directive language)
- Empirical: Seleznov 650-trial activation study via dev.to

External calibration (2026-05-27): running this rubric against the 17 published
skills in github.com/anthropics/skills gave: A- × 2, B+ × 1, B × 7, B- × 5,
C+ × 2. Zero S-tier. The rubric is therefore STRICTER than Anthropic's own
published baseline. Worst-hit checks vs Anthropic's own corpus:
  - C3_allowed_tools: 17/17 fail (Claude Code extension; now informational
    because Anthropic's skill spec does not require it)
  - A5_donot_clause: 14/17 fail (basis is empirical activation study, not
    Anthropic-published; deliberate over-shoot)
  - B2_concrete_example: 13/17 fail (Anthropic uses lighter example formats)
  - D1_evaluations: 12/17 fail (Anthropic recommends but doesn't ship)
  - A4_trigger_domain: 11/17 fail
Position: our rubric is intentionally stricter than Anthropic's published
examples because we want higher activation rates and verifiable outcomes.
The criteria above (except C3) are empirically supported even though Anthropic's
canonical examples don't apply them uniformly.

Rubric (14 automatable checks, organized by impact tier; 2 manual at corpus level).

TIER 1 — ACTIVATION (skill is found and fires)
  A1. Frontmatter parses + has `name` + `description` (Anthropic-required fields)
  A2. Combined description + when_to_use ≤1536 chars and contains no XML tags
      (current Claude Code listing truncation boundary; local fail-before-truncate rule)
  A3. Description is third-person (no "I/we/you" — Anthropic POV warning)
  A4. Description (or when_to_use) names a concrete domain + has trigger phrases
  A5. Description (or when_to_use) has explicit "Do NOT use for" / "Don't use" negative-constraint clause
       (highest-leverage empirical: ~77% → ~100% activation in trials)
       Note: trigger phrases and the Do-NOT clause may live in the `when_to_use`
       field (Claude Code extension) so the display-facing `description` stays a
       terse one-liner; A4/A5 evaluate `description` + `when_to_use` combined.
  A6. Name conforms: lowercase + hyphens + digits, ≤64 chars, no "anthropic"/"claude"

TIER 2 — EXECUTION (when fired, it does the right thing)
  B1. Body has procedural structure (≥3 "## " sections AND at least one numbered/stepped flow)
  B2. At least one concrete example (input → output, not just an "Examples" header)
  B3. All `references/*.md` citations resolve, ≤1 level deep, no Windows paths

TIER 3 — HYGIENE
  C1. Body ≤510 lines (Anthropic soft cap with 10-line tolerance)
  C1b. Skills above a conservative 4,000-token chars/4 proxy carry an early
       post-compaction recovery contract (5,000 per skill / 25,000 combined)
  C2. argument-hint, if declared, has concrete example (>15 chars or empty)
  C3. allowed-tools declared (informational; not Anthropic-required)

TIER 4 — OUTCOME
  D1. ≥3 evaluations exist  (Anthropic explicit: "Create evaluations BEFORE
       writing extensive documentation." Detected via: tests/<skill>/ dir
       with ≥3 files, references/eval*.md containing ≥3 entries, or inline
       "Eval N:" / "Example N:" markers in SKILL.md or references/.)
  E1. Executable examples do not pair supported Claude model IDs with API
      controls that those models reject; dynamic Anthropic requests fail closed

CORPUS-LEVEL (reported separately by --triggers):
  E1. Trigger space doesn't conflict with siblings

Grade mapping (out of 14 automatable points):
  S    14    -> exemplary (all checks pass)
  A    13    -> excellent, one minor gap
  A-   12    -> solid
  B+   11    -> functional, gaps
  B    10    -> functional, notable gaps
  B-    9    -> rough
  C+    8    -> structural issues
  C    ≤7    -> broken or fundamentally weak

(Example `effort:` convention is not scored; it's a local convention and not
in the Anthropic spec.)

Usage:
    python3 scripts/validate-skills.py
    python3 scripts/validate-skills.py --skill <name>
    python3 scripts/validate-skills.py --json
    python3 scripts/validate-skills.py --below 14    # show only sub-S skills
    python3 scripts/validate-skills.py --fails A5    # show only skills failing a specific check
    python3 scripts/validate-skills.py --triggers    # corpus-level trigger-conflict scan
"""
import argparse
import ast
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

# Supported-model API compatibility is evaluated inside executable fenced examples.
# This avoids turning one model generation's controls into a global ban for older
# models or unrelated APIs. Prose can document a failure mode without tripping E1;
# code examples that pair an exact covered model ID with an incompatible control
# still fail.
RESTRICTED_API_MODEL_IDS = frozenset({
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-sonnet-5",
})
ALWAYS_THINKING_MODEL_IDS = frozenset({"claude-fable-5", "claude-mythos-5"})
FENCED_CODE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
SAMPLING_CONTROL_RE = re.compile(
    r"[\"']?(?:temperature|top_p|top_k)[\"']?\s*[=:]",
    re.IGNORECASE,
)
MANUAL_THINKING_RE = re.compile(
    r"(?:\bthinking_budget\b|\bbudget_tokens\b|"
    r"[\"']?thinking[\"']?\s*[=:]\s*\{?[^\n}]*?"
    r"[\"']?type[\"']?\s*[=:]\s*[\"']enabled[\"'])",
    re.IGNORECASE,
)
DISABLED_THINKING_RE = re.compile(
    r"[\"']?thinking[\"']?\s*[=:]\s*\{?[^\n}]*?"
    r"[\"']?type[\"']?\s*[=:]\s*[\"']disabled[\"']",
    re.IGNORECASE,
)
XHIGH_OR_MAX_EFFORT_RE = re.compile(
    r"[\"']?effort[\"']?\s*[=:]\s*[\"'](?:xhigh|max)[\"']",
    re.IGNORECASE,
)


_UNRESOLVED = object()


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _literal(
    node: ast.AST,
    bindings: dict[str, list[tuple[int, object]]],
    before_line: int,
) -> object:
    if isinstance(node, ast.Name):
        candidates = [
            value
            for line, value in bindings.get(node.id, [])
            if line < before_line
        ]
        return candidates[-1] if candidates else _UNRESOLVED
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal(node.left, bindings, before_line)
        right = _literal(node.right, bindings, before_line)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        return _UNRESOLVED
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
                continue
            if isinstance(value, ast.FormattedValue):
                resolved = _literal(value.value, bindings, before_line)
                if isinstance(resolved, (str, int, float)):
                    parts.append(str(resolved))
                    continue
            return _UNRESOLVED
        return "".join(parts)
    if isinstance(node, ast.Dict):
        keys = [_literal(key, bindings, before_line) for key in node.keys]
        values = [_literal(value, bindings, before_line) for value in node.values]
        if _UNRESOLVED in keys or _UNRESOLVED in values:
            return _UNRESOLVED
        return dict(zip(keys, values))
    if isinstance(node, (ast.List, ast.Tuple)):
        values = [_literal(value, bindings, before_line) for value in node.elts]
        if _UNRESOLVED in values:
            return _UNRESOLVED
        return values if isinstance(node, ast.List) else tuple(values)
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return _UNRESOLVED


def _request_conflicts(model: object, params: dict[str, object]) -> set[str]:
    """Evaluate one Anthropic Messages request, never a whole code block."""
    exact_restricted = isinstance(model, str) and model in RESTRICTED_API_MODEL_IDS
    unresolved_model = model is _UNRESOLVED
    if not exact_restricted and not unresolved_model:
        return set()

    hits: set[str] = set()
    if any(name in params for name in ("temperature", "top_p", "top_k")):
        hits.add(
            "sampling parameters on a restricted Claude model"
            if exact_restricted
            else "sampling parameters with unresolved Anthropic model"
        )

    thinking = params.get("thinking", _UNRESOLVED)
    manual_thinking = "thinking_budget" in params or "budget_tokens" in params
    disabled_thinking = False
    if isinstance(thinking, dict):
        thinking_type = thinking.get("type")
        manual_thinking = manual_thinking or thinking_type == "enabled" or (
            "budget_tokens" in thinking
        )
        disabled_thinking = thinking_type == "disabled"
    elif thinking is _UNRESOLVED and "thinking" in params:
        hits.add("unresolved thinking configuration on an Anthropic request")

    if manual_thinking:
        hits.add(
            "manual extended thinking on a restricted Claude model"
            if exact_restricted
            else "manual extended thinking with unresolved Anthropic model"
        )

    messages = params.get("messages")
    assistant_prefill = (
        isinstance(messages, list)
        and bool(messages)
        and isinstance(messages[-1], dict)
        and messages[-1].get("role") == "assistant"
    )
    if assistant_prefill:
        hits.add(
            "assistant-message prefill on a restricted Claude model"
            if exact_restricted
            else "assistant-message prefill with unresolved Anthropic model"
        )

    if disabled_thinking:
        if model in ALWAYS_THINKING_MODEL_IDS:
            display = str(model).removeprefix("claude-").replace("-", " ").title()
            hits.add(f"disabled thinking on Claude {display}")
        elif unresolved_model:
            hits.add("disabled thinking with unresolved Anthropic model")

    output_config = params.get("output_config")
    effort = output_config.get("effort") if isinstance(output_config, dict) else None
    if model == "claude-opus-5" and disabled_thinking and effort in {"xhigh", "max"}:
        hits.add("disabled thinking with xhigh/max effort on Claude Opus 5")
    return hits


def _python_request_conflicts(block: str) -> tuple[set[str], bool]:
    """Return request-level conflicts and whether Python parsing succeeded."""
    try:
        tree = ast.parse(block)
    except SyntaxError:
        return set(), False

    bindings: dict[str, list[tuple[int, object]]] = {}
    assignments = sorted(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
        ),
        key=lambda node: (node.lineno, node.col_offset),
    )
    for node in assignments:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value_node = node.value
            value = (
                _literal(value_node, bindings, node.lineno)
                if value_node is not None
                else _UNRESOLVED
            )
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    bindings.setdefault(target.id, []).append((node.lineno, value))

    hits: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _dotted_name(node.func)
        is_sdk_request = call_name.endswith(
            (".messages.create", ".messages.parse")
        )
        is_http_request = False
        http_payload: object = _UNRESOLVED
        if call_name.endswith(".post"):
            url_node = node.args[0] if node.args else None
            if url_node is None:
                url_keyword = next(
                    (keyword for keyword in node.keywords if keyword.arg == "url"),
                    None,
                )
                url_node = url_keyword.value if url_keyword is not None else None
            url = (
                _literal(url_node, bindings, node.lineno)
                if url_node is not None
                else _UNRESOLVED
            )
            is_http_request = (
                isinstance(url, str)
                and "api.anthropic.com/v1/messages" in url
            )
            if is_http_request:
                payload_keyword = next(
                    (keyword for keyword in node.keywords if keyword.arg == "json"),
                    None,
                )
                if payload_keyword is not None:
                    http_payload = _literal(
                        payload_keyword.value, bindings, node.lineno
                    )
        if not is_sdk_request and not is_http_request:
            continue
        if is_http_request:
            if isinstance(http_payload, dict):
                hits.update(
                    _request_conflicts(
                        http_payload.get("model", _UNRESOLVED), http_payload
                    )
                )
            else:
                hits.add("unresolved Anthropic HTTP request payload")
            continue
        params: dict[str, object] = {}
        for keyword in node.keywords:
            value = _literal(keyword.value, bindings, node.lineno)
            if keyword.arg is None:
                if isinstance(value, dict):
                    params.update(value)
                continue
            params[keyword.arg] = value
        hits.update(_request_conflicts(params.get("model", _UNRESOLVED), params))
    return hits, True


def _json_request_conflicts(block: str) -> tuple[set[str], bool]:
    try:
        value = json.loads(block)
    except (ValueError, TypeError):
        return set(), False

    hits: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, dict):
            if "model" in item:
                hits.update(_request_conflicts(item.get("model", _UNRESOLVED), item))
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return hits, True


def _model_api_incompatibilities(body: str) -> list[str]:
    """Return request-bound supported-model conflicts from executable examples."""
    hits: set[str] = set()
    for block in FENCED_CODE_RE.findall(body):
        python_hits, python_parsed = _python_request_conflicts(block)
        hits.update(python_hits)
        json_hits, json_parsed = _json_request_conflicts(block)
        hits.update(json_hits)
        if python_parsed or json_parsed:
            continue

        # Conservative fallback for other languages: exact covered-model blocks
        # remain checked, but request-level Python/JSON examples never use this
        # co-occurrence path.
        models = {model for model in RESTRICTED_API_MODEL_IDS if model in block}
        if not models:
            continue
        if SAMPLING_CONTROL_RE.search(block):
            hits.add("sampling parameters on a restricted Claude model")
        if MANUAL_THINKING_RE.search(block):
            hits.add("manual extended thinking on a restricted Claude model")
        for model in models & ALWAYS_THINKING_MODEL_IDS:
            if DISABLED_THINKING_RE.search(block):
                display = model.removeprefix("claude-").replace("-", " ").title()
                hits.add(f"disabled thinking on Claude {display}")
        if (
            "claude-opus-5" in models
            and DISABLED_THINKING_RE.search(block)
            and XHIGH_OR_MAX_EFFORT_RE.search(block)
        ):
            hits.add("disabled thinking with xhigh/max effort on Claude Opus 5")
    return sorted(hits)


# Real XML tag: attributes OR namespace OR a closing-tag form. Excludes CLI placeholders like
# <github-username> or <slug> which are universally used in argument-hint prose.
XML_TAG_RE = re.compile(r"</[A-Za-z]|<[A-Za-z][A-Za-z0-9_-]*\s+[^>]*>|<[A-Za-z]+:[A-Za-z]+")
TRIGGER_RE = re.compile(r"trigger phrase|trigger:|triggers on|invoke when|invoke this|use when|use this when|use before|use after|use during|use to drive", re.IGNORECASE)
DONT_RE = re.compile(r"do not use|don't use|do NOT|don't invoke|not for", re.IGNORECASE)
SECTION_RE = re.compile(r"^## ", re.MULTILINE)
STEPPED_RE = re.compile(
    r"^\s*\d+\.|"                          # "1." at line start
    r"^#+\s*(?:Step|Phase|Article|Check)\s*(?:\d+|[IVX]+)|"  # "## Step 1", "## ARTICLE V", "## Check 1"
    r"^###\s*\d+\.|"                       # "### 1." sub-header
    r"\b(?:Step|Phase|Check)\s+(?:\d+|0)\b",  # "Step 1" or "Phase 0" mid-line
    re.MULTILINE | re.IGNORECASE,
)
EXAMPLE_HEADER_RE = re.compile(r"^#{1,3}\s.*example", re.IGNORECASE | re.MULTILINE)
# Concrete example: ≥80 chars of content between an Example header and the next ## section
# (catches "Example 1: ..." blocks; rejects "## Examples\n## Next" empty-header cases).
USER_VOICE_RE = re.compile(r"\b(I |I'll|I'm|we |we'll|we're|you |your |you'll|you're)", re.IGNORECASE)
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESERVED = {"anthropic", "claude"}
REF_RE = re.compile(r"(?:`|\(|\s)references/([a-z0-9_/-]+\.md)")
WIN_PATH_RE = re.compile(r"references\\")


def parse_frontmatter(text: str):
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None, text
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None, text[m.end():]
    return fm, text[m.end():]


def score_skill(skill_dir: Path):
    skill_md = skill_dir / "SKILL.md"
    body = skill_md.read_text(encoding='utf-8')
    fm, body_only = parse_frontmatter(body)
    checks = {}
    notes = {}

    # A1: frontmatter parses + name + description
    if fm is None:
        checks = {k: False for k in (
            "A1_frontmatter", "A2_desc_format", "A3_third_person", "A4_trigger_domain",
            "A5_donot_clause", "A6_name_format",
            "B1_procedural", "B2_concrete_example", "B3_refs_clean",
            "C1_length", "C2_arg_hint", "C3_allowed_tools",
            "D1_evaluations",
        )}
        return checks, notes
    name = fm.get("name", "")
    desc = (fm.get("description") or "").strip()
    if isinstance(desc, dict):  # multi-line YAML can produce dict, defensive
        desc = str(desc)
    # when_to_use (Claude Code extension): appended to `description` in the skill
    # listing and read by the model for routing. Trigger phrases and the Do-NOT
    # clause may live here instead of in the (display-facing) description, so the
    # routing-signal checks A4/A5 evaluate the combined text, not `desc` alone.
    wtu = (fm.get("when_to_use") or "").strip()
    if isinstance(wtu, dict):
        wtu = str(wtu)
    routing_text = f"{desc}\n{wtu}".strip()
    checks["A1_frontmatter"] = bool(name) and bool(desc)

    # A2: current Claude Code listing truncates description + when_to_use at
    # 1,536 characters. Fail before the routing contract is silently cut.
    combined_listing = f"{desc} {wtu}".strip()
    desc_len_ok = 0 < len(desc) and len(combined_listing) <= 1536
    has_xml = bool(XML_TAG_RE.search(combined_listing))
    checks["A2_desc_format"] = desc_len_ok and not has_xml
    if not desc_len_ok:
        notes["A2"] = f"combined_len={len(combined_listing)}"
    elif has_xml:
        notes["A2"] = "contains XML tags"

    # A3: third-person — strip quoted strings first (trigger phrases legitimately quote user voice)
    desc_unquoted = re.sub(r'"[^"]*"', "", desc)        # strip "..."
    desc_unquoted = re.sub(r"'[^']*'", "", desc_unquoted)  # strip '...'
    user_hits = USER_VOICE_RE.findall(desc_unquoted)
    has_first = any(h.strip().lower() in ("i", "i'll", "i'm", "we", "we'll", "we're") for h in user_hits)
    has_second = any("you" in h.lower() for h in user_hits)
    checks["A3_third_person"] = not (has_first or has_second)
    if has_first or has_second:
        notes["A3"] = f"hits={user_hits[:3]}"

    # A4: trigger phrases + domain (description and/or when_to_use)
    checks["A4_trigger_domain"] = bool(TRIGGER_RE.search(routing_text))

    # A5: Do-NOT clause (description and/or when_to_use)
    checks["A5_donot_clause"] = bool(DONT_RE.search(routing_text))

    # A6: name format
    # Documented exceptions: the gather-* upstream-sync family names the vendor it
    # syncs FROM, so the reserved word is load-bearing rather than incidental —
    # `gather-claude` (Claude Code product surface) and `gather-claude-endpoints`
    # (Anthropic's data-collection surface). Both are surfaced in healthcheck.
    EXEMPT_NAMES = {"gather-claude", "gather-claude-endpoints"}
    name_ok = (
        bool(name)
        and len(name) <= 64
        and bool(NAME_RE.match(name))
        and (name in EXEMPT_NAMES
             or (name not in RESERVED
                 and not any(tok in name.lower() for tok in RESERVED)))
    )
    checks["A6_name_format"] = name_ok
    if not name_ok:
        notes["A6"] = f"name={name!r}"

    # B1: procedural structure — scale requirements to body length
    sections = SECTION_RE.findall(body_only)
    stepped = STEPPED_RE.findall(body_only)
    body_lines = len(body_only.splitlines())
    if body_lines < 60:
        # Short utility skills: just need ≥1 section or ≥1 step (the body itself IS the procedure)
        checks["B1_procedural"] = len(sections) >= 1 or len(stepped) >= 1
    elif body_lines < 150:
        # Medium skills: ≥2 sections OR ≥2 steps
        checks["B1_procedural"] = len(sections) >= 2 or len(stepped) >= 2
    else:
        # Long skills: ≥3 sections AND ≥3 steps (multi-phase orchestration)
        checks["B1_procedural"] = len(sections) >= 3 and len(stepped) >= 3

    # B2: concrete example — ≥80 chars of content between Example header and next ##
    # For short skills (<60 body lines), the body itself is the worked example.
    m = EXAMPLE_HEADER_RE.search(body_only)
    if m:
        rest = body_only[m.end():]
        next_section = SECTION_RE.search(rest)
        block = rest[: next_section.start()] if next_section else rest
        checks["B2_concrete_example"] = len(block.strip()) >= 80
    elif body_lines < 60:
        # Short skills: the whole body counts as the example if it has a code block
        checks["B2_concrete_example"] = "```" in body_only
    else:
        # Long skills without an Example header: also accept inline "Worked example" / "Example 1" markers
        worked = re.search(r"(worked example|example (?:1|invocation|usage|prompt))", body_only, re.IGNORECASE)
        checks["B2_concrete_example"] = bool(worked)

    # B3: refs resolve, ≤1 deep, no windows paths
    # Strip fenced code blocks first — refs inside ``` ... ``` are example/documentation, not real cites
    body_no_code = re.sub(r"```.*?```", "", body_only, flags=re.DOTALL)
    refs = set(REF_RE.findall(body_no_code))
    refs_dir = skill_dir / "references"
    existing = set()
    if refs_dir.exists():
        for f in refs_dir.rglob("*"):
            if f.is_file():
                rel = f.relative_to(refs_dir)
                existing.add(str(rel).replace("\\", "/"))
    # Filter out sibling-skill cross-refs (those with skill-name/references/file.md pattern)
    sibling_re = re.compile(r"`([a-z][a-z0-9_-]*)/references/[a-z0-9_-]+\.md`")
    sibling_refs = set(sibling_re.findall(body_only))
    local_refs = {r for r in refs if not any(r.startswith(s + "/") for s in sibling_refs)}
    # Drop any ref that's actually cited via a sibling path
    for r in list(local_refs):
        sib_path = re.compile(r"`[a-z][a-z0-9_-]*/" + re.escape(r) + r"`")
        if sib_path.search(body_only):
            local_refs.discard(r)
    missing = [r for r in local_refs if r not in existing]
    too_deep = [r for r in local_refs if r.count("/") > 1]
    has_winpath = bool(WIN_PATH_RE.search(body_only))
    checks["B3_refs_clean"] = not missing and not too_deep and not has_winpath
    if missing:
        notes["B3"] = f"missing={missing[:3]}"
    elif too_deep:
        notes["B3"] = f"depth>1={too_deep[:3]}"

    # C1: length
    line_count = len(body.splitlines())
    checks["C1_length"] = line_count <= 510
    if line_count > 510:
        notes["C1"] = f"{line_count} lines"

    # C2: argument-hint quality (if declared)
    hint = fm.get("argument-hint", "")
    if hint is None:
        hint = ""
    hint = str(hint).strip()
    if not hint:
        checks["C2_arg_hint"] = True  # not declared = no requirement
    else:
        checks["C2_arg_hint"] = len(hint) > 15

    # D1: evaluations — size-aware threshold matching Anthropic spirit.
    # Anthropic: "Create evaluations BEFORE writing extensive documentation."
    # Short utility skills (<60 body lines) have minimal "extensive documentation",
    # so 1 eval suffices. Medium skills need 2; long skills need ≥3.
    #
    # FAST-PATH: if a skill has a tests/<skill>/*.yaml file containing a
    # `deterministic:` block, treat that as full D1 credit regardless of
    # documentation-marker count. Runnable deterministic evals are a strictly
    # stronger signal than documentation markers; see scripts/run-skill-evals.py.
    has_runnable_evals = False
    tests_dir_for_runnable = Path("tests") / skill_dir.name
    if tests_dir_for_runnable.is_dir():
        for yaml_path in list(tests_dir_for_runnable.glob("*.yaml")) + list(tests_dir_for_runnable.glob("*.yml")):
            try:
                eval_data = yaml.safe_load(yaml_path.read_text(encoding='utf-8'))
                if isinstance(eval_data, dict) and eval_data.get("deterministic"):
                    has_runnable_evals = True
                    break
            except yaml.YAMLError:
                pass
    eval_count = 0
    # Source 1: tests/<skill>/ directory with files
    tests_dir = Path("tests") / skill_dir.name
    if tests_dir.is_dir():
        eval_count += sum(1 for f in tests_dir.iterdir() if f.is_file() and f.suffix in (".md", ".json", ".yaml", ".yml"))
    # Source 2: references/eval*.md and known existing-convention files
    if refs_dir.exists():
        eval_files = list(refs_dir.glob("eval*.md")) + list(refs_dir.glob("*evaluation*.md"))
        for fname in ("examples-and-evals.md", "evaluation-prompts.md", "evals-and-metrics.md", "examples.md"):
            f = refs_dir / fname
            if f.is_file() and f not in eval_files:
                eval_files.append(f)
        for ef in eval_files:
            try:
                content = ef.read_text(encoding='utf-8')
                eval_count += len(re.findall(r"(?:^|\n)#{1,3}\s+(?:Eval|Example|Test|Case)\s*\d", content, re.IGNORECASE))
            except Exception:
                pass
    # Source 3 (SKILL.md) — broader pattern covering common conventions:
    #   ## Example, ### Example 1, **Example 1:, **Example:, "> User: /command",
    #   inline "/skill-name <args>" invocations (often inside code fences),
    #   bold-quoted user questions ("**\"Where's X?\"**"),
    #   demonstrative blocks within an Examples section (bold-prefix paragraphs).
    skill_command = "/" + skill_dir.name

    def _count_evals(text: str) -> int:
        n = 0
        n += len(re.findall(r"(?:^|\n)#{1,3}\s+(?:Eval|Example|Test|Case|Worked|Scenario)\b", text, re.IGNORECASE))
        n += len(re.findall(r"\*\*(?:Eval|Example|Test|Case|Worked|Scenario)[^*]*\*\*", text, re.IGNORECASE))
        # "> User: /skill-name args" — quoted user-voice invocation
        n += len(re.findall(r"^>\s*(?:User|Operator|You):\s*/", text, re.MULTILINE))
        # Direct invocation of this skill's command — count distinct lines
        # containing /skill-name (e.g., "User: /skill-name args" or bare line in code block).
        invocation_lines = {line for line in text.splitlines() if skill_command in line}
        n += len(invocation_lines)
        # Bold-quoted user questions: **"..."** at line start (code-explore style)
        n += len(re.findall(r'^\*\*"[^"]+"\*\*', text, re.MULTILINE))
        # Demonstrative blocks within an Examples section: bold-prefix paragraphs
        # like **New workspace:** or **Production deploy:** that introduce a scenario.
        ex_match = re.search(r"^#{1,3}\s+Examples?\b", text, re.IGNORECASE | re.MULTILINE)
        if ex_match:
            after_examples = text[ex_match.end():]
            # Stop at next ## section
            next_section = re.search(r"^##\s+(?!Example)", after_examples, re.MULTILINE)
            ex_block = after_examples[: next_section.start()] if next_section else after_examples
            # Count bold-prefix paragraphs ("**Name:**" or "**\"Q?\"**" at line start)
            block_starts = re.findall(r"^\*\*[^*\n]+\*\*", ex_block, re.MULTILINE)
            # Subtract already-counted "Example N:" bold markers (avoid double-counting)
            already = re.findall(r"^\*\*(?:Eval|Example|Test|Case|Worked|Scenario)[^*]*\*\*",
                                 ex_block, re.IGNORECASE | re.MULTILINE)
            n += max(0, len(block_starts) - len(already))
        return n
    eval_count += _count_evals(body_only)
    # Also re-scan eval files in references (Source 2 only counted numbered headers)
    if refs_dir.exists():
        for f in refs_dir.glob("*.md"):
            fname = f.name.lower()
            if "example" in fname or "eval" in fname or "test" in fname:
                try:
                    eval_count += _count_evals(f.read_text(encoding='utf-8'))
                except Exception:
                    pass
    # Size-aware threshold
    body_lines_now = len(body_only.splitlines())
    if body_lines_now < 60:
        required = 1
    elif body_lines_now < 150:
        required = 2
    else:
        required = 3
    if has_runnable_evals:
        checks["D1_evaluations"] = True
        notes["D1"] = "runnable-evals-present"
    else:
        checks["D1_evaluations"] = eval_count >= required
        if eval_count < required:
            notes["D1"] = f"found={eval_count}, need≥{required}"

    # C1b: compaction continuity. Claude Code initially loads the rendered body,
    # then reattaches only the first 5,000 tokens of each invoked skill after
    # compaction (25,000 combined, newest-first). chars/4 is deliberately a
    # conservative structural proxy, not a target-model tokenizer claim. Bodies
    # above 4,000 proxy tokens need an early recovery contract so a session does
    # not silently continue after losing tail instructions.
    body_proxy = (len(body) + 3) // 4
    compaction_marker = "**Compaction continuity:**"
    early_body = body[:20_000]
    marker_position = early_body.find(compaction_marker)
    recovery_window = (
        early_body[marker_position : marker_position + 1200]
        if marker_position >= 0
        else ""
    )
    recovery_is_actionable = (
        bool(re.search(r"\bre-invoke\b", recovery_window, re.IGNORECASE))
        and bool(re.search(r"\bstop and ask\b", recovery_window, re.IGNORECASE))
    )
    intentionally_inert = (
        fm.get("disable-model-invocation") is True
        and fm.get("user-invocable") is False
    )
    checks["C1b_token_budget"] = (
        body_proxy <= 4000 or recovery_is_actionable or intentionally_inert
    )
    if body_proxy > 4000 and not intentionally_inert:
        notes["C1b"] = (
            f"body_proxy={body_proxy}; "
            + (
                "early compaction recovery contract present"
                if recovery_is_actionable
                else "missing actionable early compaction recovery contract"
            )
        )

    # E1: model-aware API compatibility (keeps the historical check key for
    # report/CI compatibility). Only exact covered-model examples are checked;
    # controls used by an older model or a non-Anthropic API are not globally
    # prohibited.
    incompatible_hits = _model_api_incompatibilities(body)
    checks["E1_no_deprecated_api"] = not incompatible_hits
    if incompatible_hits:
        notes["E1"] = f"hits={incompatible_hits[:3]}"

    # M5: C3 (allowed-tools) moves to INFORMATIONAL. The check still runs but
    # does not count toward the score; ~17/17 of Anthropic's own published
    # canonical skills fail this, so it's an over-strict gate. Recorded in
    # notes as informational; not in `checks`.
    if not fm.get("allowed-tools"):
        notes["I1"] = "no allowed-tools field (informational; Claude Code extension)"

    # I2 (H3): verified_on field — informational. Skills with a verified_on
    # YYYY-MM-DD field that's <=90 days old don't show the warning; missing
    # or stale produces an advisory note.
    verified_on = fm.get("verified_on", "")
    if not verified_on:
        notes["I2"] = "no verified_on field (informational; recommended for vendor-backed guidance)"
    else:
        try:
            from datetime import date, datetime
            d = datetime.strptime(str(verified_on), "%Y-%m-%d").date()
            age = (date.today() - d).days
            if age > 90:
                notes["I2"] = f"verified_on={verified_on} (age={age}d > 90d)"
        except (ValueError, TypeError):
            notes["I2"] = f"verified_on={verified_on!r} not parseable as YYYY-MM-DD"

    return checks, notes


def grade(score: int) -> str:
    if score >= 14: return "S"
    if score >= 13: return "A"
    if score >= 12: return "A-"
    if score >= 11: return "B+"
    if score >= 10: return "B"
    if score >= 9:  return "B-"
    if score >= 8:  return "C+"
    return "C"


def _normalize_phrase(p):
    """Normalize a trigger phrase for exact and near-overlap detection."""
    p = p.lower().strip()
    # Strip punctuation and collapse whitespace
    p = re.sub(r"[^\w\s/-]+", " ", p)
    p = re.sub(r"\s+", " ", p).strip()
    return p


def _phrase_tokens(p):
    """Extract content tokens (≥3 chars) for overlap-detection."""
    return frozenset(t for t in re.split(r"[\s/-]+", _normalize_phrase(p)) if len(t) >= 3)


def trigger_conflict_scan(results, mode="strict"):
    """Corpus-level trigger-phrase conflict scan.

    Modes:
      'lenient' — only flag exact phrase matches
      'strict'  — also flag overlaps where two skills share ≥2 content
                  tokens between their trigger phrases (default)
    """
    trigger_list_re = re.compile(
        r"(?:Trigger phrases?|Triggers? on|Triggers?)\b[^.]*?:(.{1,500})",
        re.IGNORECASE | re.DOTALL,
    )
    phrase_re = re.compile(r'"([^"]{4,60})"|\'([^\']{4,60})\'')

    # First pass: collect each skill's trigger phrases
    skill_phrases = {}  # skill -> set of (raw, normalized, tokens)
    for r in results:
        desc = r.get("description", "")
        phrases = set()
        for trigger_block in trigger_list_re.findall(desc):
            cutoff = re.search(r"\.\s+[A-Z]|Do NOT|Do not\b", trigger_block)
            block = trigger_block[: cutoff.start()] if cutoff else trigger_block
            for m_pair in phrase_re.findall(block):
                m = next((x for x in m_pair if x), "")
                if not m:
                    continue
                norm = _normalize_phrase(m)
                if not norm or norm == r["skill"] or norm == r["skill"].replace("-", " "):
                    continue
                if norm.startswith("--"):
                    continue
                phrases.add((m, norm, _phrase_tokens(m)))
        if phrases:
            skill_phrases[r["skill"]] = phrases

    # Exact-match conflicts
    exact = defaultdict(set)
    for skill, phrases in skill_phrases.items():
        for _raw, norm, _toks in phrases:
            exact[norm].add(skill)
    exact_conflicts = {p: sorted(s) for p, s in exact.items() if len(s) > 1}

    if mode == "lenient":
        return {"exact": exact_conflicts, "overlap": {}}

    # Strict mode: also flag ≥2-token overlaps across different skills' phrases
    overlap_conflicts = {}
    skills = list(skill_phrases.keys())
    for i in range(len(skills)):
        for j in range(i + 1, len(skills)):
            s1, s2 = skills[i], skills[j]
            for _r1, n1, t1 in skill_phrases[s1]:
                for _r2, n2, t2 in skill_phrases[s2]:
                    if n1 == n2:
                        continue  # already in exact
                    shared = t1 & t2
                    if len(shared) >= 2:
                        # Skip very common content tokens that don't disambiguate
                        if shared <= {"use", "the", "for", "from", "with", "and", "this"}:
                            continue
                        key = f"{n1!r} ↔ {n2!r}"
                        overlap_conflicts.setdefault(key, set()).update([s1, s2])

    return {
        "exact": exact_conflicts,
        "overlap": {k: sorted(v) for k, v in overlap_conflicts.items()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", help="Detail for one skill")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--below", type=int, default=13, help="Only show skills scoring below N")
    ap.add_argument("--fails", help="Only show skills failing this specific check (e.g., A5)")
    ap.add_argument("--triggers", action="store_true", help="Run trigger-conflict scan")
    ap.add_argument(
        "--gate",
        type=int,
        metavar="MIN",
        help=(
            "CI GATE: exit 1 if any skill scores below MIN. Without this, the "
            "script always exits 0 and a caller must build its own shell "
            "conditional -- which is how the CI gate ended up fail-open "
            "(audit finding M4). Prefer `--gate 13` over an `if` in YAML."
        ),
    )
    args = ap.parse_args()

    results = []
    skills_root = Path("skills")
    for skill_dir in sorted(skills_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        if skill_dir.name.startswith("_"):
            continue
        if not (skill_dir / "SKILL.md").exists():
            continue
        if args.skill and skill_dir.name != args.skill:
            continue
        checks, notes = score_skill(skill_dir)
        score = sum(checks.values())
        # Capture description for trigger-conflict scan
        body = (skill_dir / "SKILL.md").read_text(encoding='utf-8')
        fm, _ = parse_frontmatter(body)
        desc = ""
        if fm:
            desc = (fm.get("description") or "").strip()
            # triggers may live in when_to_use; scan the combined text so the
            # trigger-conflict detector doesn't go blind after the description split
            wtu = (fm.get("when_to_use") or "").strip()
            if isinstance(wtu, dict):
                wtu = str(wtu)
            if wtu:
                desc = f"{desc}\n{wtu}".strip()
        results.append({
            "skill": skill_dir.name,
            "score": score,
            "grade": grade(score),
            "checks": checks,
            "notes": notes,
            "fails": [k for k, v in checks.items() if not v],
            "description": desc,
        })

    # --- CI GATE (audit finding M4) -------------------------------------------
    # Computed here, BEFORE the display branches, so every output mode honours it.
    # `main` returns this code and `__main__` passes it to sys.exit, so the gate
    # cannot be lost to an early `return` in one of the report modes.
    #
    # WHY a flag rather than a shell conditional: the workflow previously wrapped a
    # checker in `if <checker>; then echo ok; fi` with no `else`. In Bash a false
    # `if` condition with no `else` leaves the compound command SUCCESSFUL, so a
    # real below-threshold skill printed `::error::` and the step still exited 0 --
    # the required gate could not fail. Reproduced 2026-07-26: search-campaign
    # scored 12/14 while CI was green. Exit codes belong to the tool, not to YAML.
    gate_rc = 0
    if args.gate is not None:
        offenders = sorted(
            (r for r in results if r["score"] < args.gate),
            key=lambda r: (r["score"], r["skill"]),
        )
        for r in offenders:
            print(
                f"::error::{r['skill']} score={r['score']}/14 "
                f"(gate is {args.gate}) fails={','.join(r['fails'])}"
            )
        if offenders:
            print(
                f"\nGATE FAILED: {len(offenders)} skill(s) below {args.gate}/14.",
                file=sys.stderr,
            )
            gate_rc = 1
        else:
            print(f"GATE PASSED: all {len(results)} skills >= {args.gate}/14.")

    if args.json:
        for r in results:
            r.pop("description", None)
        print(json.dumps(results, indent=2))
        return gate_rc

    if args.skill:
        for r in results:
            print(f"\n{r['skill']}  score={r['score']}/14  grade={r['grade']}")
            for k, v in r["checks"].items():
                mark = "✓" if v else "✗"
                note = f"  ({r['notes'][k.split('_')[0]]})" if k.split("_")[0] in r["notes"] else ""
                print(f"  {mark} {k}{note}")
        return gate_rc

    if args.triggers:
        result = trigger_conflict_scan(results, mode="strict")
        exact = result["exact"]
        overlap = result["overlap"]
        if not exact and not overlap:
            print("No trigger-phrase conflicts found in descriptions (strict mode).")
        else:
            if exact:
                print(f"=== Exact trigger-phrase conflicts (n={len(exact)}) ===")
                for phrase, skills in sorted(exact.items()):
                    print(f"  '{phrase}' → {skills}")
            if overlap:
                print(f"\n=== Near-overlap conflicts (≥2 shared content tokens) (n={len(overlap)}) ===")
                for pair, skills in sorted(overlap.items()):
                    print(f"  {pair} → {skills}")
        return gate_rc

    if args.fails:
        # Filter to skills failing the named check
        matching_check_keys = [k for k in results[0]["checks"].keys() if args.fails in k]
        if not matching_check_keys:
            print(f"No check matches '{args.fails}'. Available:")
            for k in results[0]["checks"].keys():
                print(f"  {k}")
            return gate_rc
        ck = matching_check_keys[0]
        failing = [r for r in results if not r["checks"][ck]]
        print(f"=== Skills failing {ck} (n={len(failing)}) ===")
        for r in failing:
            note = r["notes"].get(ck.split("_")[0], "")
            print(f"  {r['grade']:<4} {r['skill']:<35} {note}")
        return gate_rc

    # Tabular: sort by score asc, then name
    results.sort(key=lambda r: (r["score"], r["skill"]))
    shown = [r for r in results if r["score"] < args.below]
    if shown:
        print(f"{'Score':<7} {'Grade':<6} {'Skill':<32} Fails")
        print("-" * 100)
        for r in shown:
            print(f"{r['score']}/14   {r['grade']:<6} {r['skill']:<32} {','.join(r['fails'])}")

    print(f"\n--- Distribution (n={len(results)}) ---")
    by_grade = Counter(r["grade"] for r in results)
    for g in ["S", "A", "A-", "B+", "B", "B-", "C+", "C"]:
        if g in by_grade:
            print(f"  {g:<3}: {by_grade[g]}")

    # Per-check failure histogram
    print("\n--- Per-check failure histogram ---")
    check_fails = Counter()
    for r in results:
        for k, v in r["checks"].items():
            if not v:
                check_fails[k] += 1
    for k, n in sorted(check_fails.items(), key=lambda x: -x[1]):
        print(f"  {k:<22} {n:3d} skills failing")

    # The default tabular path must ALSO honour the gate. Falling off the end of
    # main() returns None -> exit 0, which would have reproduced the very
    # fail-open behaviour this flag exists to fix (caught in verification: the
    # gate printed "GATE FAILED" and still exited 0).
    return gate_rc


if __name__ == "__main__":
    raise SystemExit(main())
