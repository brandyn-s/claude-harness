#!/usr/bin/env python3
r"""PreToolUse:Bash — warn on narrow zsh-dialect failure shapes.

WHY THIS IS A HOOK AND NOT A RULE
---------------------------------
Under zsh (the Bash tool's shell on this host) an UNQUOTED argument containing a
glob metachar that matches no file aborts the whole command before it runs:

    grep -rn "x" hooks/ --include=*.py
    (eval):1: no matches found: --include=*.py

The command NEVER EXECUTES and its output is EMPTY. Empty output from a search
reads as an authoritative "0 hits — it isn't there", so this does not merely fail
silently, it MANUFACTURES A CONFIDENT NEGATIVE FINDING. bash passes unmatched
globs through verbatim, so the habit imports from every bash example anywhere.

Applying distill's T0 test — "if Claude forgets this, does output break
silently?" — yes, and worse: the abort does not register as a failed tool call,
so it never shows up in a failure count either.

The constraint is documented in THREE ambient places and has recurred >=5 times
(2026-06-12 x2 via `az --query`, 2026-07-19, 2026-07-24, 2026-08-01). Per
pattern-maturity-lifecycle (absorb -> rule -> use -> MEASURE -> enforce) the
measurement is in and prose has failed. `search-efficiency.md` also records that
the macOS platform-constraints file is injected PREVIEW-ONLY (~2 KB of 30 KB
reaches context), so the sibling zsh entries do not reliably load — a delivery
gap no amount of rewriting fixes.

The same adherence ceiling applies to bash-style word-splitting assumptions.
zsh passes an unquoted variable as one argv element. Two high-signal forms are
covered: `set -- $var`, and a quoted flag/value assignment expanded unquoted in
the same command. Generic unquoted variables remain out of scope.

DECISION CONTRACT — ADVISORY ONLY
---------------------------------
Prints hookSpecificOutput.additionalContext (the model-facing channel) and exits 0. It does NOT block, per
verify-effectiveness's enforcement gate: these shapes are recoverable by
re-quoting or using arrays. Any blocking proposal requires a separate,
evidence-backed review and explicit authorization.

MEASURED COMBINED FIRE RATE — 0.16% (9 of 5,640 real Bash commands over 40
recent session transcripts) against the >10% "too broad" gate; 29/29 replay
fixtures pass.
Harness: hooks/test-hooks/replay_bash_glob_metachar.py — RE-RUN IT after any
change to the patterns below, it gates on the rate and exits non-zero above 10%.

TWO CORRECTIONS THE REPLAY FORCED — do not undo either
------------------------------------------------------
1. The find-predicate pattern needs a LEFT BOUNDARY `(?<![\w-])`. Without it the
   pattern matches `class-name substitution?` inside an echo string — prose, not
   a find predicate. A real false positive found by replay, not by reasoning.
2. Quoted string bodies and heredoc bodies are stripped before scanning. A glob
   inside an `echo` is prose and zsh never expands it there; a heredoc body is
   data. Same class as the self-matching-checker trap
   (rules/tdd-mutation-testing item 19), though NOT the same instance: this
   docstring contains `--include=*.py` and the guard WOULD match it if pointed at
   its own source — which it never is. The guard scans COMMANDS only, so that is a
   fixture artifact, not a defect, and a test that pinned it would tempt a "fix"
   stripping triple-quoted blocks out of commands (wrong — commands have no
   docstrings). What the tests pin instead is the property that matters: a glob
   inside a quoted string in a REAL command does not fire, and an unquoted one
   beside a quoted decoy still does.

INTERRUPTION: safe — reads stdin, writes stdout, mutates no shared state.
"""

import json
import re
import sys

# --- detection -------------------------------------------------------------
# Highest-signal, lowest-false-positive shapes ONLY: an option VALUE or a find
# PREDICATE carrying a glob metachar, unquoted. Deliberately NOT a bare trailing
# path glob (`ls *.py`, `cat logs/*.txt`) — that is the CORRECT idiom when a match
# is expected, and flagging it would be pure noise.
_OPT_EQ = re.compile(r"--(?:include|exclude|exclude-dir)=(?!['\"])(\S*[*?\[]\S*)")
_FIND_PRED = re.compile(r"(?<![\w-])-(?:i?name|path)\s+(?!['\"])(\S*[*?\[]\S*)")
# A URL/path QUERY STRING. `?` is a glob metachar, so an unquoted `...?ref=v1`
# aborts the command exactly like `--include=*.py` does — but the empty result
# then reads as "the endpoint returned nothing", a claim about the SERVER rather
# than about the shell. Anchored at a token boundary and requires the `?key=`
# shape, so a bare trailing `foo?` (a deliberate single-char glob) is not caught.
_URL_QUERY = re.compile(r"(?:^|\s)(?!['\"])(\S*\?[\w.-]+=\S*)")
# `set -- $value` is a high-signal declaration that the author expects bash-like
# word-splitting. zsh instead assigns the whole expansion to one positional arg.
_SET_DASHDASH = re.compile(
    r"(?<!\S)set\s+--\s+(\$(?:[A-Za-z_]\w*|\{[A-Za-z_]\w*\}))(?=$|[\s;&|])"
)
# `for X in $var` is the same declaration in loop form, and it fails WORSE: the
# loop body still runs, exactly ONCE, with the whole string as one element. So
# unlike the glob branches there is no abort and no empty output to notice --
# the work appears to happen. Boundaries mirror _SET_DASHDASH deliberately:
#   `(?<!\S)`         command position, not a trailing `endfor in $x`
#   `\{[A-Za-z_]`      excludes the explicit-split `${=list}`
#   `(?=$|[\s;&|])`    excludes `$arr[@]` / `${arr[@]}`, which zsh DOES expand
#                     element-wise and which are therefore already correct
_FOR_IN_SPLIT = re.compile(
    r"(?<!\S)for\s+[A-Za-z_]\w*\s+in\s+"
    r"(\$(?:[A-Za-z_]\w*|\{[A-Za-z_]\w*\}))(?=$|[\s;&|])"
)
_FLAG_PACKING_ASSIGN = re.compile(
    r"(?<![\w])(?P<name>[A-Za-z_]\w*)=(?P<quote>['\"])(?P<value>-[^'\"\n]*\s+[^'\"\n]+?)(?P=quote)"
)

_HEREDOC = re.compile(r"<<-?\s*'?(\w+)'?.*?^\1", re.DOTALL | re.MULTILINE)
_DQ = re.compile(r'"[^"\n]*"')
_SQ = re.compile(r"'[^'\n]*'")

# An UNBRACED `$name:` followed by a zsh history-modifier character. `$ECR:latest`
# is not "the value then a literal :latest" — `:l` lowercases the value AND IS
# CONSUMED, so the tag is destroyed and no error is raised.
#
# THE CHARACTER SET IS MEASURED, NOT COPIED FROM EITHER STAGED SPEC — both were
# wrong. Probed every ASCII letter plus `& # % ? - / . _` against a value every
# modifier would visibly change (2026-08-27, zsh 5.9, `emulate -L zsh`):
#
#   corrupt silently : a c e h l q r t u A P Q &      (13)
#   abort the command: s                              (1, "bad substitution")
#   inert            : the other 46, incl. b d f g i j k m n o p v w x y z
#
# `zsh-colon-modifier-guard.spec.md` listed `p x g`, and
# `zsh-unbraced-colon-modifier.spec.md` listed `x g p f F w W` — every one of those
# measures INERT, so either list would fire on `"$IMG:prod"`, a safe and extremely
# common docker tag. The older list also MISSED `Q`. Implementing either verbatim
# would have shipped a false-positive class.
#
# Of 22 realistic suffixes probed, 15 are hazardous (`latest tag head arm64 test
# ancestor amd64 alpine utf8 all any` corrupt; `squashed sha256 stable` abort) and 7
# are safe (`v2 v1.2 8080 dev prod main 3.12`).
#
# LEFT BOUNDARY, three exclusions, each with a measured reason:
#   (?<!\$)  `$$var` is the PID followed by a literal word, not an expansion.
#   (?<!\\)  a BACKSLASH-ESCAPED `\$ECR:latest` is never expanded by zsh. This one
#            was found by the corpus replay, not by reasoning: 1 of the first 5 real
#            fires was `echo "... \$ECR:latest would trigger the zsh :l modifier"` —
#            PROSE INSIDE AN ECHO, warning about this very hazard, written by a
#            previous session that had just been bitten by it. A guard that fires on
#            correct writing about itself is the `tdd-quality` item-19 self-reference
#            class, and shipping on the fire RATE alone (0.044%, far under gate)
#            would have shipped it.
#   [A-Za-z_] after the `$` excludes the CORRECT braced form `${var:h}`.
# The optional `[...]` covers a subscripted `$arr[1]:t`.
_COLON_HAZARD_CHARS = "acehlqrtuAPQ&s"
_COLON_MODIFIER = re.compile(
    r"(?<!\$)(?<!\\)\$(?P<name>[A-Za-z_]\w*)(?:\[[^\]\n]*\])?:"
    r"(?P<mod>[" + _COLON_HAZARD_CHARS + r"])"
)
_COLON_MEANINGS = {
    "a": "absolute path", "A": "absolute path with symlinks resolved",
    "P": "realpath", "c": "resolved command path", "e": "extension only",
    "h": "head (dirname)", "t": "tail (basename)", "r": "extension removed",
    "l": "lowercased", "u": "uppercased", "q": "quoted", "Q": "quotes stripped",
    "&": "repeat the previous substitution",
    "s": "substitute — with no /pattern/ it ABORTS the command (bad substitution)",
}


def _strip_noise(command):
    """Drop heredoc bodies and quoted strings — neither is glob-expanded here."""
    body = _HEREDOC.sub("", command)
    body = _DQ.sub('""', body)
    body = _SQ.sub("''", body)
    return body


def _strip_unexpanded(command):
    """Drop only what zsh does NOT expand: heredoc bodies and single-quoted spans.

    Deliberately NOT `_strip_noise`. That strips DOUBLE-quoted spans too, which is
    right for the glob branches — an unmatched glob inside `"..."` is inert. It is
    exactly wrong for the colon-modifier branch, because a parameter expansion
    inside double quotes DOES expand, and every measured instance of this hazard
    lives inside them (`docker build -t "$ECR:latest"`). Reusing `_strip_noise`
    here would make the branch structurally blind to the defect it exists to catch
    while every test that used an unquoted fixture still passed.
    """
    body = _HEREDOC.sub("", command)
    return _SQ.sub("''", body)


def _is_unquoted_at(command, index):
    """Return whether ``index`` is outside single and double quotes."""
    quote = None
    escaped = False
    for char in command[:index]:
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
    return quote is None


def _check_flag_packing(command):
    """Return an unquoted expansion of a same-command packed flag assignment."""
    body = _HEREDOC.sub("", command)
    for assignment in _FLAG_PACKING_ASSIGN.finditer(body):
        if not _is_unquoted_at(body, assignment.start()):
            continue
        name = re.escape(assignment.group("name"))
        suffix = _strip_noise(body[assignment.end() :])
        expansion = re.search(
            rf"(?<![\w$])(\${name}|\$\{{{name}\}})(?!\w)", suffix
        )
        if expansion:
            return expansion.group(1)
    return None


def check_unquoted_glob(command):
    """Return (fired, offending_token, branch_name) for a dialect hazard.

    The BRANCH NAME is returned rather than only a bool so a test can assert
    WHICH branch fired, per verify-effectiveness's N-branch GUARD: a control that
    always takes the same path still exits 0, so the untaken branch is the one
    that rots — silently, while the others keep the suite green.
    """
    body = _strip_noise(command)
    m = _OPT_EQ.search(body)
    if m:
        return True, m.group(0), "option-value"
    m = _FIND_PRED.search(body)
    if m:
        return True, m.group(0), "find-predicate"
    m = _URL_QUERY.search(body)
    if m:
        return True, m.group(1), "url-query"
    m = _SET_DASHDASH.search(body)
    if m:
        return True, m.group(1), "set-dashdash"
    m = _FOR_IN_SPLIT.search(body)
    if m:
        return True, m.group(1), "for-in-split"
    token = _check_flag_packing(command)
    if token:
        return True, token, "flag-packing"
    # LAST deliberately. Every branch above is evaluated against `_strip_noise`'d
    # text and its fixtures are pinned; putting this first would change which branch
    # a command matching two hazards reports, and silently re-verdict existing tests.
    # This branch also uses a DIFFERENT strip (see _strip_unexpanded), so it cannot
    # share the `body` above.
    m = _COLON_MODIFIER.search(_strip_unexpanded(command))
    if m:
        return True, m.group(0), "colon-modifier"
    return False, "", "none"


_MESSAGE = (
    "[zsh-dialect-guard] zsh will ABORT this command before it runs: {tok} is "
    "unquoted and matches no file in the CWD ((eval):1: no matches found). The "
    "command will NOT execute, and the resulting empty output is a PHANTOM 0-HIT "
    "— a property of the shell, not a negative finding. Fix: quote it ({fix}), or "
    "use the Grep tool's `glob` parameter, which never reaches a shell."
)
_WORD_SPLIT_MESSAGE = (
    "[zsh-dialect-guard] zsh does not word-split {token}. The expansion becomes "
    "one argv element containing the whole string, so the command can run with "
    "the wrong arguments. Use an array (`args=(...); command \"${{args[@]}}\"`), "
    "use `${{={name}}}` only when splitting is explicit, or inline the arguments."
)
_COLON_MESSAGE = (
    "[zsh-dialect-guard] `{token}` is not `${name}` followed by a literal `:{mod}`. "
    "In zsh an UNBRACED `$var:x` applies history modifier `:{mod}` ({meaning}) and "
    "CONSUMES it. {consequence} "
    "Fix: brace it — `${{{name}}}:{mod}...`. If you DID mean the modifier, write "
    "`${{{name}:{mod}}}` so the intent is explicit and this stops firing."
)
# The consequence differs by modifier and the difference matters: `:s` fails LOUDLY
# (the command aborts, so it gets noticed) while the rest corrupt SILENTLY. A single
# generic sentence saying "usually no error is raised" is simply false for `:s`, and
# a guard whose own message misdescribes the failure teaches the wrong lesson.
_COLON_ABORTS = "s&"
_COLON_CONSEQUENCE_SILENT = (
    "No error is raised — the character is just gone. Measured: "
    '`"$ECR:latest"` yields `registry/mcp/connectatest`, so the value is '
    "lowercased, the `l` is eaten, and the tag is DESTROYED."
)
# 3 of the 4 real corpus fires were GIT's own colon syntax, not docker tags. That is
# the shape most likely to reach you, and it is the one where you are least likely to
# be thinking about zsh at all — so name it explicitly rather than leaving the reader
# to generalise from a docker example.
_COLON_GIT_NOTE = (
    " NOTE: git's own `<rev>:<path>` and `<src>:<dst>` syntax collides with this "
    "directly — 3 of the 4 measured real instances were git, not docker. "
    "`git rev-parse $sha:rules/x.md` becomes `<sha>ules/x.md`, and "
    "`refs/heads/$HEAD_REF:refs/remotes/origin/$HEAD_REF` collapses into ONE "
    "mangled ref (`refs/heads/fix/some-branchefs/remotes/...`) instead of a "
    "refspec — worse still, a branch name containing a dot is TRUNCATED at it. "
    "Both were silenced by a `2>/dev/null` in the original commands."
)
_COLON_CONSEQUENCE_ABORT = (
    "This one fails LOUDLY: with no `/pattern/` to substitute, zsh reports "
    "`bad substitution` and the command does NOT run, so the empty output is a "
    "property of the shell rather than a result."
)


def advise(token, branch=None):
    """Build the advisory text (emitted as additionalContext by main); it does not block.

    The FIX suggestion is branch-specific. Quoting only the value after the first
    `=` is right for `--include=*.py` and WRONG for a query string: in
    `repos/x?ref='v1'` the `?` sits in the still-unquoted prefix and zsh globs the
    word anyway, so the suggested fix would not fix it. A query string needs the
    WHOLE token quoted.
    """
    if branch == "colon-modifier":
        m = _COLON_MODIFIER.search(token)
        # The router is only reached with a token this regex produced, so a miss
        # would mean the branch name and the token disagree. Fail loudly in tests
        # rather than emit a message with empty fields.
        assert m is not None, f"colon-modifier token does not re-match: {token!r}"
        name, mod = m.group("name"), m.group("mod")
        return {
            "advice": _COLON_MESSAGE.format(
                token=token, name=name, mod=mod,
                meaning=_COLON_MEANINGS.get(mod, "a history modifier"),
                consequence=(
                    (_COLON_CONSEQUENCE_ABORT if mod in _COLON_ABORTS
                     else _COLON_CONSEQUENCE_SILENT)
                    # Only when the token looks like a git rev/refspec, so the note
                    # lands where it helps instead of padding every advisory.
                    + (_COLON_GIT_NOTE if mod in "ra" else "")
                ),
            )
        }
    if branch in {"set-dashdash", "flag-packing", "for-in-split"}:
        name = token[2:-1] if token.startswith("${") else token[1:]
        return {
            "advice": _WORD_SPLIT_MESSAGE.format(token=token, name=name)
        }
    if branch == "url-query":
        return {"advice": _MESSAGE.format(tok=token, fix=f'"{token}"')}
    fix = token
    if "=" in token:
        key, _, value = token.partition("=")
        fix = f"{key}='{value}'"
    else:
        parts = token.split(None, 1)
        if len(parts) == 2:
            fix = f"{parts[0]} '{parts[1]}'"
    return {"advice": _MESSAGE.format(tok=token, fix=fix)}


def _log(branch, fired):
    try:
        from manifest_metrics import log_advisory_warning

        log_advisory_warning("zsh-dialect-guard", "Bash", branch, warned=fired)
    except Exception:  # noqa: S110, BLE001 -- fail-open: telemetry must never break the guard
        pass  # telemetry must never break the guard


def main():
    try:
        data = json.loads(sys.stdin.read())
        if data.get("tool_name", "") != "Bash":
            sys.exit(0)
        command = (data.get("tool_input") or {}).get("command", "")
        if not command:
            sys.exit(0)
        fired, token, branch = check_unquoted_glob(command)
        _log(branch, fired)
        if fired:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": advise(token, branch)["advice"]}}))
        sys.exit(0)
    except Exception:
        # Fail OPEN. An ADVISORY guard has nothing to protect by refusing, and a
        # crash that blocked every Bash call would be far worse than the phantom
        # 0-hit it warns about. A BLOCKING guard would fail closed instead.
        sys.exit(0)


if __name__ == "__main__":
    main()
