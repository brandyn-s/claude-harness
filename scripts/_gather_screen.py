"""Batch screen repos: get metadata + tree for Phase 1 scoring.

Usage:
    python _gather_screen.py            # screen the hardcoded REPOS list
    python _gather_screen.py owner/repo ...   # screen the listed repos instead
    python _gather_screen.py -h          # show this usage and exit

The agent contract documented in skills/gather-repos/SKILL.md is "run the
script as-is" — the optional positional args exist so an operator can spot-
check a single repo without editing the file. Unknown flags exit non-zero
with a usage message so a misuse cannot masquerade as "all UNREACHABLE".
"""
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

USAGE = (
    "Usage: python _gather_screen.py [owner/repo ...]\n"
    "  No args: screen the hardcoded REPOS list.\n"
    "  Args: must each be of the form owner/repo. Unknown flags are rejected."
)


def _parse_args(argv: list[str]) -> list[str] | None:
    """Return list of repos to screen, or None if usage was requested."""
    if not argv:
        return None
    if argv[0] in {"-h", "--help"}:
        print(USAGE)
        sys.exit(0)
    bad = [a for a in argv if a.startswith("-") or "/" not in a]
    if bad:
        print(f"ERROR: unrecognized argument(s): {bad}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    return argv


# Repos to screen (unique from Q1+Q2, excluding obvious forks/projects)
DEFAULT_REPOS = [
    "ya-luotao/claude-agent-sdk-ruby",
    "DeL-TaiseiOzaki/claude-code-orchestra",
    "esmevane/oneiros",
    "yesitsfebreeze/shard",
    "zeropsio/zcp",
    "joshholl/frollz",
    "ribon-org/ribon",
    "sandk0/fancai",
    "emirrtopaloglu/claude-code-virtuoso",
    "kame3niku9/claude-orchestra-template",
    "morixxfoxdata/claude-code-template",
]

_override = _parse_args(sys.argv[1:])
REPOS = _override if _override is not None else DEFAULT_REPOS


def gh_api(endpoint, jq_filter="."):
    try:
        r = subprocess.run(
            ["gh", "api", endpoint, "--jq", jq_filter],
            capture_output=True, timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
        return r.stdout.decode("utf-8", errors="replace").strip() if r.returncode == 0 else None
    except Exception:
        return None


def score_tree(tree_text):
    """Phase 1 score: count buckets present."""
    score = 0
    buckets = {
        "hooks": False, "rules": False, "skills": False,
        "agents": False, "memory": False, "config": False,
    }
    if not tree_text:
        return 0, buckets
    lines = tree_text.lower()
    if "hooks/" in lines or "hooks\\" in lines:
        buckets["hooks"] = True; score += 1
    if "rules/" in lines or "rules\\" in lines:
        buckets["rules"] = True; score += 1
    if "skill" in lines and ".md" in lines:
        buckets["skills"] = True; score += 1
    if "agents/" in lines or "agents\\" in lines:
        buckets["agents"] = True; score += 1
    if "memory/" in lines or "topics/" in lines:
        buckets["memory"] = True; score += 1
    if "settings.json" in lines:
        buckets["config"] = True; score += 1
    return score, buckets


for repo in REPOS:
    # Metadata
    meta = gh_api(f"repos/{repo}",
        '[.stargazers_count, .description // "(none)", .pushed_at[:10], .size] | @tsv')
    if not meta:
        print(f"  {repo}: UNREACHABLE")
        continue

    parts = meta.split("\t")
    stars = parts[0] if len(parts) > 0 else "?"
    desc = parts[1][:60] if len(parts) > 1 else "?"
    pushed = parts[2] if len(parts) > 2 else "?"
    size_kb = parts[3] if len(parts) > 3 else "?"

    # Tree (first 200 entries)
    tree = gh_api(f"repos/{repo}/git/trees/HEAD?recursive=1",
        "[.tree[].path] | .[:200] | .[]")

    score, buckets = score_tree(tree or "")
    bucket_str = " ".join(k.upper() for k, v in buckets.items() if v)

    # File count
    file_count = len(tree.split("\n")) if tree else 0

    print(f"  {repo}: {stars}* | {file_count}f | score {score}/6 [{bucket_str}] | {desc} | pushed {pushed}")


print("\nDone.")
