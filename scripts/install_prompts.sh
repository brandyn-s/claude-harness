# shellcheck shell=bash
# ── Interactive prompt helpers for install.sh ──────────────────────────
#
# Extracted from install.sh so they can be tested without running an install.
# install.sh is a straight-line script with no main() guard, so sourcing it to
# reach these two functions would perform a real install into ~/.claude — which
# is why they had no tests, and why the M1 defect below survived.
#
# THE CONTRACT (this is the whole point of the file):
#
#   Everything a HUMAN reads goes to STDERR.
#   Only the machine-readable VALUE goes to STDOUT.
#
# `ask_choice` is called as `choice=$(ask_choice ...)`. Command substitution
# captures stdout, so anything printed there becomes part of the caller's value.
# Before this split, ask_choice printed its menu to stdout, and the captured
# value was the entire rendered menu with the digit glued on the end:
#
#     $'\nInstall which rules?\n  1. All\n  2. Pick individually\n  3. Skip\n2'
#
# Every `case "$choice" in 1) ... 2) ...` therefore fell through to `*)`, whose
# body is `info "Skipping ..."`. Measured, not inferred: the installer prompted
# the user, took their answer, and installed NOTHING — for rules, skills and
# hooks alike. The menu was invisible while they chose, because the substitution
# had swallowed it.
#
# `ask_yn` was already correct: it signals through its EXIT STATUS and prints
# nothing to stdout. Its prompt moves to stderr here for consistency, so a future
# `answer=$(ask_yn ...)` cannot reintroduce the same class of bug.

# Colors are defined by install.sh. Provide inert defaults so this file can be
# sourced standalone (by tests, or by another script) without `set -u` aborting.
: "${BOLD:=}"
: "${NC:=}"

# ask_yn <prompt> [default:y|n]
# Returns 0 for yes, 1 for no. Prints only to stderr.
ask_yn() {
    local prompt="$1" default="${2:-n}"
    local answer
    if [[ "$default" == "y" ]]; then
        # `read -rp` writes its prompt to STDERR already; the explicit redirect
        # documents the contract and keeps it true if this is ever restructured.
        read -rp "$(echo -e "${BOLD}$prompt [Y/n]:${NC} ")" answer
        [[ -z "$answer" || "$answer" =~ ^[Yy] ]]
    else
        read -rp "$(echo -e "${BOLD}$prompt [y/N]:${NC} ")" answer
        [[ "$answer" =~ ^[Yy] ]]
    fi
}

# ask_choice <prompt> <option1> [option2 ...]
# Echoes ONLY the user's raw selection to stdout. The menu goes to stderr so it
# stays visible to the user even when the caller captures stdout.
ask_choice() {
    local prompt="$1"
    shift
    local options=("$@")
    local choice

    {
        echo ""
        echo -e "${BOLD}${prompt}${NC}"
        for i in "${!options[@]}"; do
            echo "  $((i+1)). ${options[$i]}"
        done
    } >&2

    read -rp "$(echo -e "${BOLD}Choice [1-${#options[@]}]:${NC} ")" choice

    # The ONLY stdout write in this function.
    echo "$choice"
}
