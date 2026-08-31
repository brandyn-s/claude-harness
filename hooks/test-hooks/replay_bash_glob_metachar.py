#!/usr/bin/env python3
r"""Historical-replay harness for the installed zsh-dialect guard.

Committed per eval-shipping-discipline: a fire-rate number whose instrument lives
in /tmp is unrepeatable the moment the transcript corpus moves. Run before
installing the hook, and re-run to re-measure after any detector change.

  python3 hooks/test-hooks/replay_bash_glob_metachar.py

Exits 1 if the combined fire rate exceeds the 10% gate or any fixture fails.

An earlier find-predicate regex `-(?:i?name|path)\s+...` had no left boundary, so
`class-name substitution?` inside an echo string matched. Two corrections:
  1. require a word boundary / start-of-token before the dash
  2. strip double-quoted AND single-quoted string bodies before scanning — a glob
     inside an echo is prose, and zsh never expands it there anyway

IMPORTS THE HOOK RATHER THAN COPYING ITS PATTERNS (2026-08-02). This harness
originally duplicated the two regexes. That is the two-source drift problem: the
moment the hook's patterns change, the measurement silently describes DIFFERENT
code while still looking authoritative — the same defect as a baseline fed by two
sources but diffed against one. A drift check caught the copies had already
diverged in text (`(?!['\"])` vs `(?!["\'])` — behaviourally identical, verified
across 7 cases, but the divergence proves the copies drift). Importing means the
number is always about the SHIPPED detector.
"""
import importlib.util
import json
from pathlib import Path

_HOOK = Path(__file__).resolve().parent.parent / "zsh-dialect-guard.py"
_spec = importlib.util.spec_from_file_location("zsh_dialect_guard", _HOOK)
_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_guard)

def fires(cmd: str):
    """Route through the guard's REAL entry point, not its regexes.

    This called OPT_EQ/FIND_PR directly until 2026-08-02. A negative control then
    showed that disabling a BRANCH inside check_unquoted_glob left the harness
    reporting GATE PASSED — the regexes were untouched, so the harness could not
    see the change. Measuring a component the hook happens to contain is not
    measuring the hook: the entry point is what the PreToolUse call executes, and
    it is the only thing whose behaviour matters.
    """
    fired, token, branch = _guard.check_unquoted_glob(cmd)
    return [(branch, token)] if fired else []

proj = Path.home()/".claude/projects"
files = sorted(proj.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:40]
total=fired=malformed=0; ex=[]; branches={}
for f in files:
    for line in f.open(errors="replace"):
        if not line.strip().startswith("{"): continue
        try: r=json.loads(line)
        except json.JSONDecodeError: malformed+=1; continue
        c=(r.get("message") or {}).get("content")
        if not isinstance(c,list): continue
        for b in c:
            if isinstance(b,dict) and b.get("type")=="tool_use" and b.get("name")=="Bash":
                cmd=(b.get("input") or {}).get("command") or ""
                if not cmd: continue
                total+=1
                h=fires(cmd)
                if h:
                    fired+=1
                    branch=h[0][0]
                    branches[branch]=branches.get(branch,0)+1
                    if len(ex)<14: ex.append((f.stem[:8],h[0][1],cmd[:88].replace("\n"," ")))
rate = 100 * fired / total if total else 0.0
print(f"Bash commands  : {total}   malformed: {malformed}")
print(f"WOULD FIRE     : {fired}  ({rate:.2f}%)   [gate >10%]")
print("BY BRANCH      : " + ", ".join(f"{k}={v}" for k,v in sorted(branches.items())))
print("--- fires ---")
for s,tok,cmd in ex: print(f"  [{s}] {tok:24s} {cmd}")

FIX=[('grep -rn "x" hooks/ --include=*.py',True,"POSITIVE motivating bug"),
     ("grep -rn 'x' hooks/ --include='*.py'",False,"neg: quoted"),
     ('ls *.py',False,"neg: intended expansion"),
     ('find . -name *.md',True,"POSITIVE find predicate"),
     ("find . -name '*.md'",False,"neg: quoted predicate"),
     ('cat logs/*.txt',False,"neg: trailing path glob"),
     ('echo "=== is it class-name substitution? ==="',False,"neg: PROSE in echo (v1 FP)"),
     ('grep -rn "x" . --include=*.py 2>/dev/null',True,"POSITIVE with redirect"),
     ("python3 - <<'PY'\nx = '--include=*.py'\nPY",False,"neg: heredoc body"),
     # --- fixtures below added 2026-08-02 after the NEGATIVE CONTROL FAILED ---
     # Breaking the hook's left boundary left this harness reporting GATE PASSED:
     # every fixture that exercises the boundary was also covered by the quote or
     # heredoc strip, so removing the boundary changed nothing measured. A harness
     # that cannot fail is not an instrument. Each case below is UNQUOTED and
     # OUTSIDE a heredoc, so exactly ONE mechanism covers it.
     ('cmd --flag class-name substitution?',False,"neg: UNQUOTED hyphenated word (isolates the LEFT BOUNDARY)"),
     ('run task by-name *.md',False,"neg: UNQUOTED by-name (boundary only)"),
     ("cat > f.sh <<'SH'\ngrep -rn x . --include=*.py\nSH",False,"neg: UNQUOTED glob in heredoc body (heredoc strip only)"),
     ('echo class-name; find . -name *.md',True,"POSITIVE: real predicate after a hyphenated word"),
     ('echo "safe --include=*.md" && grep -rn x . --include=*.py',True,"POSITIVE: unquoted flag beside a quoted decoy"),
     # Isolates the DOUBLE-QUOTE strip specifically. The class-name case above is
     # also covered by the left boundary, and the decoy case fires anyway (want=
     # True), so neither detects losing the DQ strip. This one is a DQ-quoted flag
     # with NO unquoted flag anywhere and NO hyphenated word — only the DQ strip
     # keeps it quiet.
     ('echo "pass --include=*.py to scope it"',False,"neg: DQ-quoted flag (isolates the DOUBLE-QUOTE strip)"),
     ("echo 'pass --include=*.py to scope it'",False,"neg: SQ-quoted flag (isolates the SINGLE-QUOTE strip)"),
     # --- word-splitting branches, installed 2026-08-08 ---
     ('set -- $spec',True,"POSITIVE set-dashdash word-splitting"),
     ('set -- ${spec}',True,"POSITIVE braced set-dashdash word-splitting"),
     ('R="--region us-gov-west-1"; aws logs describe-log-groups $R',True,"POSITIVE packed flag/value"),
     ("FLAGS='-v --color'; command $FLAGS",True,"POSITIVE packed flags"),
     ('echo $HOME',False,"neg: ordinary single-token expansion"),
     ('cd $DIR',False,"neg: ordinary directory expansion"),
     ('cat "$FILE"',False,"neg: quoted ordinary expansion"),
     ('args=(x y); set -- "${args[@]}"',False,"neg: correct array expansion"),
     ('set -- ${=spec}',False,"neg: explicit zsh splitting"),
     # --- v1's for-loop exclusion LIFTED 2026-08-16 ------------------------
     # This fixture asserted want=False under the label "out of v1 scope". That
     # was a SCOPE boundary, not a correctness finding, and the staged spec
     # (hooks/staged/bash-glob-metachar-guard.spec.md line 237) listed
     # `for r in $repos` as a REQUIRED positive fixture. Measured before
     # flipping it: 9 fires over 6,835 real corpus commands = 0.132% for this
     # branch alone (gate >10%, cleared by 76x), and ALL NINE are genuine --
     # every one a scalar built by command substitution (`REPOS=$(gh repo
     # list ...)`, `pids=$(pgrep ...)`) or a whitespace-separated literal
     # (`FILES="a b c"`) then iterated unquoted. Zero false positives; no fire
     # had an in-command array assignment, which is the one shape that would
     # make it benign. To restore v1 behaviour, set this back to False and drop
     # the _FOR_IN_SPLIT branch -- both are one line.
     ('for item in $ITEMS; do echo $item; done',True,"POSITIVE for-in split (v1 exclusion lifted)"),
     ('for f in ${files}; do :; done',True,"POSITIVE for-in braced form"),
     # Each negative below is covered by EXACTLY ONE mechanism of the new
     # branch, per tdd-mutation-testing item 30: a fixture that two mechanisms
     # cover cannot tell you whether either works, and its mutation reports
     # MISSED while the mechanism is the sole protection for an untested case.
     ('for f in $arr[@]; do :; done',False,"neg: zsh element-wise (isolates the RIGHT BOUNDARY)"),
     ('for x in ${=list}; do :; done',False,"neg: explicit split (isolates the BRACE-CONTENT class)"),
     ('endfor r in $repos',False,"neg: not command position (isolates the LEFT BOUNDARY)"),
     ('for i in $(seq 3); do :; done',False,"neg: command substitution"),
     ('for f in *.py; do :; done',False,"neg: glob, not this class"),
     ('command -- $FILES',False,"neg: generic file-list expansion is out of v1 scope"),
     ('R="--region us-gov-west-1"; command "$R"',False,"neg: packed value expanded as one intentional arg"),
     ('echo "try R=\'-v --color\'; cmd $R instead"',False,"neg: packed-flags example inside quoted prose"),
     # --- colon-modifier branch, installed 2026-08-27 ---------------------
     # Merges two specs staged 15 days apart (zsh-unbraced-colon-modifier 08-12,
     # zsh-colon-modifier-guard 08-27) for the same hazard. Measured 4 fires over
     # 11,252 real corpus commands = 0.036% for this branch alone, against the
     # specs' own >1% falsifier. ALL FOUR GENUINE, 0 false positives; 3 of the 4
     # were GIT's `<rev>:<path>` / `<src>:<dst>` syntax rather than docker tags.
     # A 5th fire WAS a false positive and is pinned below as the escape case.
     ('docker build -t "$ECR:latest" .',True,"POSITIVE colon-modifier: :l destroys the tag (the motivating incident)"),
     ('git log "$br:squashed"',True,"POSITIVE colon-modifier: :s ABORTS (bad substitution)"),
     ('git cat-file -s $sha:rules/git-hygiene.md 2>/dev/null',True,"POSITIVE colon-modifier: git <rev>:<path>, silenced by 2>/dev/null"),
     # Each negative below is covered by EXACTLY ONE mechanism of this branch.
     ('docker build -t "${ECR}:latest" .',False,"neg: BRACED form (isolates the no-brace requirement) — also the advisory's own suggested fix"),
     ('docker tag x "$IMG:prod"',False,"neg: `p` measured INERT (isolates the CHARACTER SET) — BOTH staged specs listed p and would fire here"),
     ('echo "BRACED - \\$ECR:latest triggers the zsh :l modifier"',False,"neg: BACKSLASH-ESCAPED $ (isolates the escape boundary) — a REAL corpus false positive: prose warning about this very hazard"),
     ('echo "$$foo:t"',False,"neg: $$ is the PID (isolates the PID boundary)"),
     ("echo '$ECR:latest'",False,"neg: single-quoted (isolates the SQ strip in _strip_unexpanded)"),
     ('curl "$host:8080/x"',False,"neg: digits are never modifiers")]
ok=True
for cmd,want,lbl in FIX:
    got=bool(fires(cmd)); good = got==want; ok &= good
    print(f"  {'PASS' if good else '**FAIL**':8s} want={want!s:5s} got={got!s:5s} {lbl}")
print(f"\nfixtures: {'ALL PASS' if ok else 'FAILURES — do not install'}")
if not ok or rate > 10.0:
    print(f"GATE FAILED (rate={rate:.2f}% fixtures_ok={ok})"); raise SystemExit(1)
print(f"GATE PASSED (rate={rate:.2f}%, fixtures OK)")
