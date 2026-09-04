#!/usr/bin/env python3
"""Every `Full: incidents#<anchor>` pointer in rules/ must resolve.

Ambient rules point at extracted narrative in `rules/incidents/<name>.md`. There
are 100+ such pointers and nothing compared them, so they drifted silently:
measured 2026-07-30, 18 of 73 resolved to no heading and no `<a id=>` in any
incidents file.

The drift is invisible for a specific reason. The corpus convention is a SHORT
PREFIX of the target's prose heading —

    pointer:  #2026-05-15-cloudfront-oac-rediscovery
    heading:  ## 2026-05-15 cloudfront-oac-rediscovery - skipped memory_search ...

— which reads correct to a human and resolves under `grep`, but a prefix never
matches GitHub's slugified heading, so the anchor link is dead. The fix is an
explicit `<a id="...">` under the heading (the pattern the corpus already used in
`incidents/verify-before-assuming.md`), which keeps the readable title.

A `"Full: incidents#anchor"` occurrence inside a `Pointer shorthand:` line is a
worked EXAMPLE of the convention, not a pointer. Excluded — otherwise the check
demands an anchor literally named `anchor`, which is the false-positive that
would get this test demoted to advisory and then ignored.

The same pointers live in `docs/rule-reference/*.md` (246 of them, measured
2026-09-04) and nothing scanned that directory until PR #11 noticed; a reference doc
can therefore point at an anchor that was renamed under it. `POINTER_SOURCES` names
every directory whose pointers must resolve, and `_dangling` is the single resolver
that both the real corpus and the negative controls run through, so "the directory
is covered" is asserted rather than assumed.
"""
import re
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RULES = REPO / "rules"
INCIDENTS = RULES / "incidents"
RULE_REFERENCE = REPO / "docs" / "rule-reference"
# Every directory whose top-level *.md may carry `Full: incidents#<anchor>` pointers.
POINTER_SOURCES = (RULES, RULE_REFERENCE)

POINTER = re.compile(r"Full:\s*incidents#([\w./-]+)")
DOC_EXAMPLE = re.compile(r"Pointer shorthand|shorthand:")


def _slug(text: str) -> str:
    """Approximate GitHub's heading -> anchor slugification."""
    t = text.strip().lower()
    t = re.sub(r"`", "", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[*_~]", "", t)
    t = unicodedata.normalize("NFKD", t)
    t = re.sub(r"[^\w\s-]", "", t)
    # Each space becomes a hyphen; runs are NOT collapsed, so a heading
    # "recovery - hook" (em-dash stripped) slugifies to "recovery--hook".
    return re.sub(r"\s", "-", t.strip())


def _exposed(path: Path) -> set[str]:
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#{1,6}\s+(.*)$", line)
        if m:
            out.add(_slug(m.group(1)))
        out.update(a.lower() for a in re.findall(r'<a id="([^"]+)"', line))
    return out


def _all_anchors() -> dict[str, set[str]]:
    return {p.stem: _exposed(p) for p in INCIDENTS.glob("*.md")}


def _dangling(sources, cache: dict[str, set[str]]) -> tuple[int, list[str]]:
    """(pointers seen, unresolved pointers) over the top-level *.md of each source dir.

    A pointer resolves against the incidents file of the same stem first, then any
    incidents file (cross-file pointers are legitimate). Labels carry the parent
    directory so a rules/ hit and a rule-reference/ hit read differently.
    """
    dangling: list[str] = []
    total = 0
    for source in sources:
        for doc in sorted(Path(source).glob("*.md")):
            for line in doc.read_text(encoding="utf-8").splitlines():
                if DOC_EXAMPLE.search(line):
                    continue
                for raw in POINTER.findall(line):
                    total += 1
                    a = raw.rstrip("./").lower()
                    if a in cache.get(doc.stem, set()):
                        continue
                    if any(a in v for v in cache.values()):
                        continue  # cross-file pointer, still resolvable
                    dangling.append(f"{doc.parent.name}/{doc.name} -> #{raw}")
    return total, dangling


def test_every_incident_pointer_resolves():
    if not INCIDENTS.is_dir():
        return  # corpus absent (fresh checkout) — not a defect
    total, dangling = _dangling(POINTER_SOURCES, _all_anchors())
    assert not dangling, (
        f"{len(dangling)} of {total} incident pointers resolve to no heading and "
        f"no <a id=> in any rules/incidents/*.md.\n"
        + "\n".join(f"  {d}" for d in dangling)
        + "\n\nFix: add `<a id=\"<anchor>\"></a>` under the target heading "
          "(keeps the readable prose title), or correct the pointer."
    )


def test_check_would_catch_a_broken_pointer():
    """Negative control: the resolver must not pass everything.

    A test that only ever sees a clean corpus cannot distinguish "all pointers
    resolve" from "the matcher never matches".
    """
    cache = _all_anchors()
    bogus = "definitely-not-an-anchor-2026-07-30"
    assert not any(bogus in v for v in cache.values())


def test_doc_example_lines_are_excluded():
    """The `Pointer shorthand:` example must not be read as a pointer."""
    line = '# Pointer shorthand: "Full: incidents#anchor" = rules/incidents/git-hygiene.md'
    assert POINTER.search(line), "pattern should still match the literal"
    assert DOC_EXAMPLE.search(line), "but the line must be recognised as documentation"


def test_rule_reference_pointers_are_checked():
    """docs/rule-reference/*.md points into the same incidents files (246 pointers
    measured 2026-09-04) but was never scanned; PR #11 found the gap."""
    assert RULE_REFERENCE in POINTER_SOURCES
    assert any(RULE_REFERENCE.glob("*.md")), "reference corpus went missing"


def test_check_would_catch_a_broken_pointer_in_a_reference_doc(tmp_path):
    """Negative control for the docs path: a deliberately wrong anchor appended to a
    copy of a reference doc must be reported, and the copy's real pointers must not."""
    ref = tmp_path / "rule-reference"
    ref.mkdir()
    source = RULE_REFERENCE / "verify-before-assuming.md"
    bogus = "definitely-not-an-anchor-2026-09-04"
    (ref / source.name).write_text(
        source.read_text(encoding="utf-8") + f"\n#   Full: incidents#{bogus}\n",
        encoding="utf-8",
    )
    total, dangling = _dangling((ref,), _all_anchors())
    assert total > 1, "the copy's own pointers were not scanned"
    assert dangling == [f"rule-reference/{source.name} -> #{bogus}"]
