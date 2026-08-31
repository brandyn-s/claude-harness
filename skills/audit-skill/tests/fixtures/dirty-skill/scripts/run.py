"""Real script in dirty-skill — D3a should NOT fire for this one.
Triggers C1 (fcntl import without platform-guard), C4 (literal HOME
string), C5 (read_text without encoding), C6 (argparse help with
unescaped %), C7 (no --help short-circuit in __main__), C9 (/tmp/
literal in Python source), and C10 (bare `subprocess.run(['bash',
...])` without _resolve_bash). All intentional — the fixture-corpus
discipline covers cross-platform checks. Note: no platform check
anywhere in this module.
"""
import argparse
import fcntl
import subprocess
import sys
from pathlib import Path

LOG_PATH = "$HOME/.dirty-skill.log"


def main():
    # C6 trigger: literal `%` in argparse help that isn't a valid
    # format spec. argparse._expand_help will crash on `--help`.
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratio", help="trim by 25% of total")
    args = ap.parse_args()

    # C5 + C9 trigger: read_text without encoding, /tmp/ literal.
    data = Path("/tmp/whatever.txt").read_text()

    # C10 trigger: bare `bash` subprocess invocation — Windows resolves
    # `bash` to the WSL launcher, which can't read `C:/...` paths. The
    # audit-skill oracle's `_resolve_bash` helper is the canonical
    # PATH-filtering fix.
    subprocess.run(["bash", "-c", "echo hello"], check=False)

    print(args, data, sys.argv, LOG_PATH, fcntl.LOCK_EX)


# C7 trigger: __main__ block consumes sys.argv (the assignment above)
# without a `--help` / `-h` short-circuit before main() runs. argparse
# DOES handle --help inside parse_args, but the C7 heuristic detects
# the lack of an explicit short-circuit — included here so the C7
# check itself is exercised by the fixture suite.
#
# Note: this fixture entry intentionally triggers C7 even though
# argparse is imported, because the C7 lint logic only skips files
# that mention ArgumentParser AND don't have argv access in a way
# that would race a hand-rolled parser. The fixture's argv access
# (line above) plus no explicit --help substring is what triggers.
if __name__ == "__main__":
    main()
