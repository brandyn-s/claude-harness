#!/usr/bin/env python3
"""Rule-relocation pilot: measure the EXPOSURE created by moving an ambient rule into
the skill that owns its activity. Deterministic, no API spend, no LLM judge.

WHAT THIS DECIDES
-----------------
Relocating a rule from ambient to a skill step changes exactly one thing: whether the
text is in context when the decision happens.

  A  ambient                             -> always present     (today)
  B  relocated, owner skill invoked      -> present            (fine)
  C  relocated, owner skill NOT invoked  -> ABSENT             (the regression)

So the decisive question is: how often is the activity performed WITHOUT the owning
skill being invoked? That is condition C, answerable from the local transcript corpus.

PRE-REGISTERED THRESHOLDS (fixed before any result was inspected)
----------------------------------------------------------------
  coverage = sessions(activity AND owner-skill) / sessions(activity)
    >= 0.95 -> SAFE          relocate; C is negligible
    >= 0.70 -> NEEDS-EVAL    relocate only behind a behavioural A/B
    <  0.70 -> KEEP-AMBIENT  the ambient slot is earned

REFUSAL CONDITIONS (added after the first run produced an untrustworthy verdict)
------------------------------------------------------------------------------
  NO-GROUND-TRUTH  the owner skill was never invoked in the corpus, so the activity
                   detector's recall CANNOT be measured. The first version reported
                   KEEP-AMBIENT here, which is a confident verdict from an unvalidated
                   instrument. It now refuses.
  LOW-RECALL       ground truth exists but the detector misses >20% of it.
  INSUFFICIENT-N   fewer than 5 sessions show the activity.

WHY THE DETECTOR IS SPLIT BY LOCATION
-------------------------------------
A signal found in a `Read` tool_result is a DOCUMENT being read, not the activity being
performed -- and the ambient rules themselves contain words like "paginate". Measured on
a 60-session sample: 15.6% of hits were prose-only, and much of the remainder was
`Read` output plus `--limit 100`, which is the behaviour the rule RECOMMENDS rather
than the activity it governs. So hits are classified and the document share reported;
a detector whose signal is mostly documents gets no verdict.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path.home() / ".claude/projects/-Users-you"
AUTHORING_SESSION = "11111111-1111-1111-1111-111111111111"
AUTHORING_SKILLS = {"mega-distill", "distill", "mega-capture", "ship"}

SAFE_AT, EVAL_AT = 0.95, 0.70
MIN_ACTIVITY_SESSIONS = 5
RECALL_FLOOR = 0.80
DOC_SHARE_CEILING = 0.50   # >50% of hits from document reads -> detector unusable

# Where a rule body can live. A relocated rule keeps its manifest but moves out of
# rules/ (skills/_shared/ since #2148), so the scope check must look in both.
# Resolved from THIS FILE, not Path.home(): the pilot evaluates the checkout it ships
# in. Reading ~/.claude would grade a DIFFERENT tree -- the deployed one, which can sit
# far behind origin/main, so a rule already relocated on main would still be found in
# its old ambient location and the guard would grade stale content. Transcripts still
# come from ~/.claude/projects, which is correct: those are session history, not code.
_REPO = Path(__file__).resolve().parents[1]
RULE_SEARCH_DIRS = (
    _REPO / "rules",
    _REPO / "skills" / "_shared",
)


def rule_scope_text(rule: str) -> str | None:
    """The rule's declared @scope, or None when the body cannot be located."""
    for d in RULE_SEARCH_DIRS:
        path = d / f"{rule}.md"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"@scope\s+(.+?)(?=\n@|\n#|\n\n)", text, re.S)
        return " ".join(m.group(1).split()) if m else ""
    return None


def scope_is_bound_to_owner_skills(c: "Candidate") -> bool | None:
    """True only when the rule's OWN @scope enumerates every owner skill.

    THIS IS THE GUARD THAT MAKES `skill_scoped` PROVABLE RATHER THAN DECLARED, and it
    closes a path that could have authorised ~50,000 B of unsafe relocation.

    `activity()` returns owner-invocation for a skill_scoped candidate, so
    `exposed = activity - owner` is EMPTY BY CONSTRUCTION -> coverage 100% -> SAFE.
    Nothing previously checked that the rule's scope actually equalled its owner
    skills. Declaring a candidate with `owner_skills` and no signals therefore MINTED
    a SAFE verdict regardless of what the rule governs.

    Measured 2026-08-26: twelve NO-DETECTOR rules are named by some skill's
    `requires_rules`, which reads like the same link that made output-grounding SAFE.
    It is not. `requires_rules` means "this skill needs this rule", NOT "this rule's
    scope is this skill". Every one of those twelve declares scope as "every <task
    type>" -- eval-shipping-discipline even says "wherever the changed source file
    lives", a clause written to defeat exactly this narrowing. Adding them as
    skill_scoped candidates would have produced twelve false SAFEs.

    Returns None when the rule body cannot be found, which is itself a refusal.
    """
    scope = rule_scope_text(c.rule)
    if scope is None:
        return None
    low = scope.lower()
    return all(sk.lower() in low for sk in c.owner_skills)

# Tools whose RESULTS are document contents, not evidence of an activity.
DOC_TOOLS = {"Read", "Grep", "Glob", "NotebookRead"}


@dataclass
class Candidate:
    rule: str
    owner_skills: set[str]
    signals: list[re.Pattern] = field(default_factory=list)
    signal_tools: set[str] = field(default_factory=set)
    mcp_prefix: bool = False
    note: str = ""

    @property
    def skill_scoped(self) -> bool:
        """The rule's scope IS the owner skills; activity == owner invocation."""
        return not (self.signals or self.signal_tools or self.mcp_prefix)


CANDIDATES = [
    Candidate(
        rule="output-grounding",
        owner_skills={"scout-frontier", "design-evidence-first", "deep-dive", "refine"},
        note="@scope is literally these four skills, so activity == owner invocation",
    ),
    Candidate(
        rule="bulk-data",
        owner_skills={"bulk-api-script"},
        signals=[
            re.compile(r"per_page=1?[05]0\b"),
            re.compile(r"\bNextToken\b|\bnext_token\b|@odata\.nextLink|meta\.next"),
            re.compile(r"\bexport_(?:assets|vulns|compliance)\b"),
        ],
        note="scope: >100 results / export / large data",
    ),
    Candidate(
        rule="mcp-tool-names",
        owner_skills=set(),
        signal_tools={"ToolSearch"},
        mcp_prefix=True,
        note="no single owning skill -- included so the measurement can say so",
    ),
    # ---- ADDED 2026-08-26: the twelve NO-DETECTOR rules named by some skill's
    # requires_rules. They are here so the refusal is RECORDED rather than left as
    # "unmeasured, not cleared" -- each one exercises the scope-bound guard, which is
    # the whole point. `requires_rules` means "this skill needs this rule", NOT "this
    # rule's scope is this skill", so every one of these must verdict
    # SCOPE-NOT-SKILL-BOUND. If one ever verdicts SAFE, either its @scope was
    # narrowed deliberately or the guard regressed -- check before relocating.
    Candidate(
        rule="eval-shipping-discipline",
        owner_skills={"build-measurement-harness", "gather-vendor", "search-campaign"},
        note="named by requires_rules in 3 skill(s), but @scope is a TASK TYPE -- expected to refuse",
    ),
    Candidate(
        rule="security-critical-search-verification",
        owner_skills={"verify-search-result"},
        note="named by requires_rules in 1 skill(s), but @scope is a TASK TYPE -- expected to refuse",
    ),
    Candidate(
        rule="red-team-rubric-discipline",
        owner_skills={"persona", "roundtable", "software-security-review"},
        note="named by requires_rules in 3 skill(s), but @scope is a TASK TYPE -- expected to refuse",
    ),
    Candidate(
        rule="symmetric-evidentiary-burden",
        owner_skills={"roundtable", "software-security-review", "vendor-breach"},
        note="named by requires_rules in 3 skill(s), but @scope is a TASK TYPE -- expected to refuse",
    ),
    Candidate(
        rule="compare-by-need",
        owner_skills={"absorb", "evaluate-repos", "gather-intel", "scout", "scout-skills"},
        note="named by requires_rules in 5 skill(s), but @scope is a TASK TYPE -- expected to refuse",
    ),
    Candidate(
        rule="reproduce-before-optimize",
        owner_skills={"search-axis-rotate"},
        note="named by requires_rules in 1 skill(s), but @scope is a TASK TYPE -- expected to refuse",
    ),
    Candidate(
        rule="api-doc-lookup",
        owner_skills={"api-ingest", "api-preflight", "gather-claude-endpoints", "gather-openai-endpoints", "gather-vendor"},
        note="named by requires_rules in 5 skill(s), but @scope is a TASK TYPE -- expected to refuse",
    ),
]


@dataclass
class Facts:
    skills: set[str] = field(default_factory=set)
    commands: set[str] = field(default_factory=set)
    tools: Counter = field(default_factory=Counter)
    hits_action: Counter = field(default_factory=Counter)
    hits_doc: Counter = field(default_factory=Counter)


def scan(path: Path, cands: list[Candidate]) -> Facts:
    f = Facts()
    pending_doc: set[str] = set()   # tool_use ids whose results are document contents
    with path.open(errors="replace") as fh:
        for raw in fh:
            s = raw.strip()
            if not s.startswith("{"):
                continue
            try:
                rec = json.loads(s)
            except Exception:
                continue
            msg = rec.get("message") or {}
            content = msg.get("content")

            if isinstance(content, str) and "<command-name>" in content:
                for frag in content.split("<command-name>")[1:]:
                    f.commands.add(frag.split("</command-name>")[0].strip().lstrip("/"))
            if not isinstance(content, list):
                continue

            for b in content:
                if not isinstance(b, dict):
                    continue
                kind = b.get("type")
                if kind == "tool_use":
                    name = b.get("name") or "?"
                    f.tools[name] += 1
                    if name in DOC_TOOLS:
                        pending_doc.add(str(b.get("id")))
                    if name == "Skill":
                        sk = (b.get("input") or {}).get("skill")
                        if sk:
                            f.skills.add(str(sk))
                    payload = json.dumps(b.get("input") or {})
                    bucket = f.hits_doc if name in DOC_TOOLS else f.hits_action
                    for c in cands:
                        if any(rx.search(payload) for rx in c.signals):
                            bucket[c.rule] += 1
                elif kind == "tool_result":
                    body = b.get("content")
                    text = body if isinstance(body, str) else json.dumps(body)
                    is_doc = str(b.get("tool_use_id")) in pending_doc
                    bucket = f.hits_doc if is_doc else f.hits_action
                    for c in cands:
                        if any(rx.search(text) for rx in c.signals):
                            bucket[c.rule] += 1
                elif kind == "text":
                    t = b.get("text") or ""
                    if "<command-name>" in t:
                        for frag in t.split("<command-name>")[1:]:
                            f.commands.add(frag.split("</command-name>")[0].strip().lstrip("/"))
                    for c in cands:
                        if any(rx.search(t) for rx in c.signals):
                            f.hits_doc[c.rule] += 1     # assistant prose is not an action
    return f


def owner_invoked(f: Facts, c: Candidate) -> bool:
    return bool(c.owner_skills & (f.skills | f.commands))


def signal_fired(f: Facts, c: Candidate) -> bool:
    if f.hits_action.get(c.rule):
        return True
    if c.signal_tools & set(f.tools):
        return True
    if c.mcp_prefix and any(t.startswith("mcp__") for t in f.tools):
        return True
    return False


def activity(f: Facts, c: Candidate) -> bool:
    return owner_invoked(f, c) if c.skill_scoped else signal_fired(f, c)


def decide_verdict(*, skill_scoped: bool, scope_bound: bool | None, has_owner: bool,
                   recall: float | None, doc_share: float | None,
                   n: int, cov: float | None) -> str:
    """The verdict ladder, extracted so its ORDER is testable.

    It used to be inline in main(), which made the only available test a textual
    check that the scope branch appeared before the SAFE branch in the source. That
    proxy passed while a mutation that moved the check to the END of the ladder
    produced 6 SAFE verdicts instead of 1 -- pinning source position rather than
    behaviour (rules/tdd-mutation-testing.md item 26). As a function, the property
    itself is assertable: a scope-unbound candidate can never reach SAFE.

    ORDER IS LOAD-BEARING. A wrongly-declared skill_scoped candidate has
    exposed == 0 and cov == 1.0 BY CONSTRUCTION, so every later gate reads as clean.
    The scope check must come first or it cannot protect anything.
    """
    if skill_scoped and scope_bound is None:
        return "RULE-BODY-NOT-FOUND"
    if skill_scoped and not scope_bound:
        return "SCOPE-NOT-SKILL-BOUND"
    if not skill_scoped and not has_owner:
        return "NO-GROUND-TRUTH"
    if recall is not None and recall < RECALL_FLOOR:
        return "LOW-RECALL"
    if doc_share is not None and doc_share > DOC_SHARE_CEILING:
        return "DETECTOR-READS-DOCS"
    if n < MIN_ACTIVITY_SESSIONS:
        return "INSUFFICIENT-N"
    if cov is None:
        return "INSUFFICIENT-N"
    return ("SAFE" if cov >= SAFE_AT else
            "NEEDS-EVAL" if cov >= EVAL_AT else "KEEP-AMBIENT")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=PROJECT_DIR)
    ap.add_argument("--min-transcripts", type=int, default=100)
    args = ap.parse_args()

    paths = sorted(args.dir.glob("*.jsonl"))
    if len(paths) < args.min_transcripts:
        print(f"FLOOR: expected >={args.min_transcripts} transcripts, found {len(paths)}",
              file=sys.stderr)
        return 2

    facts = {p.stem: scan(p, CANDIDATES) for p in paths}
    print(f"transcripts scanned: {len(paths)}\n")

    # ---- instrument validation: refuse to report if the detector is blind ----
    auth = facts.get(AUTHORING_SESSION)
    print("INSTRUMENT VALIDATION")
    if auth is None:
        print("  FAILED: authoring session absent from corpus", file=sys.stderr)
        return 2
    missing = AUTHORING_SKILLS - auth.skills
    print(f"  known-positive (Skill detection): found {len(AUTHORING_SKILLS)-len(missing)}"
          f"/{len(AUTHORING_SKILLS)} expected skills")
    if missing:
        print(f"  FAILED: cannot see {sorted(missing)}", file=sys.stderr)
        return 2
    if any("no-such-skill-xyzzy" in f.skills for f in facts.values()):
        print("  FAILED: known-negative matched", file=sys.stderr)
        return 2
    print("  known-negative (bogus skill name): 0 sessions  OK")
    print()

    print("OWNER-SKILL INVOCATION, corpus-wide (decision-relevant on its own)")
    for c in CANDIDATES:
        if not c.owner_skills:
            print(f"  {c.rule:20s} (no owner skill identified)")
            continue
        for sk in sorted(c.owner_skills):
            n = sum(1 for f in facts.values() if sk in (f.skills | f.commands))
            print(f"  {c.rule:20s} {sk:18s} invoked in {n:3d}/{len(paths)} sessions")
    print()

    print("EXPOSURE MEASUREMENT")
    summary = []
    for c in CANDIDATES:
        act = {s for s, f in facts.items() if activity(f, c)}
        own = {s for s, f in facts.items() if owner_invoked(f, c)}
        exposed = act - own
        n = len(act)

        doc = sum(f.hits_doc.get(c.rule, 0) for f in facts.values())
        actn = sum(f.hits_action.get(c.rule, 0) for f in facts.values())
        doc_share = doc / (doc + actn) if (doc + actn) else None

        recall = None
        if not c.skill_scoped and own:
            recall = len({s for s in own if signal_fired(facts[s], c)}) / len(own)

        cov = len(act & own) / n if n else None
        scope_bound = scope_is_bound_to_owner_skills(c) if c.skill_scoped else True
        verdict = decide_verdict(
            skill_scoped=c.skill_scoped, scope_bound=scope_bound, has_owner=bool(own),
            recall=recall, doc_share=doc_share, n=n, cov=cov,
        )

        print(f"\n  {c.rule}")
        print(f"    note              : {c.note}")
        print(f"    sessions: activity={n}  owner={len(own)}  EXPOSED={len(exposed)}")
        print(f"    coverage          : {'n/a' if cov is None else f'{cov:.1%}'}")
        print(f"    detector recall   : {'unmeasurable (no ground truth)' if recall is None else f'{recall:.1%}'}")
        if c.skill_scoped:
            print(f"    scope names owners: "
                  f"{'rule body not found' if scope_bound is None else scope_bound}")
        if doc_share is not None:
            print(f"    hits from documents: {doc_share:.1%} ({doc} doc / {actn} action)")
        print(f"    VERDICT           : {verdict}")
        summary.append((c.rule, verdict, cov, n, len(exposed)))

    print("\n\nSUMMARY")
    print(f"  {'rule':20s} {'verdict':20s} {'coverage':>9s} {'n':>5s} {'exposed':>8s}")
    for rule, v, cov, n, exp in summary:
        print(f"  {rule:20s} {v:20s} {'n/a' if cov is None else f'{cov:7.1%}':>9s} {n:5d} {exp:8d}")
    print("\n  Only SAFE authorises a relocation. Every other verdict means this corpus")
    print("  cannot justify one -- including the refusal verdicts, which are NOT")
    print("  evidence that the rule is load-bearing, only that this instrument cannot say.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
