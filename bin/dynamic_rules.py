#!/usr/bin/env python3
"""Entra dynamic-group membershipRule analysis primitives.

Extracted 2026-08-29 after the FOURTH dynamic-group incident in 26 days
(2026-08-03 scope-inheritance, 08-14 Dynamic_IT top-level-or defect,
08-24 EA4 null-inversion, 08-28 dept-taxonomy rename ejecting ~1,400
memberships). The 08-28 repair hand-built each of these primitives across
a dozen /tmp scripts; this module makes them importable and tested.

Primitives (pure functions unless noted):
  extract_comparisons(rule, attr)   -> [(op, literal)] incl. -in arrays
  op_matches(op, pattern, value)    -> bool (Entra operator semantics)
  match_set(op, pattern, values)    -> set of matching values
  match_set_delta(rule, attr, rename_map, census) -> per-fuzzy-clause diff
  rewrite_exact_literals(rule, rename_map)        -> str (quoted-literal swap)
  dedupe_duplicate_or_clauses(rule, attr, eligible) -> str (hotfix consolidation;
      eligible from hotfix_eligible_values — only rename-created dupes strip)
  top_level_or_defect(rule)         -> bool (guard-bypassing bare `or`)
  list_dynamic_groups() / value_census(attr)      -> live Graph reads

HARD-WON SEMANTICS ENCODED HERE (do not re-derive):
  * `and` binds tighter than `or`; a trailing appended `or (...)` clause
    bypasses every guard — detect with top_level_or_defect().
  * Rules use BOTH `and/or` and PowerShell-style `-and/-or` joiners live
    (Helm IT Portal - Users uses the hyphenated form).
  * A fuzzy clause's impact must be evaluated against the FULL live value
    census, never only the changed values (78-vs-13 incident, 2026-08-28).
  * `-ne "X"` is TRUE when the attribute is null (clearing a tag GRANTS).
  * String comparisons are case-insensitive in Entra rule evaluation.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

_EXACT_OPS = {"eq", "ne", "in", "notin"}
_FUZZY_OPS = {"contains", "notcontains", "startswith", "notstartswith", "match", "notmatch"}


def _cmp_re(attr):
    return re.compile(
        r"user\." + re.escape(attr) +
        r'\s+-(eq|ne|startsWith|notStartsWith|contains|notContains|match|notMatch)\s+"((?:[^"\\]|\\.)*)"',
        re.IGNORECASE,
    )


def _in_re(attr):
    return re.compile(
        r"user\." + re.escape(attr) + r"\s+-(in|notIn)\s+\[([^\]]*)\]",
        re.IGNORECASE,
    )


_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')


def extract_comparisons(rule, attr):
    """All (op_lowercase, literal) comparisons on user.<attr>, incl. -in arrays."""
    out = []
    for op, lit in _cmp_re(attr).findall(rule or ""):
        out.append((op.lower(), lit))
    for op, body in _in_re(attr).findall(rule or ""):
        for lit in _QUOTED.findall(body):
            out.append((op.lower(), lit))
    return out


def exact_literals(rule, attr):
    return [(op, lit) for op, lit in extract_comparisons(rule, attr) if op in _EXACT_OPS]


def fuzzy_comparisons(rule, attr):
    return [(op, lit) for op, lit in extract_comparisons(rule, attr) if op in _FUZZY_OPS]


def op_matches(op, pattern, value):
    """Entra membership-rule operator semantics (case-insensitive). None = eval error."""
    if value is None:
        value = ""
    op = op.lower()
    v, p = str(value).lower(), str(pattern).lower()
    if op in ("contains", "notcontains"):
        hit = p in v
    elif op in ("startswith", "notstartswith"):
        hit = v.startswith(p)
    elif op in ("match", "notmatch"):
        try:
            hit = re.search(pattern, str(value), re.IGNORECASE) is not None
        except re.error:
            return None
    elif op in ("eq", "in"):
        hit = v == p
    elif op in ("ne", "notin"):
        hit = v != p
    else:
        return None
    return (not hit) if op.startswith("not") else hit


def match_set(op, pattern, values):
    """Subset of values matched by (op, pattern). For not* ops this is the
    set the clause evaluates TRUE for, which is usually the complement."""
    return {v for v in values if op_matches(op, pattern, v)}


def match_set_delta(rule, attr, rename_map, census_values):
    """For each fuzzy clause on attr, how its TRUE-set changes under rename_map,
    evaluated over the FULL census (never only the renamed values).

    census_values: the complete PRE-rename live value set. Returns a list of
    {op, pattern, lost, gained} — values whose membership in the clause's
    TRUE-set changes when old->new is applied.
    """
    post = {rename_map.get(v, v) for v in census_values}
    deltas = []
    for op, pat in fuzzy_comparisons(rule, attr):
        pre_set = match_set(op, pat, set(census_values))
        post_set = match_set(op, pat, post)
        lost = {v for v in pre_set if rename_map.get(v, v) not in post_set}
        gained = {v for v in post_set if v not in {rename_map.get(x, x) for x in pre_set}}
        if lost or gained:
            deltas.append({"op": op, "pattern": pat,
                           "lost": sorted(lost), "gained": sorted(gained)})
    return deltas


def rewrite_exact_literals(rule, rename_map):
    """Swap quoted old literals for new. Quoted-literal replacement is safe
    against superstrings ('"Software"' is not a substring of '"Software Eng"')."""
    out = rule
    for old, new in rename_map.items():
        out = out.replace(f'"{old}"', f'"{new}"')
    return out


def hotfix_eligible_values(rule, rename_map):
    """Values whose duplication a literal swap would CREATE: the original rule
    already carries the NEW value as a clause (a manual hotfix) alongside the
    OLD value. Only these may be deduped after the swap.

    WHY THIS EXISTS (bug found live 2026-08-29): an unconditional dedupe treated
    Engineering Milestones' two INTENTIONAL `-eq "Quality"` clauses (PM clause +
    manager clause, different subexpressions) as a duplicate and stripped one in
    a production PATCH. A repeated literal is only a duplicate when the rename
    itself manufactured it."""
    return {new for old, new in rename_map.items()
            if f'"{old}"' in (rule or "") and f'"{new}"' in (rule or "")}


def dedupe_duplicate_or_clauses(rule, attr, eligible):
    """After a literal swap, a manual hotfix clause `or (user.<attr> -eq "V")`
    may duplicate an existing -eq clause. Strip the LAST strippable OR clause
    per duplicated literal (hotfixes are appended, so last-first is right) —
    but ONLY for literals in `eligible` (see hotfix_eligible_values); a literal
    that legitimately appears twice is load-bearing, not a duplicate.
    Leaves non-strippable duplicates alone for manual review."""
    if not eligible:
        return rule
    or_clause = re.compile(
        r"\s+-?or\s+\(user\." + re.escape(attr) + r'\s+-eq\s+"((?:[^"\\]|\\.)*)"\)',
        re.IGNORECASE,
    )
    eq_lit = re.compile(
        r"user\." + re.escape(attr) + r'\s+-eq\s+"((?:[^"\\]|\\.)*)"', re.IGNORECASE)
    out = rule
    for _ in range(10):
        lits = eq_lit.findall(out)
        dupes = {v for v in lits if lits.count(v) > 1 and v in eligible}
        if not dupes:
            break
        changed = False
        for m in reversed(list(or_clause.finditer(out))):
            if m.group(1) in dupes:
                out = out[:m.start()] + out[m.end():]
                changed = True
                break
        if not changed:
            break
    return out


_JOINER = re.compile(r"\s+(-?and|-?or)\s+", re.IGNORECASE)


def top_level_or_defect(rule):
    """True when the rule has BOTH a top-level (paren-depth-0) `or`/-or AND a
    top-level `and`/-and — the precedence shape where the or-branch bypasses
    the and-guards (`and` binds tighter). A rule that is ONLY or-joined
    parenthesized clauses is not flagged. Quoted strings are skipped."""
    if not rule:
        return False
    depth = 0
    stripped = []
    in_str = False
    i = 0
    while i < len(rule):
        ch = rule[i]
        if ch == '"' and (i == 0 or rule[i - 1] != "\\"):
            in_str = not in_str
            stripped.append(" ")
        elif in_str:
            stripped.append(" ")
        elif ch == "(":
            depth += 1
            stripped.append("(")
        elif ch == ")":
            depth -= 1
            stripped.append(")")
        else:
            stripped.append(ch if depth == 0 else " ")
        i += 1
    top = "".join(stripped)
    joiners = {m.group(1).lower().lstrip("-") for m in _JOINER.finditer(top)}
    return "or" in joiners and "and" in joiners


def build_rewrite_plan(groups, attr, rename_map):
    """Pure: compute per-group target rules for an attribute-value rename.

    Returns [{id, displayName, action, before, after}] where action is
    'patch' (rule changes), 'skip_clean' (no stale literal, nothing to do), or
    'skip_stale_unrewritable' (stale literal present but the rewrite could not
    change the rule — needs manual review, e.g. an unstrippable duplicate)."""
    plan = []
    for g in groups:
        rule = g.get("membershipRule") or ""
        stale = [lit for _, lit in exact_literals(rule, attr) if lit in rename_map]
        if not stale:
            # GATE: never rewrite a rule the rename does not touch. The
            # 2026-08-29 incident: dedupe ran on an untouched rule and stripped
            # a load-bearing clause in production.
            plan.append({"id": g.get("id"), "displayName": g.get("displayName"),
                         "action": "skip_clean", "before": rule, "after": None})
            continue
        target = dedupe_duplicate_or_clauses(
            rewrite_exact_literals(rule, rename_map), attr,
            hotfix_eligible_values(rule, rename_map))
        if target != rule:
            action = "patch"
        else:
            action = "skip_stale_unrewritable"
        plan.append({"id": g.get("id"), "displayName": g.get("displayName"),
                     "action": action, "before": rule,
                     "after": target if action == "patch" else None})
    return plan


def apply_rewrite_plan(plan, attr, rename_map, ledger_path):
    """Apply 'patch' items: fresh-fetch each rule, recompute from the LIVE rule
    (TOCTOU guard — the plan may be minutes old), PATCH, readback-verify,
    append every outcome to a JSON ledger. Returns (ok, skipped, failed)."""
    import time as _time
    from msgraph_helper import graph_get, graph_patch
    ledger = []
    ok = skipped = failed = 0
    for item in plan:
        if item["action"] != "patch":
            skipped += 1
            continue
        gid, name = item["id"], item["displayName"]
        live, err = graph_get(f"/groups/{gid}", params={"$select": "membershipRule"})
        entry = {"id": gid, "name": name, "status": None, "before": None, "after": None}
        if err:
            entry["status"] = f"GET_FAILED: {err[:150]}"
            failed += 1
        else:
            before = (live or {}).get("membershipRule") or ""
            entry["before"] = before
            fresh_stale = [lit for _, lit in exact_literals(before, attr) if lit in rename_map]
            target = before if not fresh_stale else dedupe_duplicate_or_clauses(
                rewrite_exact_literals(before, rename_map), attr,
                hotfix_eligible_values(before, rename_map))
            if target == before:
                entry["status"] = "SKIP_ALREADY_CLEAN"
                skipped += 1
            else:
                entry["after"] = target
                _, perr = graph_patch(f"/groups/{gid}", {"membershipRule": target})
                if perr:
                    entry["status"] = f"PATCH_FAILED: {perr[:150]}"
                    failed += 1
                else:
                    _time.sleep(0.4)
                    rb, rerr = graph_get(f"/groups/{gid}", params={"$select": "membershipRule"})
                    if not rerr and (rb or {}).get("membershipRule") == target:
                        entry["status"] = "PATCHED_VERIFIED"
                        ok += 1
                    else:
                        entry["status"] = f"READBACK_ISSUE: {rerr or 'mismatch'}"
                        failed += 1
        ledger.append(entry)
        print(f"  {entry['status']}: {name}")
        _time.sleep(0.4)
    import json as _json
    import os as _os
    _os.makedirs(_os.path.dirname(ledger_path), exist_ok=True)
    existing = []
    if _os.path.exists(ledger_path):
        with open(ledger_path, encoding="utf-8") as f:
            existing = _json.load(f)
    with open(ledger_path, "w", encoding="utf-8") as f:
        _json.dump(existing + ledger, f, indent=2)
    print(f"ledger: {ledger_path}")
    return ok, skipped, failed


# ---- live Graph reads (import msgraph_helper lazily so pure functions are testable offline)

def list_dynamic_groups():
    from msgraph_helper import graph_get_all
    groups, err = graph_get_all("/groups", params={
        "$filter": "groupTypes/any(c:c eq 'DynamicMembership')",
        "$select": "id,displayName,membershipRule,membershipRuleProcessingState",
        "$count": "true", "$top": "999",
    }, consistency=True)
    if err:
        raise RuntimeError(f"group enumeration failed: {err}")
    return groups


def value_census(attr):
    from msgraph_helper import graph_get_all
    users, err = graph_get_all("/users", params={"$select": attr, "$top": "999"})
    if err:
        raise RuntimeError(f"user census failed: {err}")
    return Counter((u.get(attr) or "(none)") for u in users)


def _main():
    p = argparse.ArgumentParser(description="Entra dynamic-rule analysis (read-only CLI)")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("groups", help="dynamic groups, optionally filtered to rules referencing --attr")
    g.add_argument("--attr")
    c = sub.add_parser("census", help="distinct live values of a user attribute")
    c.add_argument("attr")
    i = sub.add_parser("impact", help="rule impact of an attribute value rename")
    i.add_argument("--attr", required=True)
    i.add_argument("--rename", action="append", required=True, metavar="OLD=NEW")
    w = sub.add_parser("rewrite", help="rewrite stale exact literals across dynamic groups "
                                       "(dry-run by default; --apply patches with ledger + readback)")
    w.add_argument("--attr", required=True)
    w.add_argument("--rename", action="append", required=True, metavar="OLD=NEW")
    w.add_argument("--group-id", action="append", help="limit to specific group id(s)")
    w.add_argument("--apply", action="store_true",
                   help="PATCH the 'patch' items (fresh-fetch + readback + ledger); omit for dry-run")
    w.add_argument("--ledger", default=None, help="ledger JSON path (default: ~/Documents/reports/entra/dynamic-rules-ledger-<UTC date>.json)")
    args = p.parse_args()

    if args.cmd == "census":
        for v, n in sorted(value_census(args.attr).items()):
            print(f"{n:>6}  {v}")
        return
    groups = list_dynamic_groups()
    if args.cmd == "groups":
        for grp in groups:
            rule = grp.get("membershipRule") or ""
            if args.attr and not extract_comparisons(rule, args.attr):
                continue
            flag = " [TOP-LEVEL-OR DEFECT]" if top_level_or_defect(rule) else ""
            print(f"{grp['displayName']} ({grp['id']}){flag}\n  {rule}")
        return
    if args.cmd == "rewrite":
        rename = dict(r.split("=", 1) for r in args.rename)
        if args.group_id:
            groups = [g for g in groups if g.get("id") in set(args.group_id)]
        plan = build_rewrite_plan(groups, args.attr, rename)
        patches = [x for x in plan if x["action"] == "patch"]
        print(f"plan: {len(patches)} to patch, "
              f"{sum(1 for x in plan if x['action'] == 'skip_clean')} clean, "
              f"{sum(1 for x in plan if x['action'] == 'skip_stale_unrewritable')} need manual review")
        for x in plan:
            if x["action"] == "patch":
                print(f"\nPATCH {x['displayName']} ({x['id']})\n  before: {x['before']}\n  after:  {x['after']}")
            elif x["action"] == "skip_stale_unrewritable":
                print(f"\nMANUAL {x['displayName']} ({x['id']}): stale literal present but not rewritable\n  rule: {x['before']}")
        if not args.apply:
            print("\ndry-run only — re-run with --apply to patch")
            return
        import datetime
        import os
        ledger = args.ledger or os.path.expanduser(
            "~/Documents/reports/entra/dynamic-rules-ledger-"
            + datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d") + ".json")
        ok, skipped, failed = apply_rewrite_plan(plan, args.attr, rename, ledger)
        print(f"applied: {ok} verified, {skipped} skipped, {failed} failed")
        if failed:
            sys.exit(1)
        return
    # impact
    rename = dict(r.split("=", 1) for r in args.rename)
    census = set(value_census(args.attr))
    for grp in groups:
        rule = grp.get("membershipRule") or ""
        stale = [(op, lit) for op, lit in exact_literals(rule, args.attr) if lit in rename]
        deltas = match_set_delta(rule, args.attr, rename, census)
        if not stale and not deltas:
            continue
        print(f"\n{grp['displayName']} ({grp['id']})")
        for op, lit in stale:
            print(f"  exact -{op} \"{lit}\" -> \"{rename[lit]}\"")
        for d in deltas:
            print(f"  FUZZY -{d['op']} \"{d['pattern']}\" lost={d['lost']} gained={d['gained']}")
        if stale:
            proposed = dedupe_duplicate_or_clauses(
                rewrite_exact_literals(rule, rename), args.attr,
                hotfix_eligible_values(rule, rename))
            if proposed != rule:
                print(f"  proposed: {proposed}")


if __name__ == "__main__":
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    _main()
