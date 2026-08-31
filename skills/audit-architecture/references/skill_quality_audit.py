"""Skill quality evaluation: S1-S7, C1-C7, X1-X3 + portfolio health.

Run from audit-architecture Phase 2b or standalone:
  python ~/.claude/skills/audit-architecture/references/skill_quality_audit.py

Outputs JSON to stdout for programmatic use, human-readable to stderr.
Exit code: 0 if all skills >= 12/17, 1 otherwise.
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

base = os.environ.get('CLAUDE_CONFIG_DIR') or os.path.expanduser('~/.claude')
skills_dir = f'{base}/skills'
rules_path = f'{base}/hooks/skill-rules.json'

# Anthropic's authoritative skill-body cap (rules/skill-standards.md).
SKILL_BODY_LINE_CAP = 510  # SOFT proxy (rules/skill-standards.md, ≤510 non-failing); advisory only — C6 fails on the ~5000-word token-budget proxy, not on line count

# ── SKILL TYPE CLASSIFICATION ──
# Per rules/skill-standards.md "SKILL.md Step Format — Depends on Skill Type":
#   Mechanical skills — clear tool-call sequences, forbidden commands explicitly
#   named in prose. Descriptions are terse imperatives; they correctly skip the
#   verbose "trigger/Do NOT use" patterns that judgment-heavy skills need.
#
# Checks that penalize mechanical skills unfairly (verbosity bias):
#   C1_triggers     — looks for "use when|trigger|invoke" keywords
#   C2_negative     — looks for "Do NOT use"/"don't use" blocks
#   X2_crossref     — looks for sibling-skill redirects inside negative blocks
#
# These three checks are EXEMPTED for skills classified as mechanical.
# Front-loading check is also relaxed (imperative verbs count as front-loaded).
#
# Classification source order:
#   1. YAML frontmatter `type: mechanical` (preferred — skill self-declares)
#   2. Fallback set below (legacy skills that pre-date the frontmatter field)
MECHANICAL_SKILLS = {
    'ship',
    'ship-hook',
    'pr-fix',
    'linear-status',
    'pull-repos',
    'index-repo',
    'cross-repo',
}


def _is_mechanical(folder, frontmatter):
    type_match = re.search(r'^type:\s*(.+?)\s*$', frontmatter, re.MULTILINE)
    if type_match and type_match.group(1).strip().strip('"\'').lower() == 'mechanical':
        return True
    return folder in MECHANICAL_SKILLS


def load_routing_rules():
    """Read skill-rules.json and return the set of routed skill names.

    Mirrors the May 2026 graceful-handling pattern in doc_accuracy_audit.py:
    a missing or malformed skill-rules.json must NOT crash the scanner.
    Emit "ERROR: ..." to stderr and fall through with an empty set —
    every skill will fail X3 (no routing rule), which is honest output,
    not a Python traceback. Phase 0's "Probe error handling" promise
    ("Never let a single probe failure stall the entire audit") applies
    to Phase 2b too.
    """
    try:
        with open(rules_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {rules_path} not found", file=sys.stderr)
        return set()
    except json.JSONDecodeError as e:
        print(f"ERROR: {rules_path} malformed ({e})", file=sys.stderr)
        return set()
    return {r['skill'] for r in data.get('rules', []) if r.get('skill')}


def _safe_listdir(path):
    """os.listdir(path) but returns [] if the directory doesn't exist.

    Mirrors doc_accuracy_audit.py — a missing skills/ directory (e.g. a
    CLAUDE_CONFIG_DIR pointed at a non-existent path) must NOT crash the
    scanner with a traceback. Phase 0's "Probe error handling" promise
    applies to the full Phase 2b scanner, not just load_routing_rules().
    """
    try:
        return os.listdir(path)
    except FileNotFoundError:
        print(f"ERROR: {path} not found", file=sys.stderr)
        return []


def evaluate_skill(d, routed_skills):
    """Evaluate one skill directory. Returns (name, score, total, rating, fails, meta)."""
    skill_path = f'{skills_dir}/{d}/SKILL.md'
    with open(skill_path, 'r', encoding='utf-8') as f:
        content = f.read()

    checks: dict = {}
    # Strip frontmatter for line-count metrics: the SKILL_BODY_LINE_CAP
    # check applies to the SKILL.md *body*, not the full file. Including
    # frontmatter (typically ~11 lines) silently inflates the count and
    # made skills falsely fail the cap.
    _split_for_meta = content.split('---', 2)
    if len(_split_for_meta) >= 3 and content.startswith('---'):
        _body_for_meta = _split_for_meta[2]
    else:
        _body_for_meta = content
    meta: dict = {
        'words': len(_body_for_meta.split()),
        'lines': _body_for_meta.count('\n') + 1,
    }

    # ── STRUCTURE ──
    checks['S1_folder'] = 'PASS' if re.match(r'^[a-z0-9]+(-[a-z0-9]+)*$', d) else 'FAIL'
    checks['S2_exists'] = 'PASS'

    # S3: Frontmatter
    parts = content.split('---', 2)
    if len(parts) >= 3 and content.startswith('---'):
        fm = parts[1]
        body = parts[2]
        has_name = bool(re.search(r'^name:', fm, re.MULTILINE))
        has_desc = bool(re.search(r'^description:', fm, re.MULTILINE))
        checks['S3_frontmatter'] = 'PASS' if (has_name and has_desc) else 'FAIL'
    else:
        fm, body = '', content
        checks['S3_frontmatter'] = 'FAIL'

    # S4: Name matches folder
    name_match = re.search(r'^name:\s*(.+)', fm, re.MULTILINE)
    if name_match:
        checks['S4_name_match'] = 'PASS' if name_match.group(1).strip().strip('"\'') == d else 'FAIL'
    else:
        checks['S4_name_match'] = 'FAIL'

    # S5: No XML in frontmatter (excluding argument-hint)
    fm_no_hint = re.sub(r'^argument-hint:.*$', '', fm, flags=re.MULTILINE)
    checks['S5_no_xml'] = 'FAIL' if re.search(r'<[a-zA-Z/]', fm_no_hint) else 'PASS'

    # S6: No README.md
    checks['S6_no_readme'] = 'FAIL' if os.path.exists(f'{skills_dir}/{d}/README.md') else 'PASS'

    # S7: Description under 1024 chars
    desc_text = ''
    desc_start = fm.find('description:')
    if desc_start >= 0:
        desc_text = fm[desc_start + 12:]
        next_key = re.search(r'\n[a-z]', desc_text)
        if next_key:
            desc_text = desc_text[:next_key.start()]
        checks['S7_desc_len'] = 'PASS' if len(desc_text.strip()) <= 1024 else 'FAIL'
    else:
        checks['S7_desc_len'] = 'FAIL'

    # when_to_use (Claude Code extension): trigger phrases and the Do-NOT
    # clause commonly live here instead of the (menu-facing) description —
    # same field-relocation validate-skills.py's A4/A5 already account for
    # (fm.get("description")+fm.get("when_to_use") combined "routing_text").
    # Reading desc_text alone made C1/C2/X2 fail near-universally (97/99
    # skills on X2_crossref) for skills that fully comply, just via the
    # newer field. Extracted with the same manual field-slicing this file
    # already uses for `description:`, not a YAML re-parse, to match style.
    wtu_text = ''
    wtu_start = fm.find('when_to_use:')
    if wtu_start >= 0:
        wtu_text = fm[wtu_start + 12:]
        next_key = re.search(r'\n[a-z]', wtu_text)
        if next_key:
            wtu_text = wtu_text[:next_key.start()]
    routing_text = f'{desc_text}\n{wtu_text}'

    # ── CONTENT QUALITY ──
    # Mechanical skills (ship, pr-fix, etc.) per rules/skill-standards.md
    # correctly skip verbose trigger-phrase and negative-precedence patterns —
    # their descriptions are terse imperatives. Exempt them from C1/C2/X2.
    is_mechanical = _is_mechanical(d, fm)
    meta['skill_type'] = 'mechanical' if is_mechanical else 'judgment'

    if is_mechanical:
        checks['C1_triggers'] = 'PASS'  # terse imperatives are valid triggers
    else:
        checks['C1_triggers'] = 'PASS' if re.search(
            r'(use when|trigger|invoke|do not use)', routing_text, re.IGNORECASE) else 'FAIL'

    if is_mechanical:
        checks['C2_negative'] = 'PASS'  # exempt — mechanical skills are self-defining
    else:
        checks['C2_negative'] = 'PASS' if re.search(
            r"(do not use|don't use|not for|do NOT)", routing_text, re.IGNORECASE) else 'FAIL'
    checks['C3_examples'] = 'PASS' if re.search(
        r'^#{1,3}\s+Examples?', content, re.MULTILINE) else 'FAIL'
    checks['C4_success'] = 'PASS' if re.search(
        r'^#{1,3}\s+Success Criteria', content, re.MULTILINE) else 'FAIL'
    checks['C5_errors'] = 'PASS' if re.search(
        r'(error|fail|exception|fallback|if.*fails|when.*fails)', body, re.IGNORECASE) else 'PARTIAL'

    has_refs = os.path.isdir(f'{skills_dir}/{d}/references')
    # SKILL.md body length is SOFT guidance (rules/skill-standards.md: ≤510,
    # non-failing — "do NOT tighten to a hard 500"). The real constraint is the
    # Level-2 token budget, proxied here by ~5000 words; a long body ALONE no
    # longer fails C6 (it is reported as advisory by validate-skills / healthcheck).
    over_words = meta['words'] > 5000
    checks['C6_size'] = 'FAIL' if over_words and not has_refs else 'PASS'

    vague = re.findall(
        r'(validate properly|handle appropriately|do the right thing|as needed)', body, re.IGNORECASE)
    checks['C7_clarity'] = 'FAIL' if len(vague) > 2 else 'PASS'

    # ── COMPOSABILITY ──
    checks['X1_no_exclusive'] = 'FAIL' if re.search(
        r'(disable other|only skill|exclusive|deactivate)', body, re.IGNORECASE) else 'PASS'

    if is_mechanical:
        checks['X2_crossref'] = 'PASS'  # exempt — mechanical skills are self-defining
    elif re.search(r"(do not use|don't use|not for|do NOT)", routing_text, re.IGNORECASE):
        neg_section = re.findall(r'do not use.*?(?:\n|$)', routing_text, re.IGNORECASE)
        has_redirect = bool(re.search(r'(/[a-z-]+|use \w+ instead)', ' '.join(neg_section), re.IGNORECASE))
        checks['X2_crossref'] = 'PASS' if has_redirect else 'PARTIAL'
    else:
        checks['X2_crossref'] = 'FAIL'

    checks['X3_routing'] = 'PASS' if d in routed_skills else 'FAIL'

    # ── EXTRA CHECKS ──
    effort_match = re.search(r'^effort:\s*(\w+)', fm, re.MULTILINE)
    meta['effort'] = effort_match.group(1) if effort_match else None

    # NOTE: A front-loading regex check used to live here. It produced 10/10
    # false positives on the real skill portfolio (2026-05-23 audit) because
    # well-written descriptions lead with imperative verbs ("Generate", "Run",
    # "Bring up", "Queue", "Create", "Use before") that no narrow regex
    # captures. Dropped. The /skills menu truncation at 250 chars is still
    # real and worth manual review, just not via this scanner.

    # Score
    pass_count = sum(1 for v in checks.values() if v == 'PASS')
    partial_count = sum(1 for v in checks.values() if v == 'PARTIAL')
    score = pass_count + (partial_count * 0.5)
    total = len(checks)

    if score >= 15:
        rating = 'Excellent'
    elif score >= 12:
        rating = 'Good'
    elif score >= 8:
        rating = 'Needs Work'
    else:
        rating = 'Poor'

    fails = [k for k, v in checks.items() if v == 'FAIL']
    return d, score, total, rating, fails, meta


def _resolve_reference_target(full_path, source_skill, all_skills):
    """Given a matched path like 'references/foo.md' or
    '~/.claude/skills/other-skill/references/foo.md', return (target_skill, filename).
    Falls back to source_skill when the prefix is unrecognized.
    """
    fm = re.search(r'references/([\w\-]+\.md)$', full_path)
    if not fm:
        return None
    filename = fm.group(1)
    prefix = full_path[:fm.start()].rstrip('/')
    # Strip ~/.claude/, .claude/, or leading skills/ to isolate the skill name
    prefix_norm = re.sub(r'^~?/?(?:\.claude/)?skills/', '', prefix).strip('/')
    if not prefix_norm:
        return (source_skill, filename)
    if prefix_norm in all_skills:
        return (prefix_norm, filename)
    # Unrecognized prefix — treat as same-skill (conservative)
    return (source_skill, filename)


def _default_scan_root():
    """Return parent(skills_dir) in production, skills_dir itself in tests.

    Heuristic: real skills_dir always ends in '/skills' or '\\skills'. When
    the basename is 'skills', the meaningful tree to walk is the parent
    (which holds hooks/, rules/, agent-memory/, etc.). Otherwise we're in a
    test that monkey-patched skills_dir to a tmp dir whose siblings are
    other tests' fixtures, so we scan skills_dir itself.
    """
    abs_skills = os.path.abspath(skills_dir)
    if os.path.basename(abs_skills) == 'skills':
        return os.path.dirname(abs_skills)
    return abs_skills


def _walk_claude_tree_for_mentions(candidate_filenames, scan_root=None):
    """Build {filename: True} for every candidate that appears anywhere in the
    Claude config tree.

    A file's own self-reference (mentioning its own basename inside its own
    body) does NOT count as a mention — a stub that opens with a header
    matching its own filename should still be flagged. But a sibling
    reference file mentioning another candidate DOES count, which is the
    common case the previous SKILL.md-only check missed.

    Scans .md / .py / .yaml / .yml / .json / .toml under scan_root.
    """
    mentioned = {fn: False for fn in candidate_filenames}
    if not mentioned:
        return mentioned
    scan_root = scan_root or _default_scan_root()
    skip_dirs = {'__pycache__', '.git', 'node_modules', '.venv'}
    for root, dirs, files in os.walk(scan_root):
        dirs[:] = [d for d in dirs if d not in skip_dirs and d != 'marketplace']
        for fn in files:
            if not fn.endswith(('.md', '.py', '.yaml', '.yml', '.json', '.toml')):
                continue
            fp = os.path.join(root, fn)
            try:
                with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                    body = f.read()
            except Exception:
                continue
            for cand in candidate_filenames:
                if mentioned[cand]:
                    continue
                # Self-mention doesn't rescue: a stub that opens with its
                # own filename header is still orphan.
                if cand == fn:
                    continue
                if cand in body:
                    mentioned[cand] = True
    return mentioned


# Meta-reference recognition: a `references/x.md` mention is META (documentation
# OF the reference mechanism, not a literal citation) when it sits inside a fenced
# code block, uses a placeholder path, or is explicitly marked as an example. The
# audit-architecture / audit-skill SKILL.md files document their OWN FP pattern and
# so mention synthetic paths (references/X.md, missing-ref.md, search-waves.md) that
# are intentionally absent. Flagging them as "broken" is the recurring FP this guards.
_PLACEHOLDER_STEM_RE = re.compile(r'references/[A-Z]\.md$')  # references/X.md, Y.md
_META_LINE_RE = re.compile(
    r'placeholder|synthetic|intentionally absent|not yet detected|'
    r'not yet created|not citing|audit looks for',
    re.IGNORECASE)


def _is_meta_reference(line, matched_path):
    """True when a matched references/*.md is a meta-citation, not a real one."""
    if '<' in line or '>' in line:            # references/<skill>/... placeholder path
        return True
    if _PLACEHOLDER_STEM_RE.search(matched_path):  # single-capital stem = placeholder
        return True
    if _META_LINE_RE.search(line):            # explicit "placeholder/synthetic/..." prose
        return True
    return False


def validate_references():
    """Check for orphaned and broken reference files.

    Broken: a SKILL.md references `references/{file}.md` that doesn't exist
    at the resolved target skill's references/ dir.
    Orphaned: a file in some skill's references/ dir is mentioned NOWHERE in
    the Claude config tree (.md/.py/.yaml/.yml/.json/.toml under base/).
    The orphan check is intentionally broad — it covers cross-skill mentions,
    sibling reference files, examples/, scripts/, rules/, agent-memory/,
    manifests/, etc. (Before 2026-05-23 it only scanned SKILL.md files,
    which gave a 67% false-positive rate.)
    """
    orphaned = []
    broken = []
    all_skills = {d for d in _safe_listdir(skills_dir)
                  if os.path.isdir(f'{skills_dir}/{d}')}

    # Pattern captures the full path context around 'references/{file}.md'.
    # Matches:
    #   references/foo.md                                    (same-skill)
    #   other-skill/references/foo.md                        (cross-skill, relative)
    #   skills/other-skill/references/foo.md                 (cross-skill, semi-absolute)
    #   ~/.claude/skills/other-skill/references/foo.md       (cross-skill, absolute)
    ref_pattern = re.compile(r'([\w\-~./]*references/[\w\-]+\.md)')

    # Pre-read all SKILL.md contents for the broken-ref check
    all_skill_contents = {}
    for d in sorted(all_skills):
        skill_path = f'{skills_dir}/{d}/SKILL.md'
        if os.path.isfile(skill_path):
            with open(skill_path, 'r', encoding='utf-8') as f:
                all_skill_contents[d] = f.read()

    # ── Broken references: resolve each mention to its true target skill ──
    # Line-aware so fenced code blocks (YAML/bash examples) and meta-citations
    # (placeholder paths, "synthetic fixture" prose) are excluded — those are the
    # recurring false positives (references/X.md, missing-ref.md, search-waves.md).
    for d, skill_content in all_skill_contents.items():
        in_fence = False
        for line in skill_content.splitlines():
            if line.lstrip().startswith('```'):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for m in ref_pattern.finditer(line):
                if _is_meta_reference(line, m.group(1)):
                    continue
                resolved = _resolve_reference_target(m.group(1), d, all_skills)
                if not resolved:
                    continue
                target_skill, filename = resolved
                target_path = f'{skills_dir}/{target_skill}/references/{filename}'
                if not os.path.exists(target_path):
                    label = f'{target_skill}/references/{filename}'
                    if target_skill != d:
                        label += f' (referenced by {d})'
                    broken.append(label)

    # ── Orphaned references: build the candidate set first, then one pass
    # through the Claude tree to see what mentions them ──
    candidate_paths = {}  # filename -> ["{skill}/references/{filename}", ...]
    for d in sorted(all_skills):
        refs_dir = f'{skills_dir}/{d}/references'
        if not os.path.isdir(refs_dir):
            continue
        for fn in os.listdir(refs_dir):
            if fn.startswith('__') or fn.startswith('.'):
                continue
            candidate_paths.setdefault(fn, []).append(f'{d}/references/{fn}')

    if candidate_paths:
        mentioned = _walk_claude_tree_for_mentions(set(candidate_paths.keys()))
        for fn, is_mentioned in mentioned.items():
            if not is_mentioned:
                # Emit one entry per skill that owns a file with this name.
                for path in candidate_paths[fn]:
                    orphaned.append(path)

    orphaned = sorted(orphaned)
    broken = sorted(set(broken))
    return orphaned, broken


def main():
    routed = load_routing_rules()
    results = []
    effort_dist = {'low': 0, 'medium': 0, 'high': 0, 'max': 0, 'missing': 0}

    for d in sorted(_safe_listdir(skills_dir)):
        if not os.path.isdir(f'{skills_dir}/{d}'):
            continue
        if not os.path.isfile(f'{skills_dir}/{d}/SKILL.md'):
            continue

        name, score, total, rating, fails, meta = evaluate_skill(d, routed)

        if meta['effort']:
            effort_dist[meta['effort']] = effort_dist.get(meta['effort'], 0) + 1
        else:
            effort_dist['missing'] += 1

        results.append({
            'name': name, 'score': score, 'total': total,
            'rating': rating, 'fails': fails, 'words': meta['words'],
            'effort': meta['effort'],
        })

    results.sort(key=lambda x: x['score'])
    orphaned_refs, broken_refs = validate_references()

    # Aggregate
    ratings = {}
    all_fails = {}
    for r in results:
        ratings[r['rating']] = ratings.get(r['rating'], 0) + 1
        for f in r['fails']:
            all_fails[f] = all_fails.get(f, 0) + 1

    needs_work = [r for r in results if r['score'] < 12]
    good = [r for r in results if r['score'] >= 12]

    # ── Human-readable output to stderr ──
    print(f'=== SKILL QUALITY EVALUATION ({len(results)} skills) ===', file=sys.stderr)
    for rating in ['Excellent', 'Good', 'Needs Work', 'Poor']:
        print(f'  {rating}: {ratings.get(rating, 0)}', file=sys.stderr)

    print(f'\nEffort: {dict(sorted(effort_dist.items()))}', file=sys.stderr)

    if needs_work:
        print(f'\nNEEDS WORK ({len(needs_work)}):', file=sys.stderr)
        for r in needs_work:
            print(f'  {r["name"]:<40} {r["score"]:>5.1f}/{r["total"]} {", ".join(r["fails"])}', file=sys.stderr)

    if orphaned_refs:
        print(f'\nORPHANED REFERENCES ({len(orphaned_refs)}):', file=sys.stderr)
        for p in orphaned_refs:
            print(f'  {p}', file=sys.stderr)

    if broken_refs:
        print(f'\nBROKEN REFERENCES ({len(broken_refs)}):', file=sys.stderr)
        for p in broken_refs:
            print(f'  {p}', file=sys.stderr)

    top_fails = sorted(all_fails.items(), key=lambda x: -x[1])[:5]
    print(f'\nTop failures: {", ".join(f"{k} ({v})" for k, v in top_fails)}', file=sys.stderr)
    print(f'Compliance: {len(good)}/{len(results)} (>= 12/17)', file=sys.stderr)

    # ── JSON output to stdout ──
    output = {
        'total': len(results),
        'compliance_rate': len(good) / len(results) if results else 0,
        'ratings': ratings,
        'effort_distribution': effort_dist,
        'orphaned_references': orphaned_refs,
        'broken_references': broken_refs,
        'top_failures': dict(top_fails),
        'needs_work': [r['name'] for r in needs_work],
        'skills': results,
    }
    json.dump(output, sys.stdout, indent=2)

    return 0 if not needs_work else 1


if __name__ == '__main__':
    sys.exit(main())
