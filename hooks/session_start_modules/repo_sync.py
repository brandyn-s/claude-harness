"""Sync tracked git repos at session start."""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .concurrent_session import has_concurrent_sessions

# The environment catalog lives beside the hooks, one level up from this package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _environment_catalog import load_section, repo_entries

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
CLAUDE_CONFIG_PATH = Path.home() / ".claude"
LAST_CHECKPOINT_ARTIFACT = CLAUDE_CONFIG_PATH / ".last-auto-checkpoint.json"


def _last_checkpoint_artifact() -> Path:
    """Resolve the recovery-artifact path, honouring an env override.

    The default is LIVE state that a real session reads to recover work a
    parallel session-start checkpointed away. Without an override the test suite
    writes its own fixture paths over it: measured 2026-08-15, a run of
    `hooks/test-hooks/` replaced the live artifact's contents with a
    pytest tmp repo path WHILE ~/.claude was wedged mid-rebase, destroying the
    pointer to the real `checkpoint/<ts>` branch during the incident it exists
    to help recover from. The branch survived; the pointer did not.

    Same class the suite's own conftest already names for hook telemetry:
    "the instrument that guard keep/prune audits read had been contaminated by
    the guard's own tests." conftest points this at a tmp path for the suite.
    """
    override = os.environ.get("CLAUDE_LAST_CHECKPOINT_ARTIFACT")
    return Path(override) if override else LAST_CHECKPOINT_ARTIFACT


def _startupinfo():
    if sys.platform != "win32":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si


def _porcelain_paths(stdout: str) -> list[str]:
    """`git status --porcelain` stdout -> the paths, prefixes stripped.

    Porcelain emits a FIXED 3-char prefix per line: two status chars (XY)
    then a space. A worktree-only modification is `" M "` — the X slot is a
    SPACE. So the blob must be split WITHOUT touching leading whitespace:
    `stdout.strip().split("\\n")` strips the first line's leading space, the
    prefix becomes 2 chars, and the `[3:]` slice then eats one character of
    the path itself.

    2026-07-24: that is exactly how the auto-checkpoint recovery artifact
    (and the session-start banner that prints it) advertised recovery for
    `opics/session-friction-patterns.md` — a path that does not exist, so a
    pasted `git checkout <branch> -- <path>` fails "pathspec did not match".
    Only the FIRST line was affected (lines 2..N keep their space), which is
    why a single-file artifact was the only place it ever showed.

    splitlines() also drops the empty trailing element that split("\\n")
    leaves, so the empty-line filter is belt-and-braces.
    """
    return [line[3:] for line in stdout.splitlines() if line.strip()]


#: Paths that hook-rendered or per-machine state writes keep PERMANENTLY dirty.
#: A gate keyed on raw `git status` therefore has a nonzero steady-state floor
#: and is engaged forever while its enabling flag still reads "on" -- it fails
#: SILENT, so nobody gets an alarm; they get a sync that appears configured and
#: quietly never runs (grading-discipline.md, "gate a destructive action on a
#: counter or flag": measure the signal's floor BEFORE shipping the gate).
#:
#: Measured 2026-08-06: ~/Documents/knowledge-base was skipped at EVERY session
#: start, its only dirty file being `topics/session-friction-patterns.md` -- a
#: DERIVED artifact re-rendered by hooks/session-stop.py from a per-session
#: spool, and not gitignored, so git reports it dirty after every session. With
#: concurrent sessions normal on this host (4 live at the time; PR #1902 notes 7
#: is normal), `is_dirty and has_concurrent_sessions()` could never be False.
#:
#: SIBLING COPIES -- keep in sync (pinned by
#: test_repo_sync.py::test_transient_dirt_covers_sibling_copies):
#:   hooks/worktree-enforcement.py  `_TRANSIENT_MARKERS`
#:   hooks/post-merge-sync.py       `_is_repo_dirty`'s `transients`
_TRANSIENT_DIRT = (
    "settings.json", "settings.local.json", "last-distill.json",
    "distill-history.jsonl", "mcp-needs-auth-cache.json",
    "gh-pr-status-cache.json", "topic-checksums.json",
    "recent-sessions.md", "session-friction-patterns.md",
    ".precompact-state.json", "daemon.log",
    "/.session-active/", "/projects/",
)


def _content_dirty_paths(stdout: str) -> list[str]:
    """Porcelain paths EXCLUDING hook-managed / per-machine transients.

    Use this -- not raw `git status` output -- for any GATE decision. Raw dirt
    answers "did anything change?"; a gate needs "is there WORK here I could
    destroy?", and a re-rendered spool artifact is not work.

    PATH SPACE: porcelain emits REPO-RELATIVE paths (`.session-active/x.json`)
    while the sibling marker lists were written against ABSOLUTE paths, so their
    directory markers carry a leading slash (`/.session-active/`). Matching the
    two directly silently fails for every directory marker -- caught by
    test_transient_only_dirt_does_not_engage_the_concurrent_gate, not by reading
    the tuple. Prepending "/" reconciles the spaces AND makes those markers
    anchor at the repo root, so `/projects/` matches a top-level `projects/`
    without also matching `skills/foo/projects/bar`.
    """
    return [
        p for p in _porcelain_paths(stdout)
        if not any(t in "/" + p for t in _TRANSIENT_DIRT)
    ]


def _write_checkpoint_artifact(
    repo_str: str, checkpoint_branch: str, ts: str, files: list[str]
) -> None:
    """Record the last auto-checkpoint for active-session recovery.

    The active session can read ~/.claude/.last-auto-checkpoint.json on the
    next prompt, see that its working-tree edits were checkpointed by a
    parallel session-start hook, and recover via:
      git -C <repo> checkout <branch> -- <file>
    """
    artifact = {
        "repo": repo_str,
        "branch": checkpoint_branch,
        "timestamp": ts,
        "files": files[:50],  # cap for readability
        "recovery_hint": (
            f"git -C {repo_str} checkout {checkpoint_branch} -- <file>"
        ),
    }
    try:
        _last_checkpoint_artifact().write_text(
            json.dumps(artifact, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _prune_stale_checkpoints(_git, max_age_days: int = 7) -> int:
    """Delete checkpoint/* branches whose tip commit is older than max_age_days.

    The auto-checkpoint mechanism in _sync_one_repo creates `checkpoint/<ts>`
    branches every time main is dirty at session start, to preserve uncommitted
    work as a commit before stashing. Without cleanup these accumulate forever:
    knowledge-base hit 220 stale checkpoint branches from ~220 sessions
    (2026-05-06 /pr-fix audit). Recovery is per the artifact written by
    _write_checkpoint_artifact — once the file evolves past 7 days, the
    snapshot is no longer load-bearing.

    Returns the count of branches deleted.
    """
    import time

    cutoff = int(time.time()) - max_age_days * 86400
    listing = _git([
        "for-each-ref",
        "--format=%(refname:short) %(committerdate:unix)",
        "refs/heads/checkpoint/",
    ])
    if listing.returncode != 0 or not listing.stdout.strip():
        return 0
    stale: list[str] = []
    for line in listing.stdout.strip().splitlines():
        parts = line.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        branch, ts_str = parts
        try:
            if int(ts_str) < cutoff:
                stale.append(branch)
        except ValueError:
            continue
    if not stale:
        return 0
    deleted = 0
    for branch in stale:
        r = _git(["branch", "-D", branch])
        if r.returncode == 0:
            deleted += 1
    return deleted


#: Bases a gone branch's tip may be merged into for deletion to be safe.
_ACCEPTED_BASES = ("origin/main", "origin/master", "main", "master")


def _gone_branch_is_recoverable(_git, branch: str) -> bool:
    """True only if `branch`'s tip is already contained in an accepted base.

    `[gone]` says the UPSTREAM ref disappeared. It says NOTHING about commits added
    locally after the last push, so it is not evidence that deletion is safe.

    Verified on a disposable repo 2026-07-26 (probe in the H3 fixture): a branch
    with one pushed commit plus one local-only commit reports `[gone]` after the
    remote branch is deleted and `fetch --prune` runs, while
    `merge-base --is-ancestor <branch> main` is FALSE -- and the previous
    `git branch -D` destroyed the only named reference to that local-only commit.
    Reflog was the sole remaining path back, which is a time-limited accident, not
    a safety mechanism.
    """
    for base in _ACCEPTED_BASES:
        # Does the base even exist in this repo?
        if _git(["rev-parse", "--verify", "--quiet", base]).returncode != 0:
            continue
        if _git(["merge-base", "--is-ancestor", branch, base]).returncode == 0:
            return True
    return False


def _branch_work_is_upstream(_git, branch: str) -> bool:
    """True if every commit on `branch` already has its patch upstream.

    `_gone_branch_is_recoverable` above answers a DIFFERENT question with
    ancestry, and ancestry CANNOT answer this one on a squash-merge repo: the
    squash lands the content under a NEW sha, so a fully merged branch is never
    an ancestor of main. `git cherry` compares PATCH-IDs instead and reports
    `-` for a commit whose content is already upstream, `+` for one that is not.

    Measured 2026-08-06 on the real merged branch `docs/ssr-batch-diagnostics`
    (landed as the config repo's #1905):
        merge-base --is-ancestor <branch> origin/main  -> FALSE  (the trap)
        git cherry origin/main <branch>                -> "- 4532a7a3"  (merged)

    Deliberately CONSERVATIVE -- any `+` line, a failed cherry, or no readable
    base returns False. A false NEGATIVE costs only a warning we would have
    emitted anyway; a false POSITIVE would switch a SHARED working tree off a
    branch that still holds real work. The asymmetry is the whole design.

    Note this is patch-id based, so a branch whose several commits were squashed
    into one upstream commit still reports `+` and is treated as unmerged. That
    is the safe direction; the caller only warns.
    """
    for base in _ACCEPTED_BASES:
        if _git(["rev-parse", "--verify", "--quiet", base]).returncode != 0:
            continue
        cherry = _git(["cherry", base, branch])
        if cherry.returncode != 0:
            continue
        lines = [ln for ln in cherry.stdout.splitlines() if ln.strip()]
        if not lines:
            # NO commits unique to this branch -- a freshly-created branch, not
            # a merged one. `git cherry` cannot tell those apart (both are
            # "nothing that isn't upstream"), so the caller must, and the
            # distinction is load-bearing: yanking a just-created `feat/x` back
            # to main at the next session start would destroy the user's
            # deliberate branching. Only a branch that HAS commits, all of them
            # already upstream, counts as done.
            return False
        # First base that answers wins. Falling through to a LOCAL base after
        # origin/* already said `+` cannot turn "not upstream" into "upstream"
        # (a local base is behind its remote), so returning here is safe.
        return not any(ln.startswith("+") for ln in lines)
    return False


def _prune_gone_branches(_git) -> int:
    """Delete local branches whose upstream is gone AND whose tip is already merged.

    Squash-merge via `gh pr merge --auto --squash --delete-branch` deletes the
    remote branch but leaves the local clone tracking a now-gone upstream.
    `git fetch --prune` marks them `[gone]`; this function deletes the locals.
    Without it, repos accumulate hundreds of stale branches: three tracked
    repos held 164, 107 and 98 at the 2026-05-06 /pr-fix audit.

    CORRECTED 2026-08-05: this docstring used to claim `--prune` was "already
    run via the rebase below". It was NOT -- both fetch paths (this module's
    `_sync_one_repo` and `hooks/sync-repo.py`'s `cmd_pull`) ran a bare
    `git fetch origin <branch>`, so nothing ever pruned and no branch ever
    acquired its `[gone]` marker on a real clone. This function was therefore
    reachable but effectively inert against the exact case it was written for,
    and the omission was invisible because the tests hand-run
    `git fetch -q --prune` in their setup. Both fetch sites now pass `--prune`.
    Measured cost of the gap: 9 clones simultaneously unsyncable on 2026-08-05,
    each reporting a hard "fetch failed: couldn't find remote ref", plus
    hundreds of accumulated stale locals (the knowledge base ~85, the config
    repo ~21).

    SAFETY CHANGED 2026-07-26 (audit finding H3). This used to run `git branch -D`
    on every `[gone]` branch, justified by "gone-upstream means GitHub already
    accepted and removed the remote -- local-only divergent history is not
    possible". That reasoning is FALSE: `[gone]` is a fact about the upstream ref,
    not about local history, so any commit made after the last push is invisible to
    it. Reproduced on a disposable repo -- a `[gone]` branch carrying one
    local-only commit was force-deleted, leaving reflog as the only way back.

    Three guards now, in order:
      1. ancestry -- the tip must already be contained in an accepted base;
      2. a recovery ref is written under refs/gone-recovery/ BEFORE deletion;
      3. `-d` (safe delete) instead of `-D`, so git refuses anything unmerged even
         if guards 1-2 were somehow wrong.

    A branch that fails the ancestry check is LEFT ALONE. Accumulating a stale
    branch is a cosmetic problem; deleting someone's only reference to unpushed
    work is not.
    """
    listing = _git([
        "for-each-ref",
        "--format=%(refname:short) %(upstream:track)",
        "refs/heads/",
    ])
    if listing.returncode != 0:
        return 0
    gone: list[str] = []
    for line in listing.stdout.strip().splitlines():
        if "[gone]" in line.lower():
            branch = line.split(" ", 1)[0]
            if branch and branch not in ("main", "master"):
                gone.append(branch)
    if not gone:
        return 0
    deleted = 0
    for branch in gone:
        if not _gone_branch_is_recoverable(_git, branch):
            # Unmerged local work: preserve the branch.
            continue
        # Recovery ref first, so even a wrong ancestry verdict is undoable.
        _git(["update-ref", f"refs/gone-recovery/{branch}", branch])
        # -d, not -D: git independently refuses an unmerged branch.
        r = _git(["branch", "-d", branch])
        if r.returncode == 0:
            deleted += 1
        else:
            # Deletion refused after all -- drop the recovery ref we just made so
            # the namespace does not fill with refs for branches still present.
            _git(["update-ref", "-d", f"refs/gone-recovery/{branch}"])
    return deleted


def _has_unfenced_conflict_marker(repo: Path, rel_path: str) -> bool:
    """True if `rel_path` has a `<<<<<<<` marker OUTSIDE a fenced code block.

    A documentation file that legitimately QUOTES conflict markers puts them
    inside a ``` fence. Reporting those as "resolve before committing" produces a
    warning with nothing to resolve, every session, forever.

    Conservative by design: on any read error, return True so a genuinely broken
    file is never silently dropped from the warning. Requires the FULL marker
    shape (7 chars at line start) — the same shape git itself writes.
    """
    try:
        text = (repo / rel_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True  # unreadable: warn rather than hide

    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        # Toggle on ``` or ~~~ fences (either delimiter, any info string).
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("<<<<<<<"):
            return True
    return False


def _sync_one_repo(repo: Path, self_session_id: str | None = None) -> list[str]:
    """Sync a single repo. Returns warnings list."""
    if not (repo / ".git").exists():
        return []
    warnings: list[str] = []
    repo_name = repo.name
    repo_str = str(repo)
    def _git(args, _rs=repo_str):
        return subprocess.run(
            ["git"] + args,
            cwd=_rs,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=_startupinfo(),
        )
    # Activate a committed git-hooks directory if the repo ships one (e.g. the
    # knowledge-base's .githooks/pre-commit finalize gate). A committed hook is
    # inert until core.hooksPath points at it, and that wiring is one-time per
    # clone — so set it here, idempotently, so the gate fires no matter who or
    # what commits. Opportunistic: non-load-bearing, failures are swallowed.
    try:
        if (repo / ".githooks").is_dir():
            current = _git(["config", "--get", "core.hooksPath"])
            if current.stdout.strip() != ".githooks":
                _git(["config", "core.hooksPath", ".githooks"])
    except Exception:
        pass
    try:
        # Branch hygiene: prune stale checkpoint snapshots (>7d) and gone-upstream
        # branches. Both run before the dirty-state checks so the auto-checkpoint
        # logic below doesn't race with cleanup. Failures are silent — they're
        # opportunistic cleanup, not load-bearing.
        try:
            _prune_stale_checkpoints(_git)
            _prune_gone_branches(_git)
        except Exception:
            pass

        # An interrupted rebase is detected by ITS OWN STATE DIRECTORY, because the
        # unmerged-file check below CANNOT see one.
        #
        # `--diff-filter=U` reports unmerged INDEX entries. A git that was KILLED
        # mid-rebase has already written conflict markers into the WORKTREE but not
        # those index entries, so the filter returns ZERO while .git/rebase-merge/
        # exists — and the recovery below is blind to exactly the state it exists to
        # clear. The marker it keys on is PRODUCED by the step that was interrupted,
        # so its absence is self-concealing.
        #
        # Measured 2026-08-15 on this host: ~/.claude sat wedged for ~20 minutes at
        # msgnum=1 of end=276 with 0 unmerged files and settings.json carrying 4 raw
        # conflict blocks, so every new session read an UNPARSEABLE live config and
        # nothing reported it. Recovery required a manual `git rebase --abort`.
        #
        # #1998 stopped this hook from CREATING that state (the path fast-forwards
        # now and never rebases). This is the other half: a wedge arriving from any
        # other source — an interrupted manual rebase, a crashed session, a stale
        # hook, an interrupted `git am` — still leaves the checkout unusable, and
        # after #1998 an external source is the ONLY way to reach it.
        #
        # Use `rev-parse --git-path` rather than joining repo/".git"/…: in a linked
        # worktree `.git` is a FILE and the real state lives in the common dir, so a
        # path join silently never matches.
        for _state in ("rebase-merge", "rebase-apply"):
            probe = _git(["rev-parse", "--git-path", _state])
            if probe.returncode != 0:
                continue
            state_path = Path(probe.stdout.strip())
            if not state_path.is_absolute():
                state_path = repo / state_path
            if not state_path.exists():
                continue
            abort = _git(["rebase", "--abort"])
            if abort.returncode == 0:
                warnings.append(
                    f"[{repo_name}] Cleared an interrupted rebase ({_state}) — working "
                    "tree restored, no commits lost."
                )
            else:
                # Never swallow this. A repo stuck mid-rebase may hold conflict
                # markers in live config (settings.json, rules/) and cannot be
                # operated on by git until it is cleared.
                warnings.append(
                    f"[{repo_name}] STUCK MID-REBASE and `git rebase --abort` FAILED: "
                    f"{(abort.stderr or abort.stdout).strip()[:200]} — tracked files may "
                    f"hold conflict markers. Run `git -C {repo_str} rebase --abort`."
                )
            break

        unmerged = _git(["diff", "--name-only", "--diff-filter=U"])
        if unmerged.returncode == 0 and unmerged.stdout.strip():
            files = unmerged.stdout.strip().split("\n")
            _git(["rebase", "--abort"])
            warnings.append(
                f"[{repo_name}] Had {len(files)} unmerged file(s) from failed rebase - aborted. "
                f"Files: {', '.join(files[:3])}"
            )
        # Markers COMMITTED into a file (distinct from the mid-merge state that
        # `--diff-filter=U` above catches authoritatively). This stays a textual
        # grep because that is the only way to see a badly-resolved conflict that
        # already landed — but it MUST ignore markers inside a fenced code block.
        #
        # WHY: a knowledge-base topic that DOCUMENTS a conflict quotes the real
        # markers inside a ```text fence. On 2026-07-29 this fired every session
        # on topics/public-exposure-audit.md, which explains a nested lockfile
        # conflict — `git ls-files -u` was empty and .git/MERGE_HEAD absent, so
        # there was nothing to resolve. An unresolvable warning trains the
        # operator to ignore the channel, which is worse than no warning.
        conflict_grep = _git(["grep", "-l", "^<<<<<<<"])
        if conflict_grep.returncode == 0 and conflict_grep.stdout.strip():
            conflict_files = [
                f for f in conflict_grep.stdout.strip().split("\n")
                if f and _has_unfenced_conflict_marker(repo, f)
            ]
            if conflict_files:
                warnings.append(
                    f"[{repo_name}] Has merge conflict markers in: "
                    f"{', '.join(conflict_files[:3])}. Resolve before committing."
                )
        # Clean up old auto-stashes only if they have a matching
        # checkpoint branch (meaning the work was preserved as a commit).
        # Without a checkpoint, the stash may be the only copy of that work.
        stash_list = _git(["stash", "list"])
        if stash_list.returncode == 0 and stash_list.stdout.strip():
            branch_list = _git(["branch", "--list", "checkpoint/*"])
            has_checkpoints = (
                branch_list.returncode == 0
                and branch_list.stdout.strip()
            )
            lines = stash_list.stdout.strip().split("\n")
            for i in range(len(lines) - 1, -1, -1):
                if "auto-stash" in lines[i] and has_checkpoints:
                    _git(["stash", "drop", f"stash@{{{i}}}"])
        status = _git(["status", "--porcelain"])
        is_dirty = status.returncode == 0 and status.stdout.strip()
        branch = _git(["branch", "--show-current"])
        current_branch = branch.stdout.strip() if branch.returncode == 0 else ""
        if current_branch not in ("main", "master"):
            # Stranded-checkpoint recovery. A prior session's auto-checkpoint
            # (below) can leave HEAD on checkpoint/<ts> when its checkout-back
            # fails (Windows file lock, concurrent .git access). This branch
            # used to early-return forever — so main never rebased and real
            # work piled up uncommitted on the checkpoint branch (2026-05-29
            # root-cause analysis: ~/.claude stranded ~2 days, 30+ dirty files).
            # Recover when safe; warn loudly when not. Intentional work branches
            # (feat/*, fix/*, chore/*) are left untouched as before.
            if not current_branch.startswith("checkpoint/"):
                # This used to `return warnings` SILENTLY for every non-checkpoint
                # branch, which is how a repo gets stranded indefinitely: the
                # syncer declines and says nothing, so WARNING and SYNCING are
                # fully decoupled -- other modules shout about the branch while
                # the one component that could act quietly opts out.
                #
                # Measured 2026-08-06: ~/.claude sat on `docs/ssr-batch-
                # diagnostics` (merged as #1905) 14 commits behind origin/main.
                # Those 14 included PR #1902, whose entire purpose was fixing
                # three SessionStart checker false positives -- so the banner was
                # being produced BY the stale checkers #1902 had already fixed,
                # and #1902's own closing note said "~/.claude must sync after
                # merge for these to take effect". When a checkout of the harness
                # falls behind, the diagnostics regress with it.
                #
                # Scoped tight to stay noise-free: a branch with UNMERGED commits
                # is normal mid-development in most repos, so it stays silent
                # exactly as before. Only a branch whose work is already upstream
                # -- done, nothing to lose -- is acted on or reported.
                if not _branch_work_is_upstream(_git, current_branch):
                    return warnings
                if is_dirty:
                    n = len(_porcelain_paths(status.stdout))
                    warnings.append(
                        f"[{repo_name}] Branch '{current_branch}' is fully merged "
                        f"upstream, but {n} uncommitted file(s) block the return "
                        f"to main -- so local main cannot advance and the "
                        f"CHECKED-OUT hooks/skills (the ones that run) go stale. "
                        f"Reconcile the already-upstream files, then /pr-fix."
                    )
                    return warnings
                recover = _git(["checkout", "main"])
                if recover.returncode != 0:
                    warnings.append(
                        f"[{repo_name}] Branch '{current_branch}' is fully merged "
                        f"but auto-return to main failed: "
                        f"{recover.stderr.strip()[:80]}. Run /pr-fix."
                    )
                    return warnings
                warnings.append(
                    f"[{repo_name}] Returned from fully-merged branch "
                    f"'{current_branch}' -> main (clean tree, no unmerged "
                    f"commits). Resuming sync."
                )
                current_branch = "main"
                # is_dirty is False on this path, so the auto-checkpoint block
                # below is skipped -- same invariant as the checkpoint recovery.
            else:
                # `else`, not a fall-through: the merged-branch path above ends
                # with current_branch = "main", and letting it drop into here
                # would re-run `checkout main` as a no-op and then emit
                # "Recovered from stranded checkpoint branch 'main' -> main".
                # The two recovery shapes are mutually exclusive by construction.
                if is_dirty:
                    n = len(status.stdout.strip().split("\n"))
                    warnings.append(
                        f"[{repo_name}] STRANDED on '{current_branch}' with {n} "
                        f"uncommitted file(s). NOT auto-recovering — that would risk "
                        f"your edits. Run /pr-fix to land them and return to main."
                    )
                    return warnings
                # Clean tree: the checkpoint commit already holds any earlier
                # snapshot, so returning to main loses nothing. Resume normal sync.
                recover = _git(["checkout", "main"])
                if recover.returncode != 0:
                    warnings.append(
                        f"[{repo_name}] Stranded on '{current_branch}'; auto-return "
                        f"to main failed: {recover.stderr.strip()[:80]}. Run /pr-fix."
                    )
                    return warnings
                warnings.append(
                    f"[{repo_name}] Recovered from stranded checkpoint branch "
                    f"'{current_branch}' -> main (working tree was clean)."
                )
                current_branch = "main"
                # Fall through to fetch + rebase. is_dirty is False here, so the
                # auto-checkpoint block below is skipped.
        # Skip checkpoint+rebase entirely if another Claude session is active
        # (2026-04-26 incident: parallel session's repo_sync silently
        # checkpointed the active session's WIP onto a branch, leaving the
        # active session's working tree at main HEAD).
        #
        # Gate on CONTENT dirt, NOT raw dirt. Raw `git status` counts
        # hook-rendered artifacts that are dirty after EVERY session, which gave
        # this interlock a nonzero steady-state floor: with a concurrent session
        # present (normal on this host), the condition could never be False, so
        # the sync never ran while its enabling flag still read "on".
        #
        # Measured 2026-08-06: ~/Documents/knowledge-base was skipped at every
        # session start on the strength of exactly ONE permanently-dirty file,
        # `topics/session-friction-patterns.md` -- a derived artifact re-rendered
        # by hooks/session-stop.py from a per-session spool, and not gitignored.
        # The message said "another session is active", which reads TRANSIENT,
        # while the blocking condition was permanent. That is the failure shape
        # grading-discipline.md flags for gates: it fails SILENT, so nobody gets
        # an alarm -- they get a feature that appears configured and does nothing.
        #
        # `is_dirty` (raw) still drives the checkpoint+stash machinery below,
        # which already knows how to preserve a dirty tree across the rebase.
        # Only the GATE's signal changes.
        content_dirty = _content_dirty_paths(status.stdout)
        if content_dirty and has_concurrent_sessions(self_session_id):
            warnings.append(
                f"[{repo_name}] Skipped auto-checkpoint+rebase: another session "
                f"is active. {len(content_dirty)} dirty content file(s) "
                f"preserved in working tree."
            )
            return warnings
        # The fetch's return code is CHECKED (audit finding M8, 2026-07-26).
        # Ignoring it meant a failed fetch (offline, auth expiry, transient
        # network) fell through to a rebase against the STALE local
        # remote-tracking ref. That silently rebases onto old upstream and
        # reports success -- the same "deploy-from-stale-ref" shape
        # git-hygiene.md warns about. On fetch failure the correct move is to
        # skip the rebase entirely and say so.
        #
        # The `--prune` fetch below runs FIRST and is load-bearing (2026-08-05).
        # It is what _prune_gone_branches() already ASSUMED was happening --
        # an assumption that was FALSE: neither this fetch nor sync-repo.py's
        # passed --prune, so a merged-and-deleted branch never got its `[gone]`
        # marker and the prune logic could never fire on it. The tests passed
        # only because they hand-run `git fetch -q --prune` in setup, so the
        # harness supplied the one step production omitted.
        _git(["fetch", "origin", "--prune"])
        fetch = _git(["fetch", "origin", current_branch])
        if fetch.returncode != 0:
            # NOTE: no merged-and-deleted special case here, deliberately.
            # This code is reachable ONLY on main/master (the gate at the top
            # early-returns any other branch), and main is never deleted
            # upstream -- so a "your branch was merged and deleted" message
            # would be unreachable dead code. That case belongs to
            # sync-repo.py's cmd_pull, which DOES run on feature branches and
            # is where all nine 2026-08-05 failures surfaced.
            warnings.append(
                f"[{repo_name}] Fetch FAILED ({fetch.stderr.strip()[:160]}); "
                f"skipped rebase rather than rebasing onto a stale "
                f"origin/{current_branch}."
            )
            # No stash to restore: after the checkpoint/fetch reorder the fetch
            # runs BEFORE anything stashes, so `stashed` is provably False here.
            # The former `if stashed: pop` on this path was dead once the order
            # changed, and keeping it forced an initialiser to exist purely to
            # satisfy unreachable code.
            return warnings

        # DECIDE BEFORE DISTURBING THE TREE. The auto-checkpoint below COMMITS the
        # working tree onto a checkpoint/<ts> branch and then checks out back, which
        # CLEARS the tree. That is only worth doing if something is about to move the
        # branch -- and after #1998 nothing does unless this is a fast-forward.
        #
        # Before this gate, the order was checkpoint -> fetch -> decide, so on a
        # permanently-divergent checkout every lone session start paid the full
        # checkpoint cost (commit the user's WIP to a branch, clear the tree, write a
        # recovery artifact) to protect a fast-forward that was then SKIPPED 126 lines
        # later. It can never be protecting anything there: --ff-only will refuse
        # forever while the arc is divergent.
        #
        # Measured on this host 2026-08-15: ~/.claude is 278 commits ahead, so this is
        # its steady state, not an edge case. Concretely it also reverted a surgical
        # per-path deploy of #1998/#1999 -- the deployed files read as dirt, got
        # committed to a checkpoint branch, and the live hook silently returned to the
        # pre-fix version, re-arming the very incident those PRs fixed.
        #
        # The fetch above is READ-ONLY with respect to the working tree (it updates
        # remote-tracking refs only), so it is safe to run first and is required here:
        # can_ff compares against origin/<branch>, which must be current or the gate
        # decides on a stale ref.
        # Only fast-forward. This code path is main/master ONLY (gate above),
        # and git-hygiene FORBIDS committing directly to main -- so commits
        # that exist locally and not upstream are anomalous here by policy, and
        # replaying them is not a catch-up, it is a divergent-arc rebase that
        # cannot converge.
        #
        # The previous unconditional `git rebase origin/<branch>` did exactly
        # that. Measured on this host 2026-08-15: `git cherry origin/main HEAD`
        # reported +276/-0, so every session start replayed 276 commits, hit a
        # semantic conflict, and aborted. Two costs, and the second is the one
        # that matters: (1) guaranteed wasted work every boot; (2) a WINDOW,
        # between the rebase starting and the abort, in which tracked files
        # hold conflict markers -- and SessionStart is precisely when other
        # sessions load ambient rules. Four rule files under rules/ were
        # observed carrying `<<<<<<<` markers during that window.
        #
        # Fast-forwarding when possible preserves the useful behavior (a plain
        # catch-up) and creates no conflict window at all, because --ff-only
        # either succeeds cleanly or refuses without touching the tree.
        can_ff = _git(
            ["merge-base", "--is-ancestor", "HEAD", f"origin/{current_branch}"]
        ).returncode == 0
        if not can_ff:
            ahead = _git(
                ["rev-list", "--count", f"origin/{current_branch}..HEAD"]
            ).stdout.strip() or "?"
            behind = _git(
                ["rev-list", "--count", f"HEAD..origin/{current_branch}"]
            ).stdout.strip() or "?"
            warnings.append(
                f"[{repo_name}] {ahead} local commit(s) are not upstream and "
                f"{behind} upstream commit(s) are not local, so "
                f"origin/{current_branch} cannot be fast-forwarded. Skipped the "
                "rebase deliberately: replaying a divergent arc here conflicts "
                "every boot and leaves conflict markers in tracked files while "
                "it runs. To pick up a specific upstream change, deploy that "
                "path surgically: `git checkout origin/"
                f"{current_branch} -- <path>` then `git restore --staged <path>`."
            )
            return warnings

        stashed = False
        if is_dirty:
            # Checkpoint uncommitted work as a commit on a temp branch
            # before stashing — prevents silent loss of multi-file edits
            # across session boundaries (absorb v3 incident 2026-04-05:
            # 8 files of edits lost because stash only partially restored).
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            checkpoint_branch = f"checkpoint/{ts}"
            # Capture file list BEFORE the checkpoint commit so the artifact
            # can list what was preserved.
            dirty_files = _porcelain_paths(status.stdout)

            # Each step's return code is CHECKED (audit finding M8, 2026-07-26).
            # These three ran with their rc discarded, which is unsafe in a
            # specific way: if `checkout -b` fails (name collision from a
            # same-second checkpoint, index lock from a concurrent session), the
            # subsequent `add -A` and `commit` execute on whatever branch is
            # ACTUALLY checked out -- committing the user's work somewhere
            # unintended and then rebasing that branch. Abort the checkpoint
            # instead and preserve the dirty tree; a skipped checkpoint is
            # recoverable, a commit on the wrong branch is not.
            co = _git(["checkout", "-b", checkpoint_branch])
            if co.returncode != 0:
                warnings.append(
                    f"[{repo_name}] Auto-checkpoint ABORTED: could not create "
                    f"'{checkpoint_branch}' ({co.stderr.strip()[:160]}). "
                    f"{len(dirty_files)} dirty file(s) left untouched in the "
                    f"working tree — nothing was committed or rebased."
                )
                return warnings

            add = _git(["add", "-A"])
            if add.returncode != 0:
                # Return to the original branch before bailing so we do not
                # strand the session on the checkpoint branch.
                _git(["checkout", current_branch])
                _git(["branch", "-D", checkpoint_branch])
                warnings.append(
                    f"[{repo_name}] Auto-checkpoint ABORTED: `git add -A` failed "
                    f"({add.stderr.strip()[:160]}). Dirty files preserved; "
                    f"returned to '{current_branch}'."
                )
                return warnings

            ci = _git(["commit", "-m", f"checkpoint: session-start auto-save {ts}",
                       "--no-verify", "--allow-empty"])
            if ci.returncode != 0:
                _git(["checkout", current_branch])
                warnings.append(
                    f"[{repo_name}] Auto-checkpoint commit FAILED "
                    f"({ci.stderr.strip()[:160]}); branch "
                    f"'{checkpoint_branch}' left in place for recovery. "
                    f"No rebase attempted."
                )
                return warnings

            back = _git(["checkout", current_branch])
            # Drop a recovery artifact for any active session that finds its
            # working tree unexpectedly clean on the next prompt.
            _write_checkpoint_artifact(
                repo_str, checkpoint_branch, ts, dirty_files
            )
            if back.returncode != 0:
                # Surface the stranding NOW. The prior `except: pass` left HEAD
                # silently on the checkpoint branch; the recovery block at the
                # top of this function heals it on the next session start.
                warnings.append(
                    f"[{repo_name}] auto-checkpoint saved work to "
                    f"'{checkpoint_branch}' but checkout back to {current_branch} "
                    f"FAILED: {back.stderr.strip()[:80]}. HEAD left on the "
                    f"checkpoint branch — auto-recovered next session, or /pr-fix."
                )
                return warnings
            # Now stash any remaining untracked files for clean rebase
            status_after = _git(["status", "--porcelain"])
            if status_after.returncode == 0 and status_after.stdout.strip():
                stash_result = _git(
                    ["stash", "--include-untracked", "-m", "session-start auto-stash"]
                )
                stashed = stash_result.returncode == 0
        ff = _git(["merge", "--ff-only", f"origin/{current_branch}"])
        if ff.returncode != 0:
            warnings.append(
                f"[{repo_name}] Fast-forward failed "
                f"({ff.stderr.strip()[:160]}); tree left unchanged."
            )
        if stashed:
            pop = _git(["stash", "pop"])
            if pop.returncode != 0:
                warnings.append(
                    f"[{repo_name}] Stash pop failed after rebase (conflict). "
                    "Run `git stash pop` manually and resolve."
                )
                post_branch = _git(["branch", "--show-current"])
                if post_branch.stdout.strip() != current_branch:
                    _git(["checkout", current_branch])
    except Exception:
        pass
    return warnings


def sync_tracked_repos(self_session_id: str | None = None):
    """Stash dirty state, fetch+rebase, detect conflicts in all tracked repos.

    Each repo is synced in its own thread — git fetch is I/O-bound on Windows
    (~5s each serially). Parallel fan-out drops the wall-clock from
    ~15s to ~max(per-repo) ≈ 6s.

    INTERRUPTION: per-repo state mutations (checkout, commit, stash, rebase)
    are NOT cancellation-safe individually, but each repo is operated on by
    a single thread, so concurrent threads do not race on the same .git dir.
    A killed worker mid-rebase leaves that repo with a dangling .git/rebase-merge/
    which the next session-start clears via the rebase-STATE-DIRECTORY check in
    _sync_one_repo. It is NOT the unmerged-files check: this docstring asserted
    that it was, and the assertion was false. A killed git has written conflict
    markers to the worktree but not unmerged index entries, so `--diff-filter=U`
    returns zero and that check never fires — measured 2026-08-15, when ~/.claude
    sat wedged with an unparseable settings.json because the recovery named here
    could not observe the condition it was supposed to clear.

    Since #1998 this path fast-forwards and never rebases, so this module no
    longer produces that state itself; the recovery covers a wedge arriving from
    an external source.

    self_session_id: passed to _sync_one_repo so the concurrent-session
    detector can ignore this session's own marker.
    """
    # NEVER touch the developer's real repos from a test run. This function is
    # the ONLY place that chooses REAL Path.home() paths -- `_sync_one_repo`
    # takes an explicit repo argument, which is why every existing test can
    # drive the logic safely while this one entry point cannot be made safe by
    # argument. So the gate belongs here.
    #
    # Measured 2026-08-15: `test_crash_safety[session-start.py]` spawns the real
    # session-start hook, which submits this function -- so the test performed
    # network fetches and git mutations against the live ~/.claude and
    # ~/Documents/knowledge-base. Two observed consequences: it took ~25-29s
    # against the test's own 30s timeout (so it flipped pass/fail under load on
    # an unchanged commit), and it overwrote the live
    # `.last-auto-checkpoint.json` recovery pointer. The live hook itself costs
    # 0.05s; every bit of that 25s was the unwanted real-repo sync.
    #
    # CLAUDE_HOOK_TEST is the suite's EXISTING convention, not a new one:
    # `hooks/test-hooks/conftest.py` sets it for every test and subprocess, and
    # bash-security-guard / bash-tail-buffering-guard already skip their
    # live-audit writes under it for exactly this reason ("so the test suite
    # never contaminates the ...").
    if os.environ.get("CLAUDE_HOOK_TEST"):
        return [
            "[repo_sync] Skipped real-repo sync: CLAUDE_HOOK_TEST is set. "
            "Call _sync_one_repo(<explicit path>) to exercise the sync logic."
        ]

    # Which repos: the environment catalog's `repo_paths` (hooks/
    # _environment_catalog.py). Default: only the hot-path repos the operator
    # marked `session_sync` (the config checkout and the knowledge base, where
    # /capture, /garden, /distill and session-start-hook writes land
    # automatically). The rest are sync-on-demand: rebase before manual work,
    # not at every session start. CLAUDE_SYNC_ALL_REPOS=1 syncs every listed
    # repo. No repos configured -> nothing to do.
    entries = repo_entries(load_section("repo_paths"))
    if os.environ.get("CLAUDE_SYNC_ALL_REPOS") != "1":
        entries = [e for e in entries if e["session_sync"]]
    repos = [e["path"] for e in entries]
    warnings: list[str] = []
    if not repos:
        return warnings
    with ThreadPoolExecutor(max_workers=len(repos)) as executor:
        futures = [executor.submit(_sync_one_repo, r, self_session_id) for r in repos]
        for fut in futures:
            warnings.extend(fut.result())
    return warnings
