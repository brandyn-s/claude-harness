#!/usr/bin/env python3
"""Gate the supply-chain invariants SECURITY.md claims about CI workflows.

WHY THIS EXISTS

SECURITY.md's "Supply Chain Protection" section asserts repo-wide invariants:
SHA-pinned actions, and `persist-credentials: false` on ALL `actions/checkout`
steps. Both were asserted in prose with nothing enforcing them, and the
2026-07-26 audit found the second claim FALSE -- `gitleaks.yml` checked out full
history with the default `persist-credentials: true`, leaving the GITHUB_TOKEN in
`.git/config` for every later step in a job that runs a third-party scanner.

A prose invariant with no gate degrades silently: the next workflow added is the
one that breaks it, and nothing notices. These tests make the doc claim
machine-checked, so the doc and the workflows cannot drift apart again.

Deliberately NOT asserted here: the pip-pinning claim. SECURITY.md now records
that Python test deps are unpinned and WHY closing it needs three platform
locks; a test cannot assert an invariant the repo does not hold.

Run: pytest scripts/test_workflow_supply_chain.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"

#: A checkout step's `with:` block ends at the next step (`- ` at step indent)
#: or end of file. Scanning a fixed character window instead would silently
#: pass a step whose `with:` block is longer than the window.
_STEP_BOUNDARY = re.compile(r"\n\s*-\s+(?:name|uses):")


def workflow_files() -> list[Path]:
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    assert files, f"no workflows found under {WORKFLOWS}"
    return files


def _checkout_steps(text: str):
    """Yield (line_number, step_block) for each real `uses: actions/checkout@`.

    Anchored on `uses:` so a prose mention of `actions/checkout` in a comment
    (mirror.yml explains checkout's fetch behaviour in a header comment) is not
    counted as a step. That distinction matters: a naive `grep -c
    actions/checkout` reports mirror.yml as having 2 checkouts and 1
    declaration, which reads as a violation that does not exist.
    """
    for m in re.finditer(r"^[ \t]*(?:-[ \t]+)?uses:[ \t]*actions/checkout@", text, re.MULTILINE):
        line_no = text[: m.start()].count("\n") + 1
        rest = text[m.end():]
        boundary = _STEP_BOUNDARY.search(rest)
        yield line_no, rest[: boundary.start()] if boundary else rest


def test_every_checkout_disables_credential_persistence():
    """SECURITY.md claims this for ALL checkout steps. Enforce it.

    `actions/checkout` defaults `persist-credentials` to TRUE, writing an
    extraheader with the GITHUB_TOKEN into `.git/config`. Any later step in the
    same job -- including third-party actions -- can read it.
    """
    offenders = []
    for f in workflow_files():
        text = f.read_text(encoding="utf-8")
        for line_no, block in _checkout_steps(text):
            if "persist-credentials: false" not in block:
                offenders.append(f"{f.name}:{line_no}")
    assert offenders == [], (
        "actions/checkout without `persist-credentials: false` "
        "(SECURITY.md claims all of them have it):\n  " + "\n  ".join(offenders)
    )


def test_every_action_is_sha_pinned():
    """The other half of the same SECURITY.md claim.

    A mutable tag (`@v4`) lets the action's owner change what CI executes after
    review. Local `./.github/actions/...` composite references are exempt --
    they are this repo's own content, already covered by review.
    """
    offenders = []
    for f in workflow_files():
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"^[ \t]*(?:-[ \t]+)?uses:[ \t]*(\S+)", text, re.MULTILINE):
            ref = m.group(1)
            if ref.startswith("./"):
                continue
            line_no = text[: m.start()].count("\n") + 1
            if "@" not in ref:
                offenders.append(f"{f.name}:{line_no} {ref} (no ref at all)")
                continue
            pin = ref.split("@", 1)[1]
            if not re.fullmatch(r"[0-9a-f]{40}", pin):
                offenders.append(f"{f.name}:{line_no} {ref} (not a 40-char SHA)")
    assert offenders == [], (
        "actions not SHA-pinned (SECURITY.md claims all are):\n  "
        + "\n  ".join(offenders)
    )


def test_gitleaks_workflow_still_exists():
    """SECURITY.md names Gitleaks as the ONE secret-scanning control here.

    L1 corrected that section to say this repo implements Gitleaks only (Trivy /
    cosign / CodeQL live in the MCP server repos). If this workflow is ever
    removed, the doc claim becomes false in the other direction -- claiming a
    control that no longer runs.
    """
    assert (WORKFLOWS / "gitleaks.yml").is_file(), (
        "gitleaks.yml is gone but SECURITY.md still cites it as the "
        "secret-scanning control"
    )


def test_mirror_workflow_commands_match_its_stated_contract():
    """M6 -- the mirror claimed more than it delivered.

    Measured against two local bare repos before the fix:
      * `git push --all` mirrored ONLY main (actions/checkout fetches just the
        triggering ref, so no other branch exists locally for --all to push)
      * `git push --tags` pushed ZERO tags (the checkout fetches none)
      * the `delete:` trigger pruned NOTHING (--all --force cannot delete a
        remote branch), so it burned a CI run per deletion to no effect

    The contract is now "main + tags, no pruning" and the commands say so.
    """
    text = (WORKFLOWS / "mirror.yml").read_text(encoding="utf-8")

    # Tags cannot be pushed before they are fetched.
    assert "git fetch origin --tags" in text, (
        "mirror pushes --tags without fetching them; it will push zero tags"
    )
    # Explicit refspec, not the misleading --all.
    assert "git push personal main:main" in text, (
        "mirror no longer pushes main explicitly"
    )
    assert "git push personal --all" not in text, (
        "`--all` reads as 'every branch' but only main is checked out; "
        "use an explicit refspec"
    )
    # The dead trigger must stay gone: it cannot prune, by construction.
    assert not re.search(r"(?m)^\s{2}delete:\s*$", text), (
        "the `delete:` trigger is back; --force pushes cannot prune, so it "
        "burns a CI run per deletion and mirrors nothing"
    )
    # --mirror from a checkout leaks remote-tracking refs (verified live).
    # Scan COMMAND lines only: the workflow carries a comment warning against
    # --mirror, and a whole-file check would match that warning and fail on a
    # clean tree (rules/tdd-mutation-testing.md item 18 -- assert on the artifact, and
    # here the artifact is the executed command, not the prose beside it).
    command_lines = [
        ln for ln in text.splitlines()
        if "git push" in ln and not ln.lstrip().startswith("#")
    ]
    assert command_lines, "no git push command found in the mirror workflow"
    offenders = [ln.strip() for ln in command_lines if "--mirror" in ln]
    assert offenders == [], (
        "`git push --mirror` from a checkout propagates remote-tracking refs "
        f"(observed: it pushed `origin/main` as a literal ref): {offenders}"
    )


def test_security_doc_does_not_claim_lock_files():
    """Negative assertion: the retracted claim must not silently return.

    The audit found no lock file anywhere in the repo while SECURITY.md claimed
    "`pip-compile` lock files ensure deterministic dependency resolution". If
    someone re-adds that sentence without adding locks, this fails.
    """
    text = (REPO / "SECURITY.md").read_text(encoding="utf-8")
    claims_locks = re.search(r"pip-compile lock files ensure", text)
    lock_files = [
        p
        for p in REPO.rglob("requirements*.lock")
        if ".git/" not in str(p)
    ]
    if claims_locks:
        assert lock_files, (
            "SECURITY.md claims pip-compile lock files but none exist; "
            "either add the locks or drop the claim"
        )
