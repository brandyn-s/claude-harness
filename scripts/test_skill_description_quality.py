"""Deterministic description-collision gate for the skill routing table.

Since the static routing table was deleted, the ONLY routing logic is the text
Claude Code shows the model for each skill: `description` followed by
`when_to_use`, truncated at 1,536 characters, for every skill whose frontmatter
does not set `disable-model-invocation: true` (the same contract
scripts/validate-skills.py A2 and scripts/token-audit.py already enforce). Two
skills whose listing text says the same thing compete for the same requests,
and a listing with no triggering condition gives the model nothing to match.
No network, no LLM: this is the gate that keeps working at $0.

Checks:
  1. no two skills share an identical description (or identical listing text);
  2. no pair of listings exceeds JACCARD_MAX content-word overlap unless the
     pair is in scripts/description_collision_allowlist.json with a reason
     (and every allowlisted pair really is over the line, so entries cannot
     go stale silently);
  3. every model-visible listing carries a triggering cue -- a "use when" /
     "trigger" / "when ..." phrase or a quoted user-request pattern. Reported
     as a WARNING on stderr instead of a failure while more than
     CUE_WARN_THRESHOLD skills fail it (rewording is the owner's call).

Run `pytest -s scripts/test_skill_description_quality.py` (or the file directly)
to also see the ten most-similar pairs ranked, with the words they share.
"""
from __future__ import annotations

import json
import re
import sys
from itertools import combinations
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"
ALLOWLIST_PATH = REPO_ROOT / "scripts" / "description_collision_allowlist.json"

LISTING_CHARACTER_CAP = 1536      # Claude Code truncates description + when_to_use here
JACCARD_MAX = 0.6                 # content-word overlap above which two listings collide
MIN_TOKEN_LEN = 3
CUE_WARN_THRESHOLD = 10           # more offenders than this -> warn, do not fail
TOP_PAIRS = 10

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
TOKEN_RE = re.compile(r"[a-z0-9]+")

# Function words plus the routing scaffolding almost every listing repeats
# ("Use when ...", "Trigger phrases: ...", "Do NOT use for ..."). Scaffolding is
# stripped so that overlap measures shared SUBJECT MATTER, not shared template.
STOPWORDS = frozenset("""
the and for that this with from into onto over under than then when whenever
what which who whom whose where why how are was were been being have has had
having does did doing not but nor yet also any all each every some such only
just very more most less least much many own same other another both either
neither its their them they you your our ours his her hers him she one ones per
via about above after before against between through during without within
across toward towards upon out off can cannot could should would will shall
may might must let lets get gets got need needs needed want wants wanted use
used uses using make makes made run runs ran running see there here these those
while because since until unless whether instead rather already still again
once always never ever often
skill skills trigger triggers triggered phrase phrases invoke invoked invokes
invoking user users asks asked asking ask request requests example examples etc
don dont doesn
""".split())  # noqa: SIM905 -- one word per token reads better than a 100-item literal

# A triggering cue: the listing states WHEN to fire, or quotes what a user says.
CUE_RE = re.compile(
    r"\b(?:use|invoke|invoked|load|read)\b[^.]{0,40}?"
    r"\b(?:when|whenever|before|after|during|at the start|inside|with|to|for|if|on|as)\b"
    r"|\btrigger"
    r"|\bwhen\b"
    r"|[\"“][^\"”]{4,80}[\"”]"
    r"|'[^']{4,80}'",
    re.IGNORECASE,
)


def frontmatter_of(text: str) -> dict:
    match = FRONTMATTER_RE.search(text)
    if not match:
        return {}
    value = yaml.safe_load(match.group(1)) or {}
    return value if isinstance(value, dict) else {}


def listing_text(description: str, when_to_use: str) -> str:
    """What the model sees for one skill: description + when_to_use, capped."""
    combined = " ".join(part for part in (description, when_to_use) if part)
    return combined[:LISTING_CHARACTER_CAP]


def load_skills(skills_dir: Path = SKILLS_DIR) -> list[dict]:
    skills = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        if skill_md.parent.name == "_shared":
            continue
        fm = frontmatter_of(skill_md.read_text(encoding="utf-8"))
        description = " ".join(str(fm.get("description") or "").split())
        when_to_use = " ".join(str(fm.get("when_to_use") or "").split())
        skills.append({
            "name": skill_md.parent.name,
            "description": description,
            "when_to_use": when_to_use,
            "listing": listing_text(description, when_to_use),
            "model_visible": fm.get("disable-model-invocation") is not True,
        })
    return skills


def content_tokens(text: str) -> frozenset[str]:
    """Lowercased alphanumeric tokens, punctuation split, stopwords and short tokens dropped."""
    return frozenset(
        tok for tok in TOKEN_RE.findall(text.lower())
        if len(tok) >= MIN_TOKEN_LEN and tok not in STOPWORDS
    )


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def ranked_pairs(skills: list[dict]) -> list[tuple[float, str, str, list[str]]]:
    """Every pair of model-visible listings, most similar first."""
    tokens = {s["name"]: content_tokens(s["listing"]) for s in skills if s["model_visible"]}
    pairs = []
    for (a, ta), (b, tb) in combinations(sorted(tokens.items()), 2):
        pairs.append((jaccard(ta, tb), a, b, sorted(ta & tb)))
    pairs.sort(key=lambda row: (-row[0], row[1], row[2]))
    return pairs


def load_allowlist(path: Path = ALLOWLIST_PATH) -> dict[frozenset[str], str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    allow = {}
    for entry in data.get("pairs", []):
        allow[frozenset(entry["skills"])] = entry.get("reason", "")
    return allow


def cue_offenders(skills: list[dict]) -> list[dict]:
    return [s for s in skills if s["model_visible"] and not CUE_RE.search(s["listing"])]


def format_pair_table(pairs, limit: int = TOP_PAIRS) -> str:
    lines = [f"{'jaccard':>7}  {'skill A':<26} {'skill B':<26} shared content words"]
    for score, a, b, shared in pairs[:limit]:
        lines.append(f"{score:7.3f}  {a:<26} {b:<26} {', '.join(shared)}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- tests

def test_corpus_loads_and_most_skills_are_model_visible():
    skills = load_skills()
    assert len(skills) >= 70, "skills/*/SKILL.md corpus went missing or moved"
    assert all(s["description"] for s in skills), [s["name"] for s in skills if not s["description"]]
    hidden = [s["name"] for s in skills if not s["model_visible"]]
    assert len(hidden) < len(skills) / 2, hidden


def test_listing_text_matches_runtime_contract():
    assert listing_text("A.", "B.") == "A. B."
    assert listing_text("A.", "") == "A."
    assert len(listing_text("x" * 2000, "y" * 100)) == LISTING_CHARACTER_CAP


def test_content_tokens_strip_punctuation_stopwords_and_short_tokens():
    tokens = content_tokens('Use when the user asks: "run semgrep", SAST-scan, or /codeql (v2).')
    assert tokens == {"semgrep", "sast", "scan", "codeql"}


def test_jaccard_bounds():
    assert jaccard(frozenset(), frozenset()) == 0.0
    assert jaccard(frozenset("ab"), frozenset("ab")) == 1.0
    assert jaccard(frozenset("ab"), frozenset("bc")) == 1 / 3


def test_no_two_skills_have_identical_descriptions():
    skills = load_skills()
    by_description: dict[str, list[str]] = {}
    by_listing: dict[str, list[str]] = {}
    for s in skills:
        by_description.setdefault(s["description"].lower(), []).append(s["name"])
        by_listing.setdefault(s["listing"].lower(), []).append(s["name"])
    dupes = [names for names in by_description.values() if len(names) > 1]
    assert not dupes, f"identical descriptions: {dupes}"
    dupes = [names for names in by_listing.values() if len(names) > 1]
    assert not dupes, f"identical listing text (description + when_to_use): {dupes}"


def test_no_listing_pair_exceeds_jaccard_max_unless_allowlisted():
    pairs = ranked_pairs(load_skills())
    allow = load_allowlist()
    offenders = [
        f"{a} vs {b}: jaccard={score:.3f}, shared={shared}"
        for score, a, b, shared in pairs
        if score > JACCARD_MAX and frozenset((a, b)) not in allow
    ]
    assert not offenders, (
        f"{len(offenders)} listing pair(s) over {JACCARD_MAX} content-word overlap; "
        f"reword one side or add the pair to {ALLOWLIST_PATH.name} with a reason:\n  "
        + "\n  ".join(offenders)
    )


def test_allowlist_entries_are_current():
    """Every allowlisted pair names real skills, gives a reason, and is still over the line."""
    if not ALLOWLIST_PATH.exists():
        return
    skills = load_skills()
    names = {s["name"] for s in skills}
    scores = {frozenset((a, b)): score for score, a, b, _ in ranked_pairs(skills)}
    data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert data.get("threshold") == JACCARD_MAX
    stale = []
    for entry in data["pairs"]:
        pair = frozenset(entry["skills"])
        assert len(pair) == 2, entry
        assert entry.get("reason", "").strip(), f"allowlist entry without a reason: {entry}"
        missing = pair - names
        if missing:
            stale.append(f"{sorted(pair)}: unknown skill(s) {sorted(missing)}")
        elif scores.get(pair, 0.0) <= JACCARD_MAX:
            stale.append(f"{sorted(pair)}: jaccard={scores.get(pair, 0.0):.3f} no longer over {JACCARD_MAX}")
    assert not stale, "stale allowlist entries (remove them):\n  " + "\n  ".join(stale)


def test_every_model_visible_listing_has_a_triggering_cue():
    offenders = cue_offenders(load_skills())
    detail = "\n  ".join(f"{s['name']}: {s['listing'][:110]}" for s in offenders)
    message = (
        f"{len(offenders)} model-visible skill(s) state no triggering condition "
        f"(no 'use when'/'trigger'/'when ...' phrase and no quoted user request):\n  {detail}"
    )
    if len(offenders) > CUE_WARN_THRESHOLD:
        print(f"WARNING (not failing while > {CUE_WARN_THRESHOLD} offenders): {message}", file=sys.stderr)
        return
    assert not offenders, message


def test_report_most_similar_pairs():
    """Always passes; prints the ranked table under `pytest -s`."""
    skills = load_skills()
    pairs = ranked_pairs(skills)
    visible = sum(1 for s in skills if s["model_visible"])
    print(f"\n{visible} model-visible listings, {len(pairs)} pairs; "
          f"{TOP_PAIRS} most similar (content-word Jaccard, threshold {JACCARD_MAX}):")
    print(format_pair_table(pairs))
    offenders = cue_offenders(skills)
    print(f"{len(offenders)} listing(s) without a triggering cue: "
          f"{', '.join(s['name'] for s in offenders) or '-'}")
    # Informational: the cue usually lives in when_to_use, not in description.
    bare = [s["name"] for s in skills if s["model_visible"] and not CUE_RE.search(s["description"])]
    print(f"{len(bare)} of {visible} descriptions carry no cue on their own (when_to_use supplies it)")


if __name__ == "__main__":
    skills = load_skills()
    print(format_pair_table(ranked_pairs(skills)))
    offenders = cue_offenders(skills)
    print(f"\n{len(offenders)} listing(s) without a triggering cue: "
          f"{', '.join(s['name'] for s in offenders) or '-'}")
