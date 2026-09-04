"""Gather-repos discovery: run 3 dynamic queries + Exa secondary."""
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

QUERIES = [
    # Q1: PostToolUse MCP output rewriting (advanced hook)
    'language:json "updatedMCPToolOutput" path:.claude',
    # Q2: Compaction-aware configs
    'language:json "PreCompact" "additionalContext" path:.claude',
    # Q3: Advanced agent config fields
    '"autoHaltOnTimelineFork" OR "disallowedTools" path:.claude',
]


def run_gh_search(query, per_page=30):
    """Run GitHub code search and return repo names."""
    cmd = [
        "gh", "api", "search/code",
        "-X", "GET",
        "--paginate",
        "-f", f"q={query}",
        "-f", f"per_page={per_page}",
        "--jq", ".items[].repository.full_name",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            print(f"  gh search error: {result.stderr[:200]}", file=sys.stderr)
            return []
        repos = list(set(result.stdout.strip().split("\n")))
        return [r for r in repos if r]
    except Exception as e:
        print(f"  gh search exception: {e}", file=sys.stderr)
        return []


def main():
    all_repos = {}
    for i, q in enumerate(QUERIES, 1):
        print(f"\n--- Query {i}: {q[:60]}... ---")
        repos = run_gh_search(q)
        print(f"  Found: {len(repos)} repos")
        for r in repos:
            if r not in all_repos:
                all_repos[r] = f"Q{i}"
            else:
                all_repos[r] += f"+Q{i}"

    print(f"\n--- TOTAL UNIQUE: {len(all_repos)} repos ---")
    for repo, source in sorted(all_repos.items()):
        print(f"  [{source}] {repo}")


if __name__ == "__main__":
    main()
