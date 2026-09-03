#!/usr/bin/env python3
"""Build self-contained plugin bundles from source files.

Reads PLUGIN_MANIFEST below, copies files into marketplace/<plugin>/,
creates .claude-plugin/plugin.json for each, and writes the root
.claude-plugin/marketplace.json.

Run before publishing:
    python scripts/build-marketplace.py

Source files stay in their original locations. This script assembles
read-only copies for the plugin marketplace. Edit the originals, not
the marketplace/ output.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent
MARKETPLACE_DIR = CLAUDE_DIR / "marketplace"
MARKETPLACE_NAME = "claude-harness"
PLUGIN_AUTHOR = {
    "name": "Brandyn Schult",
    "url": "https://github.com/brandyn-s",
}
MARKETPLACE_OWNER = PLUGIN_AUTHOR


def _plugin_hook(script: str, timeout: int) -> dict:
    """Build a cross-platform command handler for a bundled Python hook."""
    return {
        "type": "command",
        "command": "bash",
        "args": [
            "${CLAUDE_PLUGIN_ROOT}/hooks/run-hook",
            script,
        ],
        "timeout": timeout,
    }


def _hook_group(script: str, timeout: int, matcher: str = "") -> dict:
    """Build one hook matcher group, omitting matcher for global events."""
    group = {"hooks": [_plugin_hook(script, timeout)]}
    if matcher:
        group["matcher"] = matcher
    return group


# ── Plugin definitions ────────────────────────────────────────────────
# Each plugin: name, description, version, and a list of (src, dest) pairs.
# src is relative to CLAUDE_DIR, dest is relative to the plugin root.

PLUGINS = [
    {
        "name": "safety-net",
        "description": "Minimal deterministic safety hooks for Claude Code — Bash command safety, protected-config integrity, and MCP result-injection detection. Additional policy and observation hooks remain opt-in.",
        "version": "1.1.0",
        "hooks": {
            "PreToolUse": [
                _hook_group("bash-security-guard.py", 30, "Bash"),
                _hook_group("config-guard.py", 30, "Write|Edit"),
            ],
            "PostToolUse": [
                _hook_group("result-injection-guard.py", 30, "mcp__.*"),
            ],
        },
        "files": [
            # Hooks
            ("hooks/run-hook", "hooks/run-hook"),
            ("hooks/loop-detector.py", "hooks/loop-detector.py"),
            ("hooks/result-injection-guard.py", "hooks/result-injection-guard.py"),
            ("hooks/bash-security-guard.py", "hooks/bash-security-guard.py"),
            ("hooks/bash_policy_tables.py", "hooks/bash_policy_tables.py"),
            ("hooks/bash-error-classifier.py", "hooks/bash-error-classifier.py"),
            ("hooks/config-guard.py", "hooks/config-guard.py"),
            ("hooks/block-partial-read.py", "hooks/block-partial-read.py"),
            ("hooks/memory-write-guard.py", "hooks/memory-write-guard.py"),
            ("hooks/search-path-guard.py", "hooks/search-path-guard.py"),
            ("hooks/post-write-edit.py", "hooks/post-write-edit.py"),
            ("hooks/post-failure-guide.py", "hooks/post-failure-guide.py"),
            ("hooks/protected-repos.json", "hooks/protected-repos.json"),
            # Shared libraries imported by the bundled hooks (must ship so the
            # plugin is self-contained): result-injection-guard imports
            # hook_input; loop-detector imports atomic_write;
            # bash-security-guard imports manifest_metrics for the
            # repeat-block escalation and bash_policy_tables for opt-in
            # non-catastrophic command policy.
            ("hooks/hook_input.py", "hooks/hook_input.py"),
            ("hooks/atomic_write.py", "hooks/atomic_write.py"),
            ("hooks/manifest_metrics.py", "hooks/manifest_metrics.py"),
            # Root rules/ are standalone configuration, not a recognized
            # plugin component. They remain available through install.sh and
            # manual copy; do not ship inert files in the cached plugin.
            # Hook and proxy guardrail management skills
            ("skills/ship-hook/SKILL.md", "skills/ship-hook/SKILL.md"),
            ("skills/guardrail/SKILL.md", "skills/guardrail/SKILL.md"),
            # Session context management
            ("skills/context-budget/SKILL.md", "skills/context-budget/SKILL.md"),
        ],
    },
    {
        "name": "planning-toolkit",
        "description": "Design-before-code and ship-safely workflow skills — architecture planning, adversarial review, prompt refinement, companions to the superpowers plugin for evidence-first design, hypothesis-driven debugging, legacy-code TDD and risk-tiered review, ship/PR lifecycle, PR cleanup, Claude API guardrails, and bulk scripting.",
        "version": "1.1.0",
        "files": [
            ("skills/superplan/SKILL.md", "skills/superplan/SKILL.md"),
            ("skills/superplan/references/examples.md", "skills/superplan/references/examples.md"),
            ("skills/supergoal/SKILL.md", "skills/supergoal/SKILL.md"),
            ("skills/supergoal/scripts/parse_plan.py", "skills/supergoal/scripts/parse_plan.py"),
            ("skills/supergoal/scripts/check_prior_arcs.py", "skills/supergoal/scripts/check_prior_arcs.py"),
            ("skills/supergoal/scripts/write_terminal.py", "skills/supergoal/scripts/write_terminal.py"),
            ("skills/supergoal/scripts/state_io.py", "skills/supergoal/scripts/state_io.py"),
            ("skills/supergoal/references/plan-parsing.md", "skills/supergoal/references/plan-parsing.md"),
            ("skills/supergoal/references/verification-hook.md", "skills/supergoal/references/verification-hook.md"),
            ("skills/supergoal/references/prior-arc-check.md", "skills/supergoal/references/prior-arc-check.md"),
            ("skills/supergoal/references/budget.md", "skills/supergoal/references/budget.md"),
            ("skills/supergoal/references/terminal-doc.md", "skills/supergoal/references/terminal-doc.md"),
            ("skills/supergoal/references/headless.md", "skills/supergoal/references/headless.md"),
            ("skills/supergoal/references/plan-pattern-library.md", "skills/supergoal/references/plan-pattern-library.md"),
            ("skills/supergoal-pause/SKILL.md", "skills/supergoal-pause/SKILL.md"),
            ("skills/supergoal-resume/SKILL.md", "skills/supergoal-resume/SKILL.md"),
            ("skills/superplan-status/SKILL.md", "skills/superplan-status/SKILL.md"),
            ("skills/superplan-loop/SKILL.md", "skills/superplan-loop/SKILL.md"),
            ("skills/interview/SKILL.md", "skills/interview/SKILL.md"),
            # Companions to the installed superpowers plugin (forks removed 2026-09-03)
            ("skills/design-evidence-first/SKILL.md", "skills/design-evidence-first/SKILL.md"),
            ("skills/debugging-hypotheses/SKILL.md", "skills/debugging-hypotheses/SKILL.md"),
            ("skills/legacy-code-tdd/SKILL.md", "skills/legacy-code-tdd/SKILL.md"),
            ("skills/review-depth-by-risk/SKILL.md", "skills/review-depth-by-risk/SKILL.md"),
            ("skills/refine/SKILL.md", "skills/refine/SKILL.md"),
            # Ship / PR / debug workflow
            ("skills/ship/SKILL.md", "skills/ship/SKILL.md"),
            ("skills/pr-fix/SKILL.md", "skills/pr-fix/SKILL.md"),
            ("skills/pr-fix/references/branch-cleanup.md", "skills/pr-fix/references/branch-cleanup.md"),
            ("skills/pr-fix/references/commit-ci-fix.md", "skills/pr-fix/references/commit-ci-fix.md"),
            ("skills/pr-fix/references/conflict-rebase.md", "skills/pr-fix/references/conflict-rebase.md"),
            ("skills/pr-fix/references/examples.md", "skills/pr-fix/references/examples.md"),
            ("skills/pr-fix/references/iterate-mode.md", "skills/pr-fix/references/iterate-mode.md"),
            ("skills/pr-fix/references/review-triage.md", "skills/pr-fix/references/review-triage.md"),
            ("skills/pr-fix/references/diagnose.md", "skills/pr-fix/references/diagnose.md"),
            ("skills/pr-fix/references/dirty-tree-discovery.md", "skills/pr-fix/references/dirty-tree-discovery.md"),
            ("skills/pr-fix/references/worktree-cleanup.md", "skills/pr-fix/references/worktree-cleanup.md"),
            # Claude API / bulk scripting
            ("skills/api-guardrails/SKILL.md", "skills/api-guardrails/SKILL.md"),
            ("skills/api-guardrails/references/prompt-diagnostic.md", "skills/api-guardrails/references/prompt-diagnostic.md"),
            ("skills/bulk-api-script/SKILL.md", "skills/bulk-api-script/SKILL.md"),
            ("skills/outlook-capability-intake/SKILL.md", "skills/outlook-capability-intake/SKILL.md"),
            # Per-session worktree isolation
            ("skills/work/SKILL.md", "skills/work/SKILL.md"),
        ],
    },
    {
        "name": "security-scanner",
        "description": "Static analysis, threat modeling, compliance, and breach response — Semgrep, CodeQL, false positive verification, differential review, threat modeling, STIG/SRG assessment and verification, dependabot triage, and vendor breach response.",
        "version": "1.1.0",
        "files": [
            ("skills/semgrep/SKILL.md", "skills/semgrep/SKILL.md"),
            ("skills/codeql/SKILL.md", "skills/codeql/SKILL.md"),
            ("skills/fp-check/SKILL.md", "skills/fp-check/SKILL.md"),
            ("skills/differential-review/SKILL.md", "skills/differential-review/SKILL.md"),
            ("skills/insecure-defaults/SKILL.md", "skills/insecure-defaults/SKILL.md"),
            ("skills/sharp-edges/SKILL.md", "skills/sharp-edges/SKILL.md"),
            ("skills/variant-analysis/SKILL.md", "skills/variant-analysis/SKILL.md"),
            ("skills/sarif-parsing/SKILL.md", "skills/sarif-parsing/SKILL.md"),
            ("skills/agentic-actions-auditor/SKILL.md", "skills/agentic-actions-auditor/SKILL.md"),
            ("skills/triage/SKILL.md", "skills/triage/SKILL.md"),
            ("skills/semgrep-rule-creator/SKILL.md", "skills/semgrep-rule-creator/SKILL.md"),
            ("skills/verify-search-result/SKILL.md", "skills/verify-search-result/SKILL.md"),
            # Reference files for existing skills
            ("skills/fp-check/references/standard-verification.md", "skills/fp-check/references/standard-verification.md"),
            ("skills/fp-check/references/false-positive-patterns.md", "skills/fp-check/references/false-positive-patterns.md"),
            ("skills/codeql/references/language-details.md", "skills/codeql/references/language-details.md"),
            ("skills/codeql/references/ruleset-catalog.md", "skills/codeql/references/ruleset-catalog.md"),
            ("skills/agentic-actions-auditor/references/foundations.md", "skills/agentic-actions-auditor/references/foundations.md"),
            ("skills/agentic-actions-auditor/references/action-profiles.md", "skills/agentic-actions-auditor/references/action-profiles.md"),
            # Agents used by security skills
            ("agents/data-flow-analyzer.md", "agents/data-flow-analyzer.md"),
            ("agents/exploitability-verifier.md", "agents/exploitability-verifier.md"),
            ("agents/poc-builder.md", "agents/poc-builder.md"),
            ("agents/semgrep-scanner.md", "agents/semgrep-scanner.md"),
            # Threat modeling / compliance / breach response
            ("skills/threat-model/SKILL.md", "skills/threat-model/SKILL.md"),
            ("skills/stig-assess/SKILL.md", "skills/stig-assess/SKILL.md"),
            ("skills/stig-assess/references/compensating-controls.md", "skills/stig-assess/references/compensating-controls.md"),
            ("skills/stig-assess/references/device-classification.md", "skills/stig-assess/references/device-classification.md"),
            ("skills/stig-assess/references/evidence-verification.md", "skills/stig-assess/references/evidence-verification.md"),
            ("skills/stig-assess/references/lateral-movement-caveat.md", "skills/stig-assess/references/lateral-movement-caveat.md"),
            ("skills/stig-assess/references/output-format.md", "skills/stig-assess/references/output-format.md"),
            ("skills/stig-assess/references/validate-artifacts.md", "skills/stig-assess/references/validate-artifacts.md"),
            ("skills/stig-verify/SKILL.md", "skills/stig-verify/SKILL.md"),
            ("skills/stig-verify/references/device-config-map.md", "skills/stig-verify/references/device-config-map.md"),
            ("skills/stig-verify/references/fix-templates.md", "skills/stig-verify/references/fix-templates.md"),
            ("skills/stig-verify/references/rag-conformance.md", "skills/stig-verify/references/rag-conformance.md"),
            ("skills/stig-verify/references/verdict-criteria.md", "skills/stig-verify/references/verdict-criteria.md"),
            ("skills/security-alerts/SKILL.md", "skills/security-alerts/SKILL.md"),
            ("skills/vendor-breach/SKILL.md", "skills/vendor-breach/SKILL.md"),
            ("skills/vendor-breach/references/audit-patterns-breach.md", "skills/vendor-breach/references/audit-patterns-breach.md"),
            ("skills/vendor-breach/references/audit-patterns-cve.md", "skills/vendor-breach/references/audit-patterns-cve.md"),
            ("skills/vendor-breach/references/breach-bulletin-schema.md", "skills/vendor-breach/references/breach-bulletin-schema.md"),
            ("skills/vendor-breach/references/comms-template.md", "skills/vendor-breach/references/comms-template.md"),
            ("skills/vendor-breach/references/ioc-multi-ecosystem-audit.md", "skills/vendor-breach/references/ioc-multi-ecosystem-audit.md"),
            ("skills/vendor-breach/references/report-template.md", "skills/vendor-breach/references/report-template.md"),
            ("skills/vendor-breach/references/vendor-library.yml", "skills/vendor-breach/references/vendor-library.yml"),
        ],
    },
    {
        "name": "knowledge-ops",
        "description": "Session knowledge, admin, and record-keeping — extract learnings, capture decisions, curate a knowledge base, retrospectives, review learnings, validate changes, healthchecks, claim verification, Claude and OpenAI monitoring/admin/cost, cross-provider AI monitoring, Linear status posting, Obsidian sync, workspace provisioning, weekly engineering updates, manifest generation, cross-tool investigation, and GitHub repo sync.",
        "version": "1.1.0",
        "files": [
            # Knowledge curation
            ("skills/distill/SKILL.md", "skills/distill/SKILL.md"),
            ("skills/distill/references/tier-decision-tree.md", "skills/distill/references/tier-decision-tree.md"),
            ("skills/distill/references/cross-cutting-audit.md", "skills/distill/references/cross-cutting-audit.md"),
            ("skills/recall/SKILL.md", "skills/recall/SKILL.md"),
            ("skills/garden/SKILL.md", "skills/garden/SKILL.md"),
            ("skills/garden/scripts/analyze.py", "skills/garden/scripts/analyze.py"),
            ("skills/garden/references/procedures.md", "skills/garden/references/procedures.md"),
            ("skills/harness-prune/SKILL.md", "skills/harness-prune/SKILL.md"),
            ("skills/harness-prune/scripts/scan_workarounds.py", "skills/harness-prune/scripts/scan_workarounds.py"),
            ("skills/retrospective/SKILL.md", "skills/retrospective/SKILL.md"),
            ("skills/review-learnings/SKILL.md", "skills/review-learnings/SKILL.md"),
            ("skills/validate-changes/SKILL.md", "skills/validate-changes/SKILL.md"),
            ("skills/healthcheck/SKILL.md", "skills/healthcheck/SKILL.md"),
            ("skills/healthcheck/references/check-9-orphans.md", "skills/healthcheck/references/check-9-orphans.md"),
            ("skills/healthcheck/references/skill-tier-checks.md", "skills/healthcheck/references/skill-tier-checks.md"),
            ("skills/capture/SKILL.md", "skills/capture/SKILL.md"),
            ("skills/capture/references/topic-format.md", "skills/capture/references/topic-format.md"),
            ("skills/retro/SKILL.md", "skills/retro/SKILL.md"),
            ("skills/retro/references/postmortem-templates.md", "skills/retro/references/postmortem-templates.md"),
            ("skills/mega-distill/SKILL.md", "skills/mega-distill/SKILL.md"),
            ("skills/mega-capture/SKILL.md", "skills/mega-capture/SKILL.md"),
            # Engineering methodology
            ("skills/plateau-diagnose/SKILL.md", "skills/plateau-diagnose/SKILL.md"),
            ("skills/build-measurement-harness/SKILL.md", "skills/build-measurement-harness/SKILL.md"),
            # Admin / platform monitoring / record-keeping
            ("skills/cc-monitor/SKILL.md", "skills/cc-monitor/SKILL.md"),
            ("skills/cc-monitor/references/routing-table.md", "skills/cc-monitor/references/routing-table.md"),
            ("skills/openai-monitor/SKILL.md", "skills/openai-monitor/SKILL.md"),
            ("skills/enterprise-ai-monitor/SKILL.md", "skills/enterprise-ai-monitor/SKILL.md"),
            ("skills/linear-status/SKILL.md", "skills/linear-status/SKILL.md"),
            ("skills/obsidian/SKILL.md", "skills/obsidian/SKILL.md"),
            ("skills/provision/SKILL.md", "skills/provision/SKILL.md"),
            ("skills/invite-to-workspace/SKILL.md", "skills/invite-to-workspace/SKILL.md"),
            ("skills/weekly-update/SKILL.md", "skills/weekly-update/SKILL.md"),
            ("skills/weekly-update/references/edge-cases.md", "skills/weekly-update/references/edge-cases.md"),
            ("skills/weekly-update/references/exemplar-brief.md", "skills/weekly-update/references/exemplar-brief.md"),
            ("skills/weekly-update/references/exemplar-mar1.md", "skills/weekly-update/references/exemplar-mar1.md"),
            ("skills/weekly-update/references/output-templates.md", "skills/weekly-update/references/output-templates.md"),
            ("skills/weekly-update/references/slack-queries.md", "skills/weekly-update/references/slack-queries.md"),
            ("skills/manifest-gen/SKILL.md", "skills/manifest-gen/SKILL.md"),
            ("skills/investigate/SKILL.md", "skills/investigate/SKILL.md"),
            ("skills/investigate/references/output-format.md", "skills/investigate/references/output-format.md"),
            ("skills/investigate/references/playbooks.md", "skills/investigate/references/playbooks.md"),
            ("skills/pull-repos/SKILL.md", "skills/pull-repos/SKILL.md"),
            # Architecture audit / cross-repo
            ("skills/audit-architecture/SKILL.md", "skills/audit-architecture/SKILL.md"),
            ("skills/audit-architecture/audit-context.md", "skills/audit-architecture/audit-context.md"),
            ("skills/audit-architecture/audit-suppress.yaml", "skills/audit-architecture/audit-suppress.yaml"),
            ("skills/audit-architecture/references/doc_accuracy_audit.py", "skills/audit-architecture/references/doc_accuracy_audit.py"),
            ("skills/audit-architecture/references/finding-codes.md", "skills/audit-architecture/references/finding-codes.md"),
            ("skills/audit-architecture/references/probe-targets.md", "skills/audit-architecture/references/probe-targets.md"),
            ("skills/audit-architecture/references/scoring-and-output.md", "skills/audit-architecture/references/scoring-and-output.md"),
            ("skills/audit-architecture/references/skill_quality_audit.py", "skills/audit-architecture/references/skill_quality_audit.py"),
            ("skills/audit-architecture/references/skill-quality-checklist.md", "skills/audit-architecture/references/skill-quality-checklist.md"),
            ("skills/audit-rules/SKILL.md", "skills/audit-rules/SKILL.md"),
            ("skills/audit-rules/references/classify_rules.py", "skills/audit-rules/references/classify_rules.py"),
            ("skills/audit-rules/references/scan_violations.py", "skills/audit-rules/references/scan_violations.py"),
            ("skills/audit-rules/references/lifecycle_check.py", "skills/audit-rules/references/lifecycle_check.py"),
            ("skills/cross-repo/SKILL.md", "skills/cross-repo/SKILL.md"),
        ],
    },
    {
        "name": "code-intelligence",
        "description": "Codebase exploration, analysis, API docs, and debugging — semantic search, structural graph queries, call chain tracing, dead code detection, Rust hierarchical documentation, MCP server diagnostics, API doc ingestion, and MCP forge (build/audit/deploy).",
        "version": "1.1.0",
        "files": [
            ("skills/code-explore/SKILL.md", "skills/code-explore/SKILL.md"),
            ("skills/code-explore/references/search-strategies.md", "skills/code-explore/references/search-strategies.md"),
            ("skills/codebase-memory-exploring/SKILL.md", "skills/codebase-memory-exploring/SKILL.md"),
            ("skills/codebase-memory-exploring/references/code-graph-reference.md", "skills/codebase-memory-exploring/references/code-graph-reference.md"),
            ("skills/codebase-memory-quality/SKILL.md", "skills/codebase-memory-quality/SKILL.md"),
            ("skills/codebase-memory-tracing/SKILL.md", "skills/codebase-memory-tracing/SKILL.md"),
            ("skills/index-repo/SKILL.md", "skills/index-repo/SKILL.md"),
            # Doc generation / MCP / API tooling
            ("skills/docgen/SKILL.md", "skills/docgen/SKILL.md"),
            ("skills/mcp-diagnose/SKILL.md", "skills/mcp-diagnose/SKILL.md"),
            ("skills/mcp-diagnose/scripts/analyze_startup.py", "skills/mcp-diagnose/scripts/analyze_startup.py"),
            ("skills/api-ingest/SKILL.md", "skills/api-ingest/SKILL.md"),
            ("skills/api-ingest/references/firecrawl-rate-limits.md", "skills/api-ingest/references/firecrawl-rate-limits.md"),
            ("skills/api-ingest/references/spec-probe-urls.md", "skills/api-ingest/references/spec-probe-urls.md"),
            ("skills/api-ingest/references/output-templates.md", "skills/api-ingest/references/output-templates.md"),
            ("skills/api-preflight/SKILL.md", "skills/api-preflight/SKILL.md"),
            # MCP forge (build / audit / deploy)
            ("skills/mcp-forge-build/SKILL.md", "skills/mcp-forge-build/SKILL.md"),
            ("skills/mcp-forge-build/references/colin-template.md", "skills/mcp-forge-build/references/colin-template.md"),
            ("skills/mcp-forge-build/references/opa-checklist.md", "skills/mcp-forge-build/references/opa-checklist.md"),
            ("skills/mcp-forge-build/references/server-template.md", "skills/mcp-forge-build/references/server-template.md"),
            ("skills/mcp-forge-build/references/spec-formats.md", "skills/mcp-forge-build/references/spec-formats.md"),
            ("skills/mcp-forge-build/references/spec-quality.md", "skills/mcp-forge-build/references/spec-quality.md"),
            ("skills/mcp-forge-build/references/tool-generation-rules.md", "skills/mcp-forge-build/references/tool-generation-rules.md"),
            ("skills/mcp-forge-build/references/verification-suite.md", "skills/mcp-forge-build/references/verification-suite.md"),
            ("skills/mcp-forge-audit/SKILL.md", "skills/mcp-forge-audit/SKILL.md"),
            ("skills/mcp-forge-audit/audit-context.md", "skills/mcp-forge-audit/audit-context.md"),
            ("skills/mcp-forge-audit/audit-suppress.yaml", "skills/mcp-forge-audit/audit-suppress.yaml"),
            ("skills/mcp-forge-audit/references/audit-modes.md", "skills/mcp-forge-audit/references/audit-modes.md"),
            ("skills/mcp-forge-audit/references/audit-report-format.md", "skills/mcp-forge-audit/references/audit-report-format.md"),
            ("skills/mcp-forge-audit/references/finding-codes.md", "skills/mcp-forge-audit/references/finding-codes.md"),
            ("skills/mcp-forge-audit/references/finding-definitions.md", "skills/mcp-forge-audit/references/finding-definitions.md"),
            ("skills/mcp-forge-audit/references/introspection-script.md", "skills/mcp-forge-audit/references/introspection-script.md"),
            ("skills/mcp-forge-audit/references/known-deviations.md", "skills/mcp-forge-audit/references/known-deviations.md"),
            ("skills/mcp-forge-audit/references/opa-checklist.md", "skills/mcp-forge-audit/references/opa-checklist.md"),
            ("skills/mcp-forge-audit/references/spec-formats.md", "skills/mcp-forge-audit/references/spec-formats.md"),
            ("skills/mcp-forge-audit/references/verification-rules.md", "skills/mcp-forge-audit/references/verification-rules.md"),
            ("skills/mcp-create/SKILL.md", "skills/mcp-create/SKILL.md"),
            ("skills/mcp-create/references/adaptation-guide.md", "skills/mcp-create/references/adaptation-guide.md"),
            ("skills/mcp-create/references/analyze-source.md", "skills/mcp-create/references/analyze-source.md"),
            ("skills/mcp-create/references/deploy-procedure.md", "skills/mcp-create/references/deploy-procedure.md"),
            ("skills/mcp-create/references/deploy-workflow.md", "skills/mcp-create/references/deploy-workflow.md"),
            ("skills/mcp-create/references/infra-config-guide.md", "skills/mcp-create/references/infra-config-guide.md"),
            ("skills/mcp-create/references/smoke-test-templates.md", "skills/mcp-create/references/smoke-test-templates.md"),
            ("skills/mcp-create/references/validate-procedure.md", "skills/mcp-create/references/validate-procedure.md"),
            ("skills/mcp-create/references/write-classifier.md", "skills/mcp-create/references/write-classifier.md"),
        ],
    },
    {
        "name": "research-intel",
        "description": "Intelligence gathering skills — community patterns, repo discovery, Claude Code changelog tracking, research papers, developer profile analysis, deep research with multi-source discrepancy flagging, and internal Slack/Linear/Confluence intel.",
        "version": "1.1.0",
        "files": [
            ("skills/gather-intel/SKILL.md", "skills/gather-intel/SKILL.md"),
            ("skills/gather-repos/SKILL.md", "skills/gather-repos/SKILL.md"),
            ("skills/gather-repos/references/repo-assessment.md", "skills/gather-repos/references/repo-assessment.md"),
            ("skills/evaluate-repos/SKILL.md", "skills/evaluate-repos/SKILL.md"),
            ("skills/scout/SKILL.md", "skills/scout/SKILL.md"),
            ("skills/scout-frontier/SKILL.md", "skills/scout-frontier/SKILL.md"),
            ("skills/scout-frontier/references/paradigm-distance-rubric.md", "skills/scout-frontier/references/paradigm-distance-rubric.md"),
            ("skills/scout-frontier/references/search-venues.md", "skills/scout-frontier/references/search-venues.md"),
            ("skills/scout-frontier/test-fixtures/code-intel-paradigms.json", "skills/scout-frontier/test-fixtures/code-intel-paradigms.json"),
            ("skills/scout-frontier/test-fixtures/observability-paradigms.json", "skills/scout-frontier/test-fixtures/observability-paradigms.json"),
            ("skills/scout-frontier/test-fixtures/2026-04-27-observability-findings.md", "skills/scout-frontier/test-fixtures/2026-04-27-observability-findings.md"),
            ("skills/scout-frontier/scripts/score_rubric.py", "skills/scout-frontier/scripts/score_rubric.py"),
            ("skills/scout-frontier/scripts/validate_constraint_trace.py", "skills/scout-frontier/scripts/validate_constraint_trace.py"),
            ("skills/scout-frontier/references/verification.md", "skills/scout-frontier/references/verification.md"),
            ("skills/scout-frontier/references/integration-cost-rubric.md", "skills/scout-frontier/references/integration-cost-rubric.md"),
            ("skills/scout-frontier/references/finding-output-template.md", "skills/scout-frontier/references/finding-output-template.md"),
            ("skills/scout-skills/SKILL.md", "skills/scout-skills/SKILL.md"),
            ("skills/scout-skills/scripts/verify_skip.py", "skills/scout-skills/scripts/verify_skip.py"),
            ("skills/scout-skills/scripts/produce_card.py", "skills/scout-skills/scripts/produce_card.py"),
            ("skills/scout-skills/references/anti-patterns.md", "skills/scout-skills/references/anti-patterns.md"),
            ("skills/scout-skills/references/finding-classification.md", "skills/scout-skills/references/finding-classification.md"),
            ("skills/scout-skills/references/known-repos.md", "skills/scout-skills/references/known-repos.md"),
            ("skills/scout-skills/references/report-format.md", "skills/scout-skills/references/report-format.md"),
            ("skills/scout-skills/references/search-strategies.md", "skills/scout-skills/references/search-strategies.md"),
            ("skills/scout-skills/references/skip-verification.md", "skills/scout-skills/references/skip-verification.md"),
            ("skills/scout-skills/references/technique-card-template.md", "skills/scout-skills/references/technique-card-template.md"),
            ("skills/scout-skills/references/routing-destinations.md", "skills/scout-skills/references/routing-destinations.md"),
            ("skills/gather-claude/SKILL.md", "skills/gather-claude/SKILL.md"),
            ("skills/gather-claude/references/examples-and-evals.md", "skills/gather-claude/references/examples-and-evals.md"),
            ("skills/gather-claude/references/run-metrics.md", "skills/gather-claude/references/run-metrics.md"),
            ("skills/gather-vendor/SKILL.md", "skills/gather-vendor/SKILL.md"),
            ("skills/gather-research/SKILL.md", "skills/gather-research/SKILL.md"),
            ("skills/deep-dive/SKILL.md", "skills/deep-dive/SKILL.md"),
            # Multi-agent adversarial review
            ("skills/roundtable/SKILL.md", "skills/roundtable/SKILL.md"),
            # Developer / internal intel
            ("skills/absorb/SKILL.md", "skills/absorb/SKILL.md"),
            ("skills/absorb/references/evidence-streams.md", "skills/absorb/references/evidence-streams.md"),
            ("skills/absorb/references/examples.md", "skills/absorb/references/examples.md"),
            ("skills/absorb/references/phase4-file-mapping.md", "skills/absorb/references/phase4-file-mapping.md"),
            ("skills/gather-internal-intel/SKILL.md", "skills/gather-internal-intel/SKILL.md"),
            # Persona dispatch — methodology research tool
            ("skills/persona/SKILL.md", "skills/persona/SKILL.md"),
            ("skills/persona/references/discovery-mode.md", "skills/persona/references/discovery-mode.md"),
            ("skills/persona/references/inventory-management.md", "skills/persona/references/inventory-management.md"),
            ("skills/persona/references/meta-mode.md", "skills/persona/references/meta-mode.md"),
            ("skills/persona/references/methodology-evolution.md", "skills/persona/references/methodology-evolution.md"),
            ("skills/persona/references/prior-results.md", "skills/persona/references/prior-results.md"),
            ("skills/persona/references/rubric-mode.md", "skills/persona/references/rubric-mode.md"),
            ("skills/persona/references/scoring-disciplines.md", "skills/persona/references/scoring-disciplines.md"),
            ("skills/persona/references/triage-protocol.md", "skills/persona/references/triage-protocol.md"),
            ("skills/persona/scripts/analyze.py", "skills/persona/scripts/analyze.py"),
            ("skills/persona/scripts/cohort_sample.py", "skills/persona/scripts/cohort_sample.py"),
            ("skills/persona/scripts/dispatch.py", "skills/persona/scripts/dispatch.py"),
            ("skills/persona/scripts/parse_inventory.py", "skills/persona/scripts/parse_inventory.py"),
            ("skills/persona/scripts/score_keyword.py", "skills/persona/scripts/score_keyword.py"),
            ("skills/persona/scripts/score_llm_judge.py", "skills/persona/scripts/score_llm_judge.py"),
            ("skills/persona/templates/dispatch-prompt.md", "skills/persona/templates/dispatch-prompt.md"),
            ("skills/persona/templates/pre-registration.md", "skills/persona/templates/pre-registration.md"),
            ("skills/persona/templates/rubric.yaml", "skills/persona/templates/rubric.yaml"),
            ("skills/persona/inventories/canonical-2026-04-29.meta.yaml", "skills/persona/inventories/canonical-2026-04-29.meta.yaml"),
            ("skills/persona/inventories/README.md", "skills/persona/inventories/README.md"),
        ],
    },
]


# ── CURATED-EXPORT PRUNE ──────────────────────────────────────────────
# This repository is a CURATED SUBSET of a larger private configuration: skills
# whose purpose was operating specific internal systems are not shipped. The
# PLUGINS manifest above still declares them, and _preflight_plugin() correctly
# refuses to build against a missing source.
#
# So prune the manifest to what actually exists here -- LOUDLY. A silent skip
# could ship a hook without a helper module it imports, which is exactly the
# self-containment property the plugin format requires (installed plugins are
# copied to a cache and cannot reference files outside their own directory).
#
# Order matters: drop missing FILES first, then drop hook REGISTRATIONS whose
# script is no longer bundled, then drop plugins left with nothing to ship.


def _prune_manifest_to_existing_sources() -> None:
    """Drop declared sources absent from this export, reporting every removal."""
    kept_plugins = []
    total_dropped = 0

    for plugin in PLUGINS:
        name = plugin["name"]
        present, missing = [], []
        for entry in plugin.get("files", []):
            src_rel = entry[0] if isinstance(entry, tuple) else entry
            (present if (CLAUDE_DIR / src_rel).exists() else missing).append(entry)

        if missing:
            print(f"  prune {name}: dropping {len(missing)} absent source(s)")
            for entry in missing:
                print(f"      - {entry[0] if isinstance(entry, tuple) else entry}")
            total_dropped += len(missing)
        plugin["files"] = present

        # A hook registration naming a script we no longer bundle would resolve
        # to nothing at runtime, so remove it with the script.
        bundled = {
            (entry[1] if isinstance(entry, tuple) else entry).split("/")[-1]
            for entry in present
        }
        hooks_cfg = plugin.get("hooks") or {}
        for event, groups in list(hooks_cfg.items()):
            surviving = []
            for group in groups:
                scripts = [
                    arg
                    for handler in group.get("hooks", [])
                    for arg in handler.get("args", [])
                    if arg.endswith(".py")
                ]
                if scripts and not all(s.split("/")[-1] in bundled for s in scripts):
                    print(f"  prune {name}: unregistering {event} hook {scripts}")
                    continue
                surviving.append(group)
            if surviving:
                hooks_cfg[event] = surviving
            else:
                del hooks_cfg[event]

        ships_skills = any(
            (entry[0] if isinstance(entry, tuple) else entry).startswith("skills/")
            for entry in present
        )
        if not present or not (ships_skills or hooks_cfg):
            print(f"  prune: REMOVING plugin {name} (nothing left to ship)")
            continue
        kept_plugins.append(plugin)

    # Vacuity floor: an empty result would make every downstream check pass
    # trivially and publish an empty marketplace.
    if not kept_plugins:
        raise RuntimeError("prune removed every plugin; refusing to build")
    PLUGINS[:] = kept_plugins
    print(
        f"  prune summary: {len(kept_plugins)} plugin(s) retained, "
        f"{total_dropped} absent source(s) dropped"
    )


_prune_manifest_to_existing_sources()
# ── end CURATED-EXPORT PRUNE ──────────────────────────────────────────

# INTENTIONALLY LOCAL-ONLY (not registered above):
# - lab-deploy: example-labs-org-specific Amplify deployment helper. Tied to
#   internal org AWS account; not useful outside Example. Healthcheck will
#   continue to flag this as "on disk but not in PLUGINS" — that's expected.
# - agentic-search: experimental multi-query rerank with disable-model-invocation.
#   Manually invocable for niche extreme-difficulty queries; production rerank
#   already at HR@5=0.993 so general publication isn't justified yet. Keep
#   local-only until accuracy edge over baseline is reproducible.
# - audit-skill / audit-fix: heavyweight internal audit tooling. Depend on
#   ~/.claude/audit-runs/ infrastructure, oracle setup, and the locally-
#   indexed skill corpus. Not useful in a generic Claude Code installation
#   without first reproducing that infrastructure — keep local-only.


# Cache/build cruft never shipped into a plugin, even inside a copied skill dir.
SKILL_COPY_EXCLUDES = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".DS_Store"}
# Repo-internal files a plugin consumer never reads. manifest.yaml is this
# repo's manifest-graph metadata (the prior builder deliberately omitted it;
# see bin/audit-skill.py H3 note). Excluded so plugins stay free of internal
# metadata while still shipping every SKILL.md-referenced file.
# build-history.jsonl / unmapped-history.jsonl are machine-local runtime
# state (untracked at source since 2026-06-10) — never ship into a plugin.
SKILL_COPY_EXCLUDE_NAMES = {"manifest.yaml", "build-history.jsonl", "unmapped-history.jsonl"}
NON_PACKAGEABLE_SKILLS = {
    # Intentionally inert prototype. Its canonical frontmatter disables both
    # user and model invocation; publishing it would turn an unfinished stub
    # into an advertised command surface.
    "sca-review",
}
TEXT_ASSET_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}

# Shared assets are deliberately NOT skills: they are copied below
# ``skills/_shared`` without a SKILL.md and therefore never become ambient
# discovery context. References occur in several canonical forms because the
# source tree predates plugins. The built copy normalizes those references to
# CLAUDE_PLUGIN_ROOT after copying; canonical source remains untouched.
_SHARED_REF_RE = re.compile(
    r"(?:"
    r"~/\.claude/skills/|\$HOME/\.claude/skills/|"
    r"\$\{?CONFIG_ROOT\}?/skills/|\$\{?CLAUDE_CONFIG_ROOT\}?/skills/|"
    r"\$\{CLAUDE_PLUGIN_ROOT\}/skills/|"
    r"(?:\.\./)?skills/|\.\./"
    r")?_shared/(?P<path>[A-Za-z0-9_./*?{}\[\]-]+)"
)
_INLINE_LOCAL_REF_RE = re.compile(
    r"`(?P<code>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+)`|"
    r"\]\((?P<link>[^)\s]+)\)"
)
_HELPER_REF_RE = re.compile(
    r"(?:"
    r"(?P<bin_prefix>~/\.claude/bin/|\$HOME/\.claude/bin/|"
    r"\$\{?CONFIG_ROOT\}?/bin/|\$\{?CLAUDE_CONFIG_ROOT\}?/bin/)"
    r"(?P<bin_path>[A-Za-z0-9_][A-Za-z0-9_./-]*)|"
    r"(?P<scripts_prefix>~/\.claude/scripts/|\$HOME/\.claude/scripts/|"
    r"\$\{?CONFIG_ROOT\}?/scripts/|\$\{?CLAUDE_CONFIG_ROOT\}?/scripts/)"
    r"(?P<scripts_path>[A-Za-z0-9_][A-Za-z0-9_./-]*)"
    r")"
)
_LOCAL_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([A-Za-z_][\w]*)\s+import|import\s+([A-Za-z_][\w]*))",
    re.MULTILINE,
)


def _validated_relative_path(raw: str, *, label: str) -> Path:
    """Return a portable relative path or fail before touching output."""
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise ValueError(f"{label} must be a non-empty POSIX relative path: {raw!r}")
    if re.match(r"^[A-Za-z]:", raw):
        raise ValueError(f"{label} must be a relative path: {raw!r}")
    path = Path(raw)
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError(f"{label} must be a contained relative path: {raw!r}")
    return path


def _assert_source_contained(path: Path, root: Path, *, label: str) -> None:
    """Reject missing, non-file, escaping, or symlinked source paths."""
    try:
        root_resolved = root.resolve(strict=True)
        relative = path.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} is outside its source root: {path}") from exc
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"{label} contains a symlink: {cursor}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} escapes its source root: {path}") from exc


def _read_requires_skills(skill_name: str) -> list[str]:
    """Read the small ``requires_skills`` list without a YAML dependency.

    Manifests use either ``requires_skills: []`` or an indented dash list.
    Anything else fails closed: silently guessing at a malformed dependency
    graph would publish a plugin whose composed workflow cannot run.
    """
    skill_dir = CLAUDE_DIR / "skills" / skill_name
    manifest_path = skill_dir / "manifest.yaml"
    skill_path = skill_dir / "SKILL.md"
    if (
        not skill_dir.is_dir()
        or not manifest_path.is_file()
        or not skill_path.is_file()
    ):
        raise ValueError(
            f"unknown required skill {skill_name!r}: expected {manifest_path} "
            f"and {skill_path}"
        )

    lines = manifest_path.read_text(encoding="utf-8").splitlines()
    top_level_keys = [
        match.group(1)
        for line in lines
        if (match := re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:", line))
    ]
    duplicate_keys = sorted(
        key for key in set(top_level_keys) if top_level_keys.count(key) > 1
    )
    if duplicate_keys:
        raise ValueError(
            f"duplicate {', '.join(duplicate_keys)} fields in {manifest_path}"
        )
    id_lines = [line for line in lines if re.match(r"^id\s*:", line)]
    manifest_id = (
        id_lines[0].split(":", 1)[1].strip().strip("\"'")
        if id_lines
        else None
    )
    if manifest_id != skill_name:
        raise ValueError(
            f"skill manifest id mismatch: directory={skill_name!r}, id={manifest_id!r}"
        )

    requires_fields = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := re.match(r"^requires_skills\s*:\s*(.*?)\s*$", line))
    ]
    for index, match in requires_fields:
        inline = match.group(1).split("#", 1)[0].strip()
        if inline:
            if inline == "[]":
                return []
            if inline.startswith("[") and inline.endswith("]"):
                values = [
                    value.strip().strip("\"'")
                    for value in inline[1:-1].split(",")
                    if value.strip()
                ]
                if all(re.fullmatch(r"[a-z0-9][a-z0-9-]*", v) for v in values):
                    return values
            raise ValueError(
                f"unsupported requires_skills syntax in {manifest_path}: {inline!r}"
            )

        values = []
        for child in lines[index + 1 :]:
            if not child.strip() or child.lstrip().startswith("#"):
                continue
            item = re.match(r"^\s+-\s+([a-z0-9][a-z0-9-]*)\s*(?:#.*)?$", child)
            if item:
                values.append(item.group(1))
                continue
            if not child.startswith((" ", "\t")):
                break
            raise ValueError(
                f"unsupported requires_skills entry in {manifest_path}: {child!r}"
            )
        return values
    raise ValueError(f"missing requires_skills field in {manifest_path}")


def _skill_dependency_closure(root_skills) -> tuple[list[str], dict[str, list[str]]]:
    """Return roots plus their transitive manifest-declared dependencies.

    Cycles are legal composition (for example supergoal pause/resume) and are
    broken by the visited set. Unknown dependencies and malformed manifests
    raise before any incomplete plugin is accepted.
    """
    ordered = []
    dependencies = {}
    pending = deque(root_skills)
    seen = set()
    while pending:
        name = pending.popleft()
        if name in seen:
            continue
        if name in NON_PACKAGEABLE_SKILLS:
            raise ValueError(
                f"skill {name!r} is intentionally non-packageable; remove it "
                "from plugin roots or the active requires_skills graph"
            )
        required = _read_requires_skills(name)
        # Resolve every edge immediately so an unknown later duplicate cannot
        # hide behind the visited set.
        for dependency in required:
            if dependency in NON_PACKAGEABLE_SKILLS:
                raise ValueError(
                    f"active skill {name!r} requires intentionally "
                    f"non-packageable skill {dependency!r}"
                )
            _read_requires_skills(dependency)
        seen.add(name)
        ordered.append(name)
        dependencies[name] = required
        pending.extend(required)
    return ordered, dependencies


def _copy_skill_dir(src_dir: Path, dest_dir: Path) -> int:
    """Copy an entire skill directory (references/, scripts/, templates/, ...)
    so the SKILL.md's relative links resolve inside the plugin. Skips cache
    cruft, compiled artifacts, and repo-internal metadata. Returns the number
    of files copied."""
    copied = 0
    for src in sorted(src_dir.rglob("*")):
        if src.is_symlink():
            raise ValueError(f"skill source contains a symlink: {src}")
        if src.is_dir():
            continue
        rel = src.relative_to(src_dir)
        if any(part in SKILL_COPY_EXCLUDES for part in rel.parts):
            continue
        if src.name in SKILL_COPY_EXCLUDE_NAMES or src.suffix == ".pyc":
            continue
        _assert_source_contained(src, src_dir, label="skill source")
        dest = dest_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
    return copied


def _iter_text_files(root: Path):
    if root.is_file():
        candidates = (root,)
    elif root.is_dir():
        candidates = root.rglob("*")
    else:
        return
    for path in candidates:
        if (
            path.is_file()
            and path.suffix.lower() in TEXT_ASSET_SUFFIXES
            and not any(part in SKILL_COPY_EXCLUDES for part in path.parts)
        ):
            yield path


def _expand_asset_reference(source_root: Path, raw_reference: str) -> set[Path]:
    """Resolve a referenced shared/helper asset inside ``source_root``.

    A templated leaf such as ``stig-targets/{target}.md`` selects that bounded
    directory. A repository-wide glob such as ``_shared/*.md`` is descriptive,
    not a dependency, and is intentionally ignored rather than copying the
    whole shared tree.
    """
    raw = raw_reference.rstrip(".,:;)]}'\"")
    if not raw:
        return set()
    relative = _validated_relative_path(raw, label="shared/helper reference")
    parts = relative.parts

    pattern_index = next(
        (
            index
            for index, part in enumerate(parts)
            if re.search(r"[{}\[\]*?]", part)
        ),
        None,
    )
    if pattern_index is not None:
        fixed_parts = parts[:pattern_index]
        # Do not turn a category/example like skills/_shared/*.md into a copy
        # of every shared file. A templated child directory is bounded.
        if not fixed_parts:
            return set()
        target = source_root.joinpath(*fixed_parts)
    else:
        target = source_root.joinpath(*parts)

    try:
        target.resolve().relative_to(source_root.resolve())
    except ValueError as exc:
        raise ValueError(f"asset reference escapes source root: {raw!r}") from exc

    if not target.exists():
        raise FileNotFoundError(f"referenced asset does not exist: {target}")
    _assert_source_contained(target, source_root, label="referenced asset")
    if target.is_file():
        return {target}
    selected = set()
    for path in target.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"referenced asset contains a symlink: {path}")
        if path.is_dir():
            continue
        _assert_source_contained(path, source_root, label="referenced asset")
        if (
            not any(part in SKILL_COPY_EXCLUDES for part in path.parts)
            and path.name not in SKILL_COPY_EXCLUDE_NAMES
            and path.suffix != ".pyc"
        ):
            selected.add(path)
    return selected


def _shared_references(text: str) -> set[str]:
    return {match.group("path") for match in _SHARED_REF_RE.finditer(text)}


def _discover_shared_assets(skill_names, extra_sources=()) -> list[Path]:
    """Discover the bounded shared-asset closure for selected skills.

    This replaces the old model-policy-only allowlist. It discovers all
    explicit ``_shared`` references, expands only their bounded file/directory,
    then follows local markdown/code links between selected shared files. A new
    model overlay therefore ships automatically when the policy names it.
    """
    shared_root = CLAUDE_DIR / "skills" / "_shared"
    pending_refs = deque()
    for skill_name in skill_names:
        for source in _iter_text_files(CLAUDE_DIR / "skills" / skill_name):
            text = source.read_text(encoding="utf-8", errors="ignore")
            pending_refs.extend(_shared_references(text))
    for source in extra_sources:
        if source.suffix.lower() not in TEXT_ASSET_SUFFIXES:
            continue
        text = source.read_text(encoding="utf-8", errors="ignore")
        pending_refs.extend(_shared_references(text))

    selected = set()
    scanned = set()
    while pending_refs:
        raw_reference = pending_refs.popleft()
        for source in _expand_asset_reference(shared_root, raw_reference):
            if source in selected:
                continue
            selected.add(source)

        # Scan every newly selected text file. Besides another explicit
        # _shared reference, follow a local path in backticks/markdown links
        # when it resolves under the shared tree (for model-overlays/*, etc.).
        for source in sorted(selected - scanned):
            scanned.add(source)
            if source.suffix.lower() not in TEXT_ASSET_SUFFIXES:
                continue
            text = source.read_text(encoding="utf-8", errors="ignore")
            pending_refs.extend(_shared_references(text))
            for match in _INLINE_LOCAL_REF_RE.finditer(text):
                candidate = match.group("code") or match.group("link")
                if not candidate or "://" in candidate or candidate.startswith("#"):
                    continue
                local = (source.parent / candidate).resolve()
                try:
                    relative = local.relative_to(shared_root.resolve())
                except ValueError:
                    continue
                if local.exists():
                    pending_refs.append(relative.as_posix())
    return sorted(selected, key=lambda path: path.relative_to(shared_root).parts)


def _copy_shared_assets(plugin_dir: Path, sources) -> int:
    shared_root = CLAUDE_DIR / "skills" / "_shared"
    copied = 0
    for source in sources:
        _assert_source_contained(source, shared_root, label="shared asset")
        relative = source.relative_to(shared_root)
        destination = plugin_dir / "skills" / "_shared" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    return copied


def _helper_references(text: str) -> set[tuple[str, str]]:
    references = set()
    for match in _HELPER_REF_RE.finditer(text):
        if match.group("bin_path"):
            references.add(("bin", match.group("bin_path")))
        else:
            references.add(("scripts", match.group("scripts_path")))
    return references


def _discover_helper_assets(skill_names, shared_sources) -> list[tuple[str, Path]]:
    """Discover root ``bin/`` and ``scripts/`` helper dependencies.

    Only explicitly referenced root helpers are seeded. Python sibling imports
    and named sibling data files are then followed transitively. This is small
    and deterministic: it never copies an entire root helper directory.
    """
    pending = deque()
    for skill_name in skill_names:
        for source in _iter_text_files(CLAUDE_DIR / "skills" / skill_name):
            pending.extend(_helper_references(source.read_text(
                encoding="utf-8", errors="ignore"
            )))
    for source in shared_sources:
        if source.suffix.lower() in TEXT_ASSET_SUFFIXES:
            pending.extend(_helper_references(source.read_text(
                encoding="utf-8", errors="ignore"
            )))

    selected = set()
    while pending:
        kind, raw_reference = pending.popleft()
        source_root = CLAUDE_DIR / kind
        expanded = _expand_asset_reference(source_root, raw_reference)
        if not expanded:
            continue
        for source in expanded:
            key = (kind, source)
            if key in selected:
                continue
            selected.add(key)
            if source.suffix.lower() not in TEXT_ASSET_SUFFIXES:
                continue
            text = source.read_text(encoding="utf-8", errors="ignore")
            pending.extend(_helper_references(text))

            # Resolve local Python imports (transcript_friction_corpus imports
            # two sibling modules) and direct sibling data assets
            # (x-monitor.py names x-monitor.config.json).
            if source.suffix == ".py":
                for match in _LOCAL_IMPORT_RE.finditer(text):
                    module = match.group(1) or match.group(2)
                    module_source = source_root / f"{module}.py"
                    if module_source.is_file():
                        pending.append((kind, module_source.name))
            for sibling in source_root.iterdir():
                if sibling.is_file() and sibling != source and sibling.name in text:
                    pending.append((kind, sibling.name))

    return sorted(selected, key=lambda item: (item[0], item[1].parts))


def _copy_helper_assets(plugin_dir: Path, helpers) -> int:
    copied = 0
    for kind, source in helpers:
        source_root = CLAUDE_DIR / kind
        _assert_source_contained(source, source_root, label="root helper")
        destination = plugin_dir / kind / source.relative_to(source_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    return copied


_PYTHON_EXPANDUSER_SKILL_RE = re.compile(
    r"os\.path\.expanduser\(\s*([\"'])~/\.claude/skills/([^\"']+)\1\s*\)"
)


def _rewrite_cached_paths(plugin_dir: Path) -> int:
    """Normalize cached executable/data paths without editing canonical prose."""
    changed = 0
    replacements = (
        ("~/.claude/skills/", "${CLAUDE_PLUGIN_ROOT}/skills/"),
        ("$HOME/.claude/skills/", "${CLAUDE_PLUGIN_ROOT}/skills/"),
        ("$CONFIG_ROOT/skills/_shared/", "${CLAUDE_PLUGIN_ROOT}/skills/_shared/"),
        ("${CONFIG_ROOT}/skills/_shared/", "${CLAUDE_PLUGIN_ROOT}/skills/_shared/"),
        ("$CLAUDE_CONFIG_ROOT/skills/_shared/", "${CLAUDE_PLUGIN_ROOT}/skills/_shared/"),
        ("${CLAUDE_CONFIG_ROOT}/skills/_shared/", "${CLAUDE_PLUGIN_ROOT}/skills/_shared/"),
        ("~/.claude/bin/", "${CLAUDE_PLUGIN_ROOT}/bin/"),
        ("$HOME/.claude/bin/", "${CLAUDE_PLUGIN_ROOT}/bin/"),
        ("$CONFIG_ROOT/bin/", "${CLAUDE_PLUGIN_ROOT}/bin/"),
        ("${CONFIG_ROOT}/bin/", "${CLAUDE_PLUGIN_ROOT}/bin/"),
        ("$CLAUDE_CONFIG_ROOT/bin/", "${CLAUDE_PLUGIN_ROOT}/bin/"),
        ("${CLAUDE_CONFIG_ROOT}/bin/", "${CLAUDE_PLUGIN_ROOT}/bin/"),
        ("~/.claude/scripts/", "${CLAUDE_PLUGIN_ROOT}/scripts/"),
        ("$HOME/.claude/scripts/", "${CLAUDE_PLUGIN_ROOT}/scripts/"),
        ("$CONFIG_ROOT/scripts/", "${CLAUDE_PLUGIN_ROOT}/scripts/"),
        ("${CONFIG_ROOT}/scripts/", "${CLAUDE_PLUGIN_ROOT}/scripts/"),
        ("$CLAUDE_CONFIG_ROOT/scripts/", "${CLAUDE_PLUGIN_ROOT}/scripts/"),
        ("${CLAUDE_CONFIG_ROOT}/scripts/", "${CLAUDE_PLUGIN_ROOT}/scripts/"),
    )
    for path in _iter_text_files(plugin_dir):
        original = path.read_text(encoding="utf-8", errors="strict")
        updated = original
        if path.suffix == ".py":
            # Never apply shell-style substitutions across arbitrary Python
            # source. Besides changing parser constants and examples, replacing
            # text inside an f-string turns ``${CLAUDE_PLUGIN_ROOT}`` into a
            # Python expression and raises NameError at runtime. Only transform
            # the one executable path-construction shape we can preserve
            # semantically.
            updated = _PYTHON_EXPANDUSER_SKILL_RE.sub(
                lambda match: (
                    'os.path.join(os.environ["CLAUDE_PLUGIN_ROOT"], "skills", '
                    + json.dumps(match.group(2))
                    + ")"
                ),
                updated,
            )
        else:
            for old, new in replacements:
                updated = updated.replace(old, new)
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
            changed += 1
    return changed


def _preflight_plugin(plugin_def: dict) -> None:
    """Validate a plugin declaration and its exact sources before staging."""
    name = plugin_def.get("name")
    if not isinstance(name, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]*", name
    ):
        raise ValueError(f"invalid plugin name: {name!r}")
    for field in ("description", "version"):
        if not isinstance(plugin_def.get(field), str) or not plugin_def[field]:
            raise ValueError(f"plugin {name!r} has invalid {field}")
    files = plugin_def.get("files")
    if not isinstance(files, list):
        raise ValueError(f"plugin {name!r} files must be a list")

    root_skills = {}
    destinations = set()
    for entry in files:
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise ValueError(f"plugin {name!r} has malformed file entry: {entry!r}")
        src_rel, dest_rel = entry
        source_path = _validated_relative_path(
            src_rel, label=f"plugin {name!r} source relative path"
        )
        destination_path = _validated_relative_path(
            dest_rel, label=f"plugin {name!r} destination relative path"
        )
        if destination_path in destinations:
            raise ValueError(
                f"plugin {name!r} has duplicate destination: {dest_rel!r}"
            )
        destinations.add(destination_path)
        source = CLAUDE_DIR / source_path
        if not source.exists():
            raise FileNotFoundError(
                f"explicit plugin source does not exist: {source_path.as_posix()}"
            )
        if not source.is_file():
            raise ValueError(
                f"explicit plugin source is not a regular file: "
                f"{source_path.as_posix()}"
            )
        _assert_source_contained(source, CLAUDE_DIR, label="explicit plugin source")
        if len(source_path.parts) >= 2 and source_path.parts[0] == "skills":
            root_skills.setdefault(source_path.parts[1], None)

    # Parse the entire active dependency graph now. Missing SKILL.md files,
    # malformed/duplicate manifest fields, and unknown edges therefore fail
    # before the previous published payload can be replaced.
    _skill_dependency_closure(root_skills)


def _assemble_plugin(plugin_def: dict, plugin_dir: Path) -> int:
    """Assemble a single plugin in an empty staging directory.

    Skills are copied as COMPLETE directories (any skills/<name>/... entry in
    the file list selects the whole skills/<name>/ tree) so their
    references/scripts/templates ship with them. The previous per-file
    allowlist dropped un-listed reference files, leaving published SKILL.md
    files pointing at paths that weren't in the plugin. Non-skill files
    (hooks/, agents/) are still copied individually by exact path.
    """
    # Create plugin manifest
    manifest_dir = plugin_dir / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": plugin_def["name"],
        "description": plugin_def["description"],
        "version": plugin_def["version"],
        "author": PLUGIN_AUTHOR,
    }
    (manifest_dir / "plugin.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    copied = 0
    root_skill_names = {}  # preserve first-seen order, dedupe

    for src_rel, dest_rel in plugin_def["files"]:
        parts = Path(src_rel).parts
        if len(parts) >= 2 and parts[0] == "skills":
            root_skill_names.setdefault(parts[1], None)
            continue
        # Non-skill file (hook / rule / agent): copy individually.
        src = CLAUDE_DIR / src_rel
        dest = plugin_dir / dest_rel
        _assert_source_contained(src, CLAUDE_DIR, label="explicit plugin source")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1

    skill_names, dependency_edges = _skill_dependency_closure(root_skill_names)

    # Copy each root and manifest-required skill as a complete directory.
    for name in skill_names:
        src_dir = CLAUDE_DIR / "skills" / name
        copied += _copy_skill_dir(src_dir, plugin_dir / "skills" / name)

    # Reach a fixed point across explicit shared references and root-helper
    # references. In practice this converges in one or two iterations; the
    # loop makes a helper->shared->helper edge safe without a manual list.
    shared_sources = []
    helper_sources = []
    for _ in range(8):
        next_shared = _discover_shared_assets(
            skill_names, (source for _, source in helper_sources)
        )
        next_helpers = _discover_helper_assets(skill_names, next_shared)
        if next_shared == shared_sources and next_helpers == helper_sources:
            break
        shared_sources = next_shared
        helper_sources = next_helpers
    else:
        raise RuntimeError(
            f"packaging dependency closure did not converge for {plugin_def['name']}"
        )

    copied += _copy_shared_assets(plugin_dir, shared_sources)
    copied += _copy_helper_assets(plugin_dir, helper_sources)

    # The dependency lock is both review evidence and a deterministic test
    # surface. It contains source-relative names only, never host/runtime state.
    dependency_lock = {
        "schema_version": 1,
        "root_skills": list(root_skill_names),
        "packaged_skills": skill_names,
        "requires_skills": dependency_edges,
        "shared_assets": [
            source.relative_to(CLAUDE_DIR / "skills" / "_shared").as_posix()
            for source in shared_sources
        ],
        "helpers": [
            f"{kind}/{source.relative_to(CLAUDE_DIR / kind).as_posix()}"
            for kind, source in helper_sources
        ],
    }
    (manifest_dir / "dependency-lock.json").write_text(
        json.dumps(dependency_lock, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    copied += 1

    _rewrite_cached_paths(plugin_dir)

    if plugin_def.get("hooks"):
        hooks_path = plugin_dir / "hooks" / "hooks.json"
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        hooks_path.write_text(
            json.dumps(
                {
                    "description": f"{plugin_def['name']} plugin hooks",
                    "hooks": plugin_def["hooks"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        copied += 1

    path_problems = _plugin_skill_path_problems(plugin_def["name"], plugin_dir)
    if path_problems:
        details = "; ".join(problem[2] for problem in path_problems)
        raise ValueError(details)

    return copied


def build_plugin(plugin_def: dict) -> int:
    """Build in isolation, then replace the prior payload only after success."""
    _preflight_plugin(plugin_def)
    MARKETPLACE_DIR.mkdir(parents=True, exist_ok=True)
    name = plugin_def["name"]
    final_dir = MARKETPLACE_DIR / name
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{name}.build-", dir=MARKETPLACE_DIR)
    )
    try:
        copied = _assemble_plugin(plugin_def, staging_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    backup_dir = Path(
        tempfile.mkdtemp(prefix=f".{name}.backup-", dir=MARKETPLACE_DIR)
    )
    backup_dir.rmdir()
    moved_previous = False
    try:
        if final_dir.exists():
            final_dir.rename(backup_dir)
            moved_previous = True
        staging_dir.rename(final_dir)
    except Exception:
        if moved_previous and not final_dir.exists() and backup_dir.exists():
            backup_dir.rename(final_dir)
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    if moved_previous:
        shutil.rmtree(backup_dir)
    return copied


# In-skill relative links (references/foo.md, scripts/bar.py, templates/x.yaml,
# test-fixtures/y.json, inventories/z.yaml) that a SKILL.md instructs Claude to read.
_REF_RE = re.compile(
    r"(?:references|scripts|templates|test-fixtures|inventories)/[\w./-]+"
    r"\.(?:md|py|ya?ml|json|txt|sh|ql)"
)


def check_dropped_references() -> list:
    """Return [(plugin, skill, ref)] for any in-skill reference that exists in
    the source skill but is missing from the built plugin — the exact failure
    the per-file allowlist used to produce. With whole-dir copies it should be
    empty. Near-zero false positives: a path is flagged only if it genuinely
    exists in the source skill yet wasn't shipped."""
    problems = []
    for plugin_def in PLUGINS:
        plugin_dir = MARKETPLACE_DIR / plugin_def["name"]
        for skill_md in sorted(plugin_dir.glob("skills/*/SKILL.md")):
            skill = skill_md.parent.name
            src_skill = CLAUDE_DIR / "skills" / skill
            text = skill_md.read_text(encoding="utf-8", errors="ignore")
            for ref in sorted(set(_REF_RE.findall(text))):
                if (src_skill / ref).exists() and not (skill_md.parent / ref).exists():
                    problems.append((plugin_def["name"], skill, ref))
    return problems


def check_shared_asset_containment() -> list:
    """Return shared references that do not resolve inside their plugin."""
    problems = []
    for plugin_def in PLUGINS:
        plugin_dir = MARKETPLACE_DIR / plugin_def["name"]
        shared_root = plugin_dir / "skills" / "_shared"
        if (shared_root / "SKILL.md").exists():
            problems.append((plugin_def["name"], "_shared", "ambient SKILL.md"))
        for source in _iter_text_files(plugin_dir / "skills"):
            if "_shared/" not in source.read_text(encoding="utf-8", errors="ignore"):
                continue
            body = source.read_text(encoding="utf-8", errors="ignore")
            for reference in _shared_references(body):
                try:
                    targets = _expand_asset_reference(shared_root, reference)
                except (FileNotFoundError, ValueError) as exc:
                    problems.append(
                        (
                            plugin_def["name"],
                            source.relative_to(plugin_dir).as_posix(),
                            str(exc),
                        )
                    )
                    continue
                if not targets and not re.search(r"[{}\[\]*?]", reference):
                    problems.append(
                        (
                            plugin_def["name"],
                            source.relative_to(plugin_dir).as_posix(),
                            f"empty shared dependency: {reference}",
                        )
                    )
    return problems


_PLUGIN_HELPER_REF_RE = re.compile(
    r"\$\{CLAUDE_PLUGIN_ROOT\}/(?P<kind>bin|scripts)/"
    r"(?P<path>[A-Za-z0-9_{}\[\]*?][A-Za-z0-9_./{}\[\]*?-]*)"
)
_PLUGIN_SKILL_REF_RE = re.compile(
    r"\$\{CLAUDE_PLUGIN_ROOT\}/skills/"
    r"(?P<path>[A-Za-z0-9_{}\[\]*?][A-Za-z0-9_./{}\[\]*?-]*)"
)
_LEGACY_PACKAGED_SKILL_PREFIXES = (
    "~/.claude/skills/",
    "$HOME/.claude/skills/",
)


def check_skill_dependency_containment() -> list:
    """Return manifest-required skills absent from a generated plugin."""
    problems = []
    for plugin_def in PLUGINS:
        plugin_dir = MARKETPLACE_DIR / plugin_def["name"]
        lock_path = plugin_dir / ".claude-plugin" / "dependency-lock.json"
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append((plugin_def["name"], "dependency-lock", str(exc)))
            continue
        packaged = set(lock.get("packaged_skills", []))
        for skill_name, dependencies in lock.get("requires_skills", {}).items():
            if skill_name not in packaged:
                problems.append((plugin_def["name"], skill_name, "skill absent"))
            for dependency in dependencies:
                if dependency not in packaged or not (
                    plugin_dir / "skills" / dependency / "SKILL.md"
                ).is_file():
                    problems.append(
                        (plugin_def["name"], skill_name, f"missing {dependency}")
                    )
    return problems


def _plugin_skill_path_problems(plugin_name: str, plugin_dir: Path) -> list:
    """Find canonical skill assets referenced but absent from one plugin.

    Missing canonical targets can be deliberate output paths or documented
    future interfaces, so only a target that exists in the source tree creates
    a packaging obligation.

    A name in SKILL_COPY_EXCLUDE_NAMES creates NO obligation even when it does
    exist canonically. Those files are machine-local runtime state that the copy
    layer deliberately refuses to ship, so requiring them here contradicts it:
    on any host where the producing skill has actually run, the file appears in
    the source tree, the obligation fires, and the build can never satisfy it.
    CI never sees this because a fresh checkout has no runtime state.
    """
    problems = []
    canonical_skills = CLAUDE_DIR / "skills"
    # SKILL.md is the executable instruction surface. Historical/reference
    # prose can legitimately cite optional or external skills and must not turn
    # into a hard runtime dependency merely because the canonical target exists.
    for source in sorted((plugin_dir / "skills").glob("*/SKILL.md")):
        body = source.read_text(encoding="utf-8", errors="ignore")
        for match in _PLUGIN_SKILL_REF_RE.finditer(body):
            raw = match.group("path")
            try:
                canonical_targets = _expand_asset_reference(canonical_skills, raw)
            except FileNotFoundError:
                continue
            except ValueError as exc:
                problems.append(
                    (plugin_name, source.relative_to(plugin_dir).as_posix(), str(exc))
                )
                continue
            if not canonical_targets:
                continue
            # Drop deliberately-unshipped runtime state before it can create an
            # unsatisfiable obligation (see the docstring).
            canonical_targets = {
                target
                for target in canonical_targets
                if target.name not in SKILL_COPY_EXCLUDE_NAMES
            }
            if not canonical_targets:
                continue
            try:
                packaged_targets = _expand_asset_reference(
                    plugin_dir / "skills", raw
                )
            except (FileNotFoundError, ValueError):
                packaged_targets = set()
            if not packaged_targets:
                problems.append(
                    (
                        plugin_name,
                        source.relative_to(plugin_dir).as_posix(),
                        f"missing packaged skill target: {raw}",
                    )
                )
    return problems


def check_packaged_path_containment() -> list:
    """Return legacy skill paths or missing plugin-root helper targets."""
    problems = []
    for plugin_def in PLUGINS:
        plugin_dir = MARKETPLACE_DIR / plugin_def["name"]
        problems.extend(
            _plugin_skill_path_problems(plugin_def["name"], plugin_dir)
        )
        for source in _iter_text_files(plugin_dir):
            body = source.read_text(encoding="utf-8", errors="ignore")
            if source.suffix != ".py":
                for prefix in _LEGACY_PACKAGED_SKILL_PREFIXES:
                    if prefix in body:
                        problems.append(
                            (
                                plugin_def["name"],
                                source.relative_to(plugin_dir).as_posix(),
                                prefix,
                            )
                        )
            for match in _PLUGIN_HELPER_REF_RE.finditer(body):
                raw = match.group("path")
                try:
                    targets = _expand_asset_reference(
                        plugin_dir / match.group("kind"), raw
                    )
                except (FileNotFoundError, ValueError) as exc:
                    problems.append(
                        (
                            plugin_def["name"],
                            source.relative_to(plugin_dir).as_posix(),
                            str(exc),
                        )
                    )
                    continue
                if not targets and not re.search(r"[{}\[\]*?]", raw):
                    problems.append(
                        (
                            plugin_def["name"],
                            source.relative_to(plugin_dir).as_posix(),
                            f"empty helper dependency: {raw}",
                        )
                    )
    return problems


VERSION_LEDGER = CLAUDE_DIR / ".claude-plugin" / "plugin-versions.json"
MIN_SAFE_PLUGIN_VERSIONS = {
    # Cross-branch payloads already used lower versions with different hashes.
    # These floors make each reconciled payload identity globally unambiguous.
    "code-intelligence": "1.1.12",
    "knowledge-ops": "1.1.39",
    "planning-toolkit": "1.1.26",
    "research-intel": "1.1.17",
    "safety-net": "1.1.25",
    "security-scanner": "1.1.6",
}


def _semver_tuple(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"plugin version must be numeric semver: {version!r}")
    return tuple(int(part) for part in parts)


def _max_semver(*versions: str) -> str:
    return max(versions, key=_semver_tuple)


def _increment_patch(version: str) -> str:
    major, minor, patch = _semver_tuple(version)
    return f"{major}.{minor}.{patch + 1}"


def _load_base_version_ledger() -> dict:
    """Read fetched origin/main evidence; absence or corruption is fatal."""
    completed = subprocess.run(
        ["git", "show", "origin/main:.claude-plugin/plugin-versions.json"],
        cwd=CLAUDE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"git exited {completed.returncode}"
        raise RuntimeError(
            "origin/main version ledger unavailable; fetch origin/main before "
            f"a release build ({detail})"
        )
    try:
        parsed = json.loads(completed.stdout)
    except ValueError as exc:
        raise RuntimeError(
            "origin/main version ledger is not valid JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("origin/main version ledger must be a JSON object")
    return parsed


def _base_ledger_for_build(*, offline_non_release: bool) -> dict:
    """Resolve base evidence, allowing only an explicitly diagnostic bypass."""
    try:
        return _load_base_version_ledger()
    except RuntimeError:
        if not offline_non_release:
            raise
        print(
            "WARNING: OFFLINE NON-RELEASE build has no origin/main version "
            "evidence; do not publish or commit its generated versions.",
            file=sys.stderr,
        )
        return {}


def _plugin_content_hash(plugin_dir: Path) -> str:
    """Deterministic content hash of a built plugin, excluding
    .claude-plugin/plugin.json (it embeds the version — circular).

    CRLF is normalized to LF before hashing: Windows runners check the
    repo out with autocrlf, so raw-byte hashing made every plugin's
    hash differ from the LF-computed ledger, spuriously bumping all six
    versions and failing the porcelain freshness gate — the exact
    merge-queue failure on PR #1162 (windows-2022, 2026-06-11)."""
    import hashlib
    h = hashlib.sha256()
    # Sort by the rel-path PARTS TUPLE (case-sensitive str tuples), not by
    # Path objects: WindowsPath ordering is case-insensitive, so SKILL.md
    # vs lowercase siblings ordered differently on the Windows runner than
    # on Linux — and a sequential hash is order-sensitive. That was the
    # residual five-plugin merge-queue failure after the CRLF fix
    # (2026-06-11): exactly the plugins with multi-file skill dirs
    # differed; safety-net's SKILL.md-only skills were immune. The parts
    # tuple matches PosixPath's native order, so committed ledger hashes
    # are unchanged (verified), and compares identically on every
    # platform. (A plain as_posix STRING key would NOT work: string vs
    # parts order diverges on dash-extended siblings like supergoal /
    # supergoal-pause — caught by the ledger-match probe.)
    entries = []
    for path in plugin_dir.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"plugin payload contains a symlink: {path}")
        if path.is_file():
            _assert_source_contained(path, plugin_dir, label="plugin payload")
            entries.append((path.relative_to(plugin_dir).parts, path))
    entries.sort(key=lambda entry: entry[0])
    for parts, q in entries:
        rel = "/".join(parts)
        if rel == ".claude-plugin/plugin.json":
            continue
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(q.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def resolve_plugin_versions(
    *,
    offline_non_release: bool = False,
    base_ledger: dict | None = None,
) -> dict:
    """Content-hash-derived auto-versioning (B10/F5 decision, 2026-06-10).

    Versions were frozen at 1.1.0 since inception, so `claude plugin update`
    never saw content changes. Now: a committed ledger
    (.claude-plugin/plugin-versions.json) maps plugin -> {version,
    content_hash}. Unchanged content keeps its version (builds stay
    idempotent — the freshness gate depends on that); changed content
    patch-bumps automatically and updates the ledger, which the porcelain
    freshness gate then forces into the same commit. The PLUGINS def
    `version` is only the initial floor; to force a minor/major bump,
    edit the ledger version directly and rebuild. Known quirk: edit ->
    rebuild -> revert -> rebuild bumps twice (no hash history is kept);
    harmless — versions stay monotonic and the spurious bump is a no-op
    update for consumers."""
    try:
        ledger = json.loads(VERSION_LEDGER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ledger = {}

    if base_ledger is None:
        base_ledger = _base_ledger_for_build(
            offline_non_release=offline_non_release
        )
    resolved = {}
    for plugin_def in PLUGINS:
        name = plugin_def["name"]
        plugin_dir = MARKETPLACE_DIR / name
        content_hash = _plugin_content_hash(plugin_dir)
        entry = ledger.get(name)
        if entry is None:
            version = plugin_def["version"]
        elif entry.get("content_hash") == content_hash:
            version = entry["version"]
        else:
            version = _increment_patch(entry["version"])

        required_versions = [version, MIN_SAFE_PLUGIN_VERSIONS.get(name, version)]
        base_entry = base_ledger.get(name)
        if isinstance(base_entry, dict) and base_entry.get("version"):
            base_version = base_entry["version"]
            if base_entry.get("content_hash") == content_hash:
                required_versions.append(base_version)
            else:
                required_versions.append(_increment_patch(base_version))
        version = _max_semver(*required_versions)

        prior_version = entry.get("version") if isinstance(entry, dict) else None
        if prior_version != version:
            reason = "content changed" if entry else "new plugin"
            print(f"  version bump: {name} {prior_version or '-'} -> {version} ({reason})")
        ledger[name] = {"version": version, "content_hash": content_hash}
        resolved[name] = version

        # Rewrite the plugin manifest with the resolved version.
        manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = version
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                                 encoding="utf-8", newline="\n")

    VERSION_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    VERSION_LEDGER.write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        newline="\n")
    return resolved


# Discovery metadata for the catalog. `relevance` lets Claude SUGGEST a plugin
# when the session matches; without it there is no proactive discovery at all.
# Schema (code.claude.com/docs/en/plugin-relevance): topic + signals, where
# signals is one or more of cwd / cli / hosts / filesRead / manifestDeps.
PLUGIN_RELEVANCE = {
    "safety-net": {
        "topic": "Claude Code agent safety and hooks",
        "signals": {
            "cwd": ["**/.claude/**"],
            "filesRead": ["**/.claude/settings.json", "**/.claude/hooks/**",
                          "**/hooks/*.py"],
        },
    },
    "security-scanner": {
        "topic": "Code security scanning and threat modelling",
        "signals": {
            "cli": ["semgrep", "codeql", "gitleaks", "trivy", "bandit"],
            "filesRead": ["**/*.rego", "**/Dockerfile*"],
        },
    },
    "research-intel": {
        "topic": "Multi-source technical research",
        "signals": {
            "hosts": ["arxiv.org", "api.tavily.com", "api.exa.ai",
                      "api.firecrawl.dev"],
        },
    },
    "knowledge-ops": {
        "topic": "Session knowledge capture and recall",
        "signals": {
            "filesRead": ["**/agent-memory/**", "**/knowledge-base/**",
                          "**/AGENTS.md", "**/CLAUDE.md"],
        },
    },
    "planning-toolkit": {
        "topic": "Plan-before-code and test-driven workflow",
        "signals": {
            "filesRead": ["**/docs/plans/**"],
            "cli": ["pytest"],
        },
    },
    # code-intelligence: intentionally absent, see the note in the export tooling.
}
PLUGIN_KEYWORDS = {
    "safety-net": ["hooks", "security", "guardrails", "enforcement"],
    "planning-toolkit": ["planning", "tdd", "debugging", "workflow"],
    "security-scanner": ["security", "sast", "semgrep", "codeql", "threat-model"],
    "knowledge-ops": ["memory", "knowledge-base", "retrospective", "documentation"],
    "code-intelligence": ["code-search", "call-graph", "refactoring", "api-docs"],
    "research-intel": ["research", "web-search", "multi-model", "evaluation"],
}
REPO_URL = "https://github.com/brandyn-s/claude-harness"


def build_marketplace_json(
    versions: dict | None = None, *, manifest_dir: Path | None = None
) -> None:
    """Write the root marketplace.json."""
    manifest_dir = manifest_dir or CLAUDE_DIR / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    marketplace = {
        "name": MARKETPLACE_NAME,
        "owner": MARKETPLACE_OWNER,
        "description": "Working Claude Code harness: hooks, ambient rules, and "
                       "skills, packaged as six installable bundles. Install one "
                       "bundle or the whole set; each is self-contained.",
        "$schema": "https://json.schemastore.org/claude-code-marketplace.json",
        "metadata": {"pluginRoot": "./marketplace"},
        "plugins": [],
    }

    for plugin_def in PLUGINS:
        version = (versions or {}).get(plugin_def["name"], plugin_def["version"])
        entry = {
            "name": plugin_def["name"],
            "source": f"./marketplace/{plugin_def['name']}",
            "description": plugin_def["description"],
            "version": version,
            "license": "MIT",
            "repository": REPO_URL,
        }
        if plugin_def["name"] in PLUGIN_KEYWORDS:
            entry["keywords"] = PLUGIN_KEYWORDS[plugin_def["name"]]
        if plugin_def["name"] in PLUGIN_RELEVANCE:
            entry["relevance"] = PLUGIN_RELEVANCE[plugin_def["name"]]
        marketplace["plugins"].append(entry)

    (manifest_dir / "marketplace.json").write_text(
        json.dumps(marketplace, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


# Local-module import shape: `import X` / `from X import ...` where X is a
# sibling hook module (hook_input, atomic_write, git_lock, ...).
_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][\w]*)", re.MULTILINE)


def check_hook_import_containment() -> list:
    """Return [(plugin, hook, missing_module)] for any shipped hook that
    imports a sibling hooks/ module the plugin does NOT ship — the
    dead-on-arrival class the 2026-06-10 install test caught (2 of 4
    starter hooks crashed on import; B9/F5 + B10/F1). Hooks/rules/agents
    are per-file allowlists by design (plugins ship deliberate subsets),
    so a generic "uncopied file" warning would be all noise; import
    resolvability is the invariant that actually breaks adopters."""
    local_modules = {p.stem for p in (CLAUDE_DIR / "hooks").glob("*.py")}
    problems = []
    for plugin_def in PLUGINS:
        hooks_dir = MARKETPLACE_DIR / plugin_def["name"] / "hooks"
        if not hooks_dir.is_dir():
            continue
        shipped = {p.stem for p in hooks_dir.glob("*.py")}
        for hook in sorted(hooks_dir.glob("*.py")):
            text = hook.read_text(encoding="utf-8", errors="ignore")
            for mod in _IMPORT_RE.findall(text):
                if mod in local_modules and mod not in shipped:
                    problems.append((plugin_def["name"], hook.name, mod))
    return problems


class MarketplaceValidationError(RuntimeError):
    """A staged release failed an integrity gate before promotion."""


def _validate_built_marketplace() -> None:
    """Run every release integrity gate against the active marketplace root."""
    problems = check_dropped_references()
    if problems:
        sys.stderr.write(
            f"\nERROR: {len(problems)} in-skill reference(s) present in source "
            "but missing from the built plugin:\n"
        )
        for plugin, skill, ref in problems[:40]:
            sys.stderr.write(f"  [{plugin}] skills/{skill}/{ref}\n")
        if len(problems) > 40:
            sys.stderr.write(f"  ... and {len(problems) - 40} more\n")
        raise MarketplaceValidationError("reference link-check failed")
    print("Reference link-check: OK (no dropped references)")

    dependency_problems = check_skill_dependency_containment()
    if dependency_problems:
        sys.stderr.write(
            f"\nERROR: {len(dependency_problems)} manifest-required skill "
            "dependency problem(s) in built plugins:\n"
        )
        for plugin, skill, target in dependency_problems:
            sys.stderr.write(f"  [{plugin}] skills/{skill}: {target}\n")
        raise MarketplaceValidationError("skill dependency closure failed")
    print("Skill dependency closure: OK")

    shared_problems = check_shared_asset_containment()
    if shared_problems:
        sys.stderr.write(
            f"\nERROR: {len(shared_problems)} shared asset reference(s) "
            "are not self-contained inside their plugin:\n"
        )
        for plugin, source, target in shared_problems:
            sys.stderr.write(f"  [{plugin}] {source}: {target}\n")
        raise MarketplaceValidationError("shared asset containment failed")
    print("Shared asset containment: OK")

    path_problems = check_packaged_path_containment()
    if path_problems:
        sys.stderr.write(
            f"\nERROR: {len(path_problems)} cached executable/helper path "
            "problem(s) in built plugins:\n"
        )
        for plugin, source, target in path_problems:
            sys.stderr.write(f"  [{plugin}] {source}: {target}\n")
        raise MarketplaceValidationError("cached path containment failed")
    print("Cached executable/helper path containment: OK")

    import_problems = check_hook_import_containment()
    if import_problems:
        sys.stderr.write(
            f"\nERROR: {len(import_problems)} shipped hook import(s) not "
            "satisfied inside the plugin (dead-on-arrival for adopters):\n"
        )
        for plugin, hook, mod in import_problems:
            sys.stderr.write(
                f"  [{plugin}] hooks/{hook} imports {mod} "
                f"— add hooks/{mod}.py to the plugin file list\n"
            )
        raise MarketplaceValidationError("hook import containment failed")
    print("Hook import self-containment: OK")


def _remove_transaction_path(path: Path) -> None:
    """Remove one exact transaction target during rollback."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _promote_release_transaction(
    staged_marketplace: Path,
    staged_manifest_dir: Path,
    transaction_root: Path,
    final_marketplace: Path,
    final_manifest_dir: Path,
) -> None:
    """Promote every plugin and root manifest, rolling back as one unit."""
    targets = [
        (staged_marketplace / plugin["name"], final_marketplace / plugin["name"])
        for plugin in PLUGINS
    ]
    targets.extend(
        (
            staged_manifest_dir / name,
            final_manifest_dir / name,
        )
        for name in ("plugin-versions.json", "marketplace.json")
    )
    for staged, _final in targets:
        if not staged.exists() or staged.is_symlink():
            raise RuntimeError(f"staged release target is missing or unsafe: {staged}")

    backup_root = transaction_root / "backup"
    moved_previous: list[tuple[Path, Path]] = []
    promoted: list[Path] = []
    try:
        for index, (_staged, final) in enumerate(targets):
            if not (final.exists() or final.is_symlink()):
                continue
            backup = backup_root / f"{index:02d}" / final.name
            backup.parent.mkdir(parents=True, exist_ok=True)
            final.rename(backup)
            moved_previous.append((backup, final))
        for staged, final in targets:
            final.parent.mkdir(parents=True, exist_ok=True)
            staged.rename(final)
            promoted.append(final)
    except Exception:
        for final in reversed(promoted):
            _remove_transaction_path(final)
        for backup, final in reversed(moved_previous):
            final.parent.mkdir(parents=True, exist_ok=True)
            backup.rename(final)
        raise


def _build_release_transaction(
    *, base_ledger: dict, offline_non_release: bool
) -> tuple[int, dict]:
    """Build and validate the complete release before changing final bytes."""
    global MARKETPLACE_DIR, VERSION_LEDGER

    final_marketplace = MARKETPLACE_DIR
    final_ledger = VERSION_LEDGER
    final_manifest_dir = final_ledger.parent
    transaction_root = Path(
        tempfile.mkdtemp(prefix=".marketplace-transaction-", dir=CLAUDE_DIR)
    )
    staged_marketplace = transaction_root / "marketplace"
    staged_manifest_dir = transaction_root / ".claude-plugin"
    staged_ledger = staged_manifest_dir / "plugin-versions.json"
    staged_manifest_dir.mkdir(parents=True)
    if final_ledger.is_file():
        shutil.copy2(final_ledger, staged_ledger)

    MARKETPLACE_DIR = staged_marketplace
    VERSION_LEDGER = staged_ledger
    try:
        total = 0
        for plugin_def in PLUGINS:
            count = build_plugin(plugin_def)
            total += count
            print(f"  {plugin_def['name']}: {count} files")

        print()
        versions = resolve_plugin_versions(
            offline_non_release=offline_non_release,
            base_ledger=base_ledger,
        )
        build_marketplace_json(versions, manifest_dir=staged_manifest_dir)
        print(f"Wrote .claude-plugin/marketplace.json ({len(PLUGINS)} plugins)")
        print(f"Total: {total} files across {len(PLUGINS)} plugins")
        _validate_built_marketplace()
    except Exception:
        shutil.rmtree(transaction_root, ignore_errors=True)
        raise
    finally:
        MARKETPLACE_DIR = final_marketplace
        VERSION_LEDGER = final_ledger

    try:
        _promote_release_transaction(
            staged_marketplace,
            staged_manifest_dir,
            transaction_root,
            final_marketplace,
            final_manifest_dir,
        )
    except Exception:
        shutil.rmtree(transaction_root, ignore_errors=True)
        raise
    shutil.rmtree(transaction_root, ignore_errors=True)
    return total, versions


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline-non-release",
        action="store_true",
        help=(
            "permit a local diagnostic build without fetched origin/main "
            "version evidence; generated versions must not be published"
        ),
    )
    args = parser.parse_args(argv)
    # Version collision evidence is a release precondition, not a post-build
    # diagnostic. Establish it before replacing any prior plugin payload.
    base_ledger = _base_ledger_for_build(
        offline_non_release=args.offline_non_release
    )
    print(f"Building marketplace plugins in {MARKETPLACE_DIR}/")
    print()
    try:
        _build_release_transaction(
            base_ledger=base_ledger,
            offline_non_release=args.offline_non_release,
        )
    except MarketplaceValidationError:
        sys.exit(1)
    print()
    print("Users install with:")
    print(f"  /plugin marketplace add brandyn-s/{MARKETPLACE_NAME}")
    print(f"  /plugin install safety-net@{MARKETPLACE_NAME}")


if __name__ == "__main__":
    main()
