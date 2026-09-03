#!/usr/bin/env bash
set -e

# ── Claude Code Harness — Fresh-Laptop Installer ──────────────────────
# Lets you rebuild a portable core or select author-workstation components.
# Works on macOS, Linux, WSL, and Windows through Git Bash. On native Windows,
# generated exec-form hooks launch the copied dispatcher through bash.exe.
#
# Usage:
#   git clone https://github.com/brandyn-s/claude-harness.git
#   cd claude-harness
#   bash install.sh

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

info()  { echo -e "${BLUE}[info]${NC} $1"; }
ok()    { echo -e "${GREEN}[ok]${NC} $1"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $1"; }
err()   { echo -e "${RED}[error]${NC} $1"; }

# ── Detect Python ─────────────────────────────────────────────────────
# Floor is 3.11: scripts/install-profile.py imports datetime.UTC (3.11+) and
# bin/fresh_laptop_doctor.py requires 3.10+. The installer used to say 3.8+
# and never checked, so a stock-Python host failed inside the profile step.
detect_python() {
    if command -v python3 &>/dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &>/dev/null; then
        PYTHON_CMD="python"
    else
        err "Python not found. This installer and its hooks require Python 3.11+."
        exit 1
    fi
    PYTHON_PATH="$(command -v "$PYTHON_CMD")"
    if ! "$PYTHON_CMD" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
        err "Python 3.11+ is required; $PYTHON_PATH is $("$PYTHON_CMD" --version 2>&1). On macOS: brew install python@3.13"
        exit 1
    fi
    info "Using Python: $PYTHON_PATH"
}

# ── Qualify the installed Claude Code binary ─────────────────────────
check_claude_version() {
    if ! command -v claude &>/dev/null; then
        warn "Claude Code is not installed yet. settings.json will record the 2.1.223 updater downgrade guard; only an administrator-deployed requiredMinimumVersion blocks startup."
        return
    fi

    local output result
    if ! output="$(claude --version 2>&1)"; then
        err "The installed 'claude' command could not run: $output"
        exit 1
    fi
    if ! result="$($PYTHON_CMD "$SCRIPT_DIR/scripts/check_claude_version.py" "$output" 2>&1)"; then
        err "$result"
        exit 1
    fi
    info "$result"
}

ensure_runtime_floor() {
    local settings_file="$CLAUDE_DIR/settings.json"
    if [[ ! -f "$settings_file" ]]; then
        echo '{}' > "$settings_file"
    fi
    "$PYTHON_CMD" "$SCRIPT_DIR/scripts/wire_hooks.py" \
        --ensure-minimum-version "$settings_file"
    ok "Claude Code minimumVersion updater downgrade guard set to at least 2.1.223"
}

# ── Prompt helpers ────────────────────────────────────────────────────
# Sourced from scripts/install_prompts.sh so they can be tested without running
# an install (this script has no main() guard, so sourcing IT would install).
#
# The contract those helpers keep: human-readable output goes to STDERR, and
# only the machine-readable value goes to STDOUT. That matters because every
# ask_choice call site below captures stdout via $(...) -- when the menu was
# printed to stdout it became PART of the captured value, and every numbered
# branch fell through to the "skip" default. See the header of
# scripts/install_prompts.sh for the measured failure.
if [[ -f "$SCRIPT_DIR/scripts/install_prompts.sh" ]]; then
    # shellcheck source=scripts/install_prompts.sh
    source "$SCRIPT_DIR/scripts/install_prompts.sh"
else
    err "Missing $SCRIPT_DIR/scripts/install_prompts.sh (incomplete checkout?)"
    exit 1
fi

# ── Component installers ──────────────────────────────────────────────

install_rules() {
    local src_dir="$SCRIPT_DIR/rules"
    local dest_dir="$CLAUDE_DIR/rules"
    mkdir -p "$dest_dir"

    echo -e "\n${BOLD}Available rules:${NC}"
    local rules=()
    while IFS= read -r f; do
        rules+=("$(basename "$f")")
    done < <(find "$src_dir" -maxdepth 1 -name "*.md" -type f \
        ! -name "never-stop-early.md" \
        ! -name "validate-to-improve.md" | sort)

    local choice
    choice=$(ask_choice "Install which rules?" "All ${#rules[@]} rules" "Pick individually" "Skip rules")

    case "$choice" in
        1)
            for r in "${rules[@]}"; do
                cp "$src_dir/$r" "$dest_dir/$r"
            done
            ok "Installed ${#rules[@]} rules"
            ;;
        2)
            for r in "${rules[@]}"; do
                if ask_yn "  Install $r?"; then
                    cp "$src_dir/$r" "$dest_dir/$r"
                    ok "  Installed $r"
                fi
            done
            ;;
        *) info "Skipping rules" ;;
    esac
}

install_skills() {
    local src_dir="$SCRIPT_DIR/skills"
    local dest_dir="$CLAUDE_DIR/skills"
    mkdir -p "$dest_dir"

    # Category rosters. Counts shown in the menu are COMPUTED from these arrays,
    # never hardcoded (audit finding M3, 2026-07-26).
    #
    # The menu used to carry hand-written counts and every one of them had
    # drifted: it advertised "All portable skills (51)" against a tree holding
    # 105, plus security 11-vs-12, knowledge-ops 9-vs-8 and research 10-vs-8. It
    # also named skills that no longer exist -- writing-plans,
    # dispatching-parallel-agents and handoff (twice) -- so those `cp`s were
    # guaranteed misses. The three dead names are REMOVED rather than replaced
    # with a guess: none of them exists anywhere in the repo under any name
    # (verified against every SKILL.md, including marketplace/), so there is no
    # rename to follow and inventing a substitute would misrepresent the kit.
    local planning=(superplan interview refine design-evidence-first debugging-hypotheses
                    legacy-code-tdd review-depth-by-risk)
    local security=(semgrep codeql fp-check differential-review insecure-defaults
                    sharp-edges variant-analysis sarif-parsing
                    agentic-actions-auditor triage semgrep-rule-creator
                    )
    local knowledge=(distill recall garden retrospective review-learnings
                     validate-changes healthcheck)
    local codeintel=(code-explore codebase-memory-exploring codebase-memory-quality
                     codebase-memory-tracing index-repo)
    local research=(gather-intel gather-repos evaluate-repos scout scout-skills
                    gather-claude gather-research deep-dive)

    # Count what is actually installable, so "All" cannot advertise a stale total.
    local all_skills=()
    while IFS= read -r d; do
        local n
        n="$(basename "$d")"
        [[ "$n" == "_shared" ]] && continue
        all_skills+=("$n")
    done < <(find "$src_dir" -name "SKILL.md" -exec dirname {} \; | sort)

    local choice
    choice=$(ask_choice "Install which skills?" \
        "All portable skills (${#all_skills[@]})" \
        "Planning toolkit (${#planning[@]} skills)" \
        "Security scanner (${#security[@]} skills)" \
        "Knowledge ops (${#knowledge[@]} skills)" \
        "Code intelligence (${#codeintel[@]} skills)" \
        "Research intel (${#research[@]} skills)" \
        "Pick individually" \
        "Skip skills")

    local skills=()
    case "$choice" in
        1) skills=("${all_skills[@]}") ;;
        2) skills=("${planning[@]}") ;;
        3) skills=("${security[@]}") ;;
        4) skills=("${knowledge[@]}") ;;
        5) skills=("${codeintel[@]}") ;;
        6) skills=("${research[@]}") ;;
        7) # Pick individually
            while IFS= read -r d; do
                local name
                name="$(basename "$d")"
                [[ "$name" == "_shared" ]] && continue
                if ask_yn "  Install /$(basename "$d")?"; then
                    skills+=("$name")
                fi
            done < <(find "$src_dir" -name "SKILL.md" -exec dirname {} \; | sort)
            ;;
        *) info "Skipping skills"; return ;;
    esac

    for skill in "${skills[@]}"; do
        if [[ -d "$src_dir/$skill" ]]; then
            cp -r "$src_dir/$skill" "$dest_dir/$skill"
            ok "  Installed /$(basename "$skill")"
        fi
    done

    # skills/_shared/ (oracle, conventions, model overlays) is read by ~60 of the
    # shipped skills. The copy used to be gated on three skills that this export
    # does not contain, so no menu path ever installed it (review 2026-09-03).
    if (( ${#skills[@]} )) && [[ -d "$src_dir/_shared" ]]; then
        cp -r "$src_dir/_shared" "$dest_dir/_shared"
        ok "  Installed skills/_shared"
    fi

    ok "Installed ${#skills[@]} skills"
}

install_hooks() {
    local src_dir="$SCRIPT_DIR/hooks"
    local dest_dir="$CLAUDE_DIR/hooks"
    mkdir -p "$dest_dir"

    echo -e "\n${BOLD}Available hook bundles:${NC}"
    echo "  Hooks require settings.json wiring. This installer can do it automatically."
    echo ""
    local choice
    choice=$(ask_choice "Install which hooks?" \
        "Fresh-laptop core (bash safety, config integrity, injection guard)" \
        "Author workstation (all universal hooks)" \
        "Pick individually" \
        "Skip hooks")

    local hooks=()
    local hook_dirs=()
    local hook_configs=()
    case "$choice" in
        1) hooks=(bash-security-guard.py config-guard.py result-injection-guard.py)
           hook_configs=(
               'PreToolUse|Bash|bash-security-guard.py|30'
               'PreToolUse|Write|Edit|config-guard.py|30'
               'PostToolUse|mcp__.*|result-injection-guard.py|30'
           ) ;;
        2) hooks=(loop-detector.py result-injection-guard.py bash-security-guard.py
                  destructive-ops-guard.py bash-security-audit.py bash-error-classifier.py
                  config-guard.py memory-write-guard.py worktree-enforcement.py
                  rule-size-guard.py rule_context_budget.py home-scratch-guard.py
                  write-edit-dispatcher.py block-partial-read.py search-path-guard.py
                  post-write-edit.py post-failure-guide.py
                  config-change-validate.py session-start.py session-end.py
                  protected-repos.json)
           hook_dirs=(session_start_modules)
           # Timeouts below are aligned to settings.json (audit finding H4,
           # 2026-07-26). They previously hardcoded 3-5s while live used 15-30s.
           # A timed-out PreToolUse hook never returns its blocking decision, so
           # the action proceeds UNGUARDED (see hooks/run-hook) -- and measured
           # wrapper start-up alone is 1.4-4.1s, so a 3s budget could kill a
           # security guard before its body ran. Keep these >= 10s and in step
           # with settings.json; bin/test_drift_blocking_timeouts.py enforces it.
           hook_configs=(
               'ConfigChange|user_settings|project_settings|local_settings|config-change-validate.py|30'
               'PreToolUse|Bash|bash-security-guard.py|30'
               'PreToolUse|Bash|PowerShell|destructive-ops-guard.py|30'
               'PreToolUse|Glob|Grep|search-path-guard.py|30'
               'PreToolUse|Write|Edit|write-edit-dispatcher.py|30'
               'PreToolUse|Read|block-partial-read.py|30'
               'PostToolUse|Write|Edit|post-write-edit.py|30'
               'PostToolUse|mcp__.*|result-injection-guard.py|30'
               'PostToolUse|mcp__.*|Bash|Read|Glob|Grep|loop-detector.py|20'
               'PostToolUse|Bash|bash-security-audit.py|30'
               'PostToolUseFailure|mcp__.*|Bash|Read|Edit|Write|post-failure-guide.py|20'
               'PostToolUseFailure|Bash|bash-error-classifier.py|30'
               'SessionStart||session-start.py|30'
               'SessionEnd|.*|session-end.py|5'
           ) ;;
        3) # Pick individually
           for f in "$src_dir"/*.py; do
               local name
               name="$(basename "$f")"
               [[ "$name" == "__"* ]] && continue
               if ask_yn "  Install $name?"; then
                   hooks+=("$name")
               fi
           done ;;
        *) info "Skipping hooks"; return ;;
    esac

    for hook in "${hooks[@]}"; do
        if [[ -f "$src_dir/$hook" ]]; then
            cp "$src_dir/$hook" "$dest_dir/$hook"
        fi
    done
    for hook_dir in "${hook_dirs[@]}"; do
        if [[ -d "$src_dir/$hook_dir" ]]; then
            mkdir -p "$dest_dir/$hook_dir"
            cp -R "$src_dir/$hook_dir/." "$dest_dir/$hook_dir/"
        fi
    done
    # Always ship shared hook libraries + the run-hook dispatcher (the committed
    # settings.json / settings.example.json invoke hooks through run-hook), and
    # keep it executable.
    for shared in run-hook atomic_write.py hook_input.py git_lock.py bash_policy_tables.py; do
        if [[ -f "$src_dir/$shared" ]]; then
            cp "$src_dir/$shared" "$dest_dir/$shared"
        fi
    done
    [[ -f "$dest_dir/run-hook" ]] && chmod +x "$dest_dir/run-hook"
    ok "Copied ${#hooks[@]} hook files to $dest_dir/"

    # Auto-wire hooks into settings.json
    if [[ ${#hook_configs[@]} -gt 0 ]]; then
        if ask_yn "Auto-wire hooks into settings.json?" "y"; then
            wire_hooks "${hook_configs[@]}"
        else
            warn "Hooks copied but NOT wired. See settings.example.json for the format."
        fi
    fi
}

wire_hooks() {
    local settings_file="$CLAUDE_DIR/settings.json"
    local configs=("$@")

    # Ensure settings.json exists
    if [[ ! -f "$settings_file" ]]; then
        echo '{}' > "$settings_file"
    fi

    # The tested helper emits direct run-hook exec form on POSIX/WSL and a real
    # bash.exe executable with run-hook as argv[0] on native Windows.
    "$PYTHON_CMD" "$SCRIPT_DIR/scripts/wire_hooks.py" --reconcile-existing \
        "$settings_file" "${configs[@]}"
    ok "Hooks wired into settings.json"
}

install_agents() {
    local src_dir="$SCRIPT_DIR/agents"
    local dest_dir="$CLAUDE_DIR/agents"
    mkdir -p "$dest_dir"

    if ask_yn "Install agent definitions (worker + 5 specialized)?"; then
        for f in "$src_dir"/*.md; do
            cp "$f" "$dest_dir/"
        done
        ok "Installed $(ls "$src_dir"/*.md | wc -l) agent definitions"
    else
        info "Skipping agents"
    fi
}

install_agent_memory() {
    # Many skills (gather-intel, gather-research, gather-claude, gather-repos,
    # api-preflight, distill, triage, etc.) reference topic and rule files
    # under ~/.claude/agent-memory/. Without these, skills hit a runtime
    # gap and fall back to source-repo paths (works, but inconsistent).
    local src_dir="$SCRIPT_DIR/agent-memory"
    local dest_dir="$CLAUDE_DIR/agent-memory"
    if [[ ! -d "$src_dir" ]]; then
        warn "agent-memory/ not in source tree — skipping"
        return
    fi
    if ask_yn "Install agent-memory/ (topics + rules read by many skills)?" "y"; then
        mkdir -p "$dest_dir"
        cp -r "$src_dir/." "$dest_dir/"
        ok "Installed agent-memory/ ($(find "$src_dir" -type f | wc -l) files)"
    else
        info "Skipping agent-memory — skills will use source-repo fallback paths"
    fi
}

install_architecture_doc() {
    # ARCHITECTURE.md is cited by audit-architecture, sync-repo, gather-intel,
    # gather-claude, deep-dive ("Only if topic is about this system's own
    # design"). Deploying it makes those cites resolve at ~/.claude/.
    local src_file="$SCRIPT_DIR/ARCHITECTURE.md"
    local dest_file="$CLAUDE_DIR/ARCHITECTURE.md"
    if [[ ! -f "$src_file" ]]; then
        return
    fi
    if ask_yn "Install ARCHITECTURE.md (cited by audit/sync/gather skills)?" "y"; then
        cp "$src_file" "$dest_file"
        ok "Installed ARCHITECTURE.md"
    fi
}

# ── Main ──────────────────────────────────────────────────────────────

echo -e "${BOLD}"
echo "  Claude Code Harness — Fresh-Laptop Installer"
echo "  ============================================="
echo -e "${NC}"
echo "  This will install components into: $CLAUDE_DIR"
echo "  Source: $SCRIPT_DIR"
echo ""

detect_python
check_claude_version

if [[ ! -d "$CLAUDE_DIR" ]]; then
    mkdir -p "$CLAUDE_DIR"
    info "Created $CLAUDE_DIR"
fi

operator_selected=0
if ask_yn "Apply the fresh-laptop settings profile (fast edits + native sandbox)?" "y"; then
    profile_args=(--profile fresh-laptop)
    if ask_yn "Add the Brandyn operator layer (delivery policy + high-consequence review)?" "y"; then
        operator_selected=1
        profile_args+=(--profile brandyn-operator)
    fi
    "$PYTHON_CMD" "$SCRIPT_DIR/scripts/install-profile.py" \
        "${profile_args[@]}" --target "$CLAUDE_DIR/settings.json" --apply
fi

ensure_runtime_floor

# Quick install option
if ask_yn "Install the recommended fresh-laptop core? (2 rules + 3 deterministic hooks)" "y"; then
    mkdir -p "$CLAUDE_DIR/rules" "$CLAUDE_DIR/hooks"

    # The starter-kit manifest. SINGLE SOURCE OF TRUTH for both the collision
    # inventory and the copy loop (audit finding M2, 2026-07-26).
    #
    # These used to be two hand-maintained lists and they had DRIFTED: the
    # inventory checked 5 paths (1 rule + 4 hooks) while the copy wrote 11
    # (5 rules + 6 files under hooks/). So a user with local edits to
    # diagnose-before-fix.md, never-stop-early.md, validate-to-improve.md,
    # search-efficiency.md, hook_input.py or atomic_write.py had them silently
    # overwritten -- and the guard could still print "existing files kept",
    # having never looked at 6 of the files it was about to clobber. Deriving
    # the inventory from the manifest makes that drift unrepresentable.
    #
    # Shared libs come FIRST in the hooks list: result-injection-guard imports
    # hook_input. Same self-containment rule the
    # marketplace builder documents (build-marketplace.py ~line 54). The B10
    # empirical install test (2026-06-10) confirmed 2 of 4 starter hooks were
    # dead-on-arrival before this ordering was fixed.
    starter_rules=(
        outcome-over-verification.md
        claude-md-quality.md
    )
    starter_hooks=(
        run-hook
        hook_input.py
        manifest_metrics.py
        protected-repos.json
        bash_policy_tables.py
        bash-security-guard.py
        config-guard.py
        result-injection-guard.py
    )
    if (( operator_selected )); then
        starter_rules+=(operator-discipline.md)
        starter_hooks+=(
            atomic_write.py
            loop-detector.py
            prompt-secret-scan.py
            output-secret-redact.py
        )
    fi

    starter_files=()
    for rule in "${starter_rules[@]}"; do starter_files+=("rules/$rule"); done
    for hook in "${starter_hooks[@]}"; do starter_files+=("hooks/$hook"); done

    # Idempotency guard (B10): re-running used to silently overwrite any
    # local edits to previously installed starter files. Warn + confirm.
    existing=()
    for f in "${starter_files[@]}"; do
        [[ -f "$CLAUDE_DIR/$f" ]] && existing+=("$f")
    done
    if (( ${#existing[@]} )) && ! ask_yn "Starter files already exist (${#existing[@]} of ${#starter_files[@]} found, e.g. ${existing[0]}). Overwrite with repo versions?" "n"; then
        warn "Skipping starter kit copy (existing files kept)."
    else

    for rule in "${starter_rules[@]}"; do
        cp "$SCRIPT_DIR/rules/$rule" "$CLAUDE_DIR/rules/$rule"
    done

    for hook in "${starter_hooks[@]}"; do
        cp "$SCRIPT_DIR/hooks/$hook" "$CLAUDE_DIR/hooks/$hook"
    done
    chmod +x "$CLAUDE_DIR/hooks/run-hook"

    if (( operator_selected )); then
        ok "Fresh-laptop core + operator layer installed (3 rules + 6 hooks)"
    else
        ok "Fresh-laptop core installed (2 rules + 3 hooks + 5 support files)"
    fi
    fi  # idempotency guard

    hook_configs=(
        'PreToolUse|Bash|bash-security-guard.py|30'
        'PreToolUse|Write|Edit|config-guard.py|30'
        'PostToolUse|mcp__.*|result-injection-guard.py|30'
    )
    if (( operator_selected )); then
        hook_configs+=(
            'PostToolUse|mcp__.*|Bash|Read|Glob|Grep|loop-detector.py|20'
            'UserPromptSubmit|.*|prompt-secret-scan.py|30'
            'PostToolUse|Bash|Read|mcp__.*|output-secret-redact.py|30'
        )
    fi

    missing_starter_hooks=()
    for hook in "${starter_hooks[@]}"; do
        [[ -f "$CLAUDE_DIR/hooks/$hook" ]] || missing_starter_hooks+=("$hook")
    done
    if [[ -f "$CLAUDE_DIR/hooks/run-hook" && ! -x "$CLAUDE_DIR/hooks/run-hook" ]]; then
        missing_starter_hooks+=("run-hook (not executable)")
    fi

    if ask_yn "Wire these hooks into settings.json?" "y"; then
        if (( ${#missing_starter_hooks[@]} )); then
            warn "Not wiring starter hooks: the starter copy was incomplete (${missing_starter_hooks[0]} missing or unusable)."
        else
            wire_hooks "${hook_configs[@]}"
        fi
    fi

    # Activate the repo's committed githooks (pre-push marketplace-drift
    # gate). Without this a fresh clone never runs them — git defaults to
    # .git/hooks/. This was the known install.sh gap from the 2026-06-10
    # review; bin/setup-githooks.py existed but nothing invoked it.
    if [[ -d "$SCRIPT_DIR/.githooks" ]] && ask_yn "Activate this clone's .githooks/ (pre-push marketplace-drift gate)?" "y"; then
        (cd "$SCRIPT_DIR" && git config core.hooksPath .githooks) \
            && ok "githooks activated (core.hooksPath=.githooks)" \
            || warn "could not set core.hooksPath (not a git checkout?)"
    fi

    echo ""
    if ! ask_yn "Continue to pick more components?"; then
        echo ""
        ok "Installation complete!"
        exit 0
    fi
fi

install_rules
install_skills
install_hooks
install_agents
install_agent_memory
install_architecture_doc

# CLAUDE.template.md
if [[ -f "$SCRIPT_DIR/CLAUDE.template.md" ]]; then
    if [[ ! -f "$CLAUDE_DIR/CLAUDE.md" ]]; then
        if ask_yn "Install CLAUDE.template.md as your CLAUDE.md?"; then
            cp "$SCRIPT_DIR/CLAUDE.template.md" "$CLAUDE_DIR/CLAUDE.md"
            ok "Installed CLAUDE.md (customize it for your workflow)"
        fi
    else
        info "CLAUDE.md already exists — skipping template"
    fi
fi

echo ""
echo -e "${GREEN}${BOLD}Installation complete!${NC}"
echo ""
echo "  Next steps:"
echo "    1. Review installed files in $CLAUDE_DIR"
echo "    2. Customize any rules marked with <!-- CUSTOMIZE -->"
echo "    3. Start a Claude Code session to test"
echo ""
