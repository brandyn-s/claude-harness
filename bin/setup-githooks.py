#!/usr/bin/env python3
"""Wire .githooks/ as this repo's hook path. Run once per clone.

Cross-platform: works on Linux, Mac, and Windows (any environment with
Python 3 and git available). Replaces the bash-only setup-githooks.sh
so contributors on Windows-without-WSL can run the setup too.
"""

import subprocess
import sys
from pathlib import Path


def main():
    try:
        repo = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True
        ).strip()
    except subprocess.CalledProcessError:
        sys.exit("error: not inside a git repo")
    except FileNotFoundError:
        sys.exit("error: git not found on PATH")

    hooks_dir = Path(repo) / ".githooks"
    if not hooks_dir.is_dir():
        sys.exit(f"error: {hooks_dir} does not exist")

    subprocess.check_call(
        ["git", "-C", repo, "config", "core.hooksPath", ".githooks"]
    )
    print(f"ok: core.hooksPath set to .githooks (this clone)")
    print(f"    pre-commit will now block on marketplace drift.")


if __name__ == "__main__":
    main()
