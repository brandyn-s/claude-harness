#!/usr/bin/env python3
"""ai-access — grant / revoke / inspect access to Private AI, Open WebUI,
LibreChat, and the MCPs from one callable.

Built 2026-08-25 because granting one cohort three products required re-deriving
the grant unit per product across Graph, two Terraform roots, and OPA data.
The map (ai-access-map.json, same directory) encodes the measured model:

  USER  grant  -> add to the product's canonical gating GROUP (one membership op)
  GROUP grant  -> direct appRoleAssignedTo on each of the product's SPs
                  (app assignment does NOT cascade to nested groups)

Verbs:
  products                       show the map and each product's gates
  status  <principal>            effective access per product, with the path
  grant   <principal> <product>... [--via GROUP]   (mcp-gateway requires --via)
  revoke  <principal> <product>... [--via GROUP]
  list    <product>              principals currently granted

Every write prints its exact target set first, applies, then READS BACK.
Status and revoke honor the union rule: access = union(ALL transitive groups)
∪ direct assignments — removing one path is not removal of access, and the
tool says what still grants.

Auth: app-only Graph via msgraph_helper (gateway app; Group.ReadWrite.All +
AppRoleAssignment.ReadWrite.All). Read-only verbs need no flags.

INTERRUPTION: safe — every write is a single idempotent Graph POST/DELETE with
a per-item ledger printed as it goes; re-running converges (already-member and
already-assigned are treated as success).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from msgraph_helper import (  # noqa: E402
    graph_add_group_member,
    graph_delete,
    graph_get,
    graph_get_all,
    graph_post,
    graph_remove_group_member,
    odata_quote,
)

MAP_PATH = Path(__file__).resolve().parent / "ai-access-map.json"
MAP = json.loads(MAP_PATH.read_text(encoding="utf-8"))
GROUPS = MAP["groups"]
PRODUCTS = MAP["products"]
DEFAULT_ROLE = "00000000-0000-0000-0000-000000000000"


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def resolve_principal(ident: str) -> dict:
    """Resolve an email/UPN, group name, or object id to {id, type, display}."""
    ident = ident.strip()
    if ident in GROUPS:  # map-known group name
        return {"id": GROUPS[ident], "type": "group", "display": ident}
    if len(ident) == 36 and ident.count("-") == 4:  # object id: ask Graph what it is
        obj, err = graph_get(f"/directoryObjects/{ident}")
        if err:
            die(f"object id {ident} not found: {err}")
        kind = "group" if obj["@odata.type"].endswith("group") else "user"
        return {"id": ident, "type": kind,
                "display": obj.get("displayName") or obj.get("userPrincipalName") or ident}
    if "@" in ident:  # UPN/email
        q = odata_quote(ident)
        users, err = graph_get_all(
            "/users", {"$filter": f"userPrincipalName eq '{q}' or mail eq '{q}'",
                       "$select": "id,displayName,userPrincipalName,accountEnabled"})
        if err:
            die(f"user lookup failed: {err}")
        if len(users) != 1:
            die(f"{ident}: {len(users)} directory matches (need exactly 1)")
        u = users[0]
        if not u.get("accountEnabled"):
            print(f"NOTE: {ident} is DISABLED in Entra")
        return {"id": u["id"], "type": "user", "display": u["userPrincipalName"]}
    # bare group display name
    q = odata_quote(ident)
    grps, err = graph_get_all("/groups", {"$filter": f"displayName eq '{q}'",
                                          "$select": "id,displayName"})
    if err:
        die(f"group lookup failed: {err}")
    if len(grps) != 1:
        die(f"group {ident!r}: {len(grps)} matches (need exactly 1)")
    return {"id": grps[0]["id"], "type": "group", "display": grps[0]["displayName"]}


_TRANSITIVE_CACHE: dict[str, set[str]] = {}
_ASSIGN_CACHE: dict[str, list[dict]] = {}


def transitive_group_ids(user_id: str) -> set[str]:
    if user_id not in _TRANSITIVE_CACHE:
        rows, err = graph_get_all(f"/users/{user_id}/transitiveMemberOf",
                                  {"$select": "id"}, max_pages=20)
        if err:
            die(f"transitiveMemberOf failed: {err}")
        _TRANSITIVE_CACHE[user_id] = {r["id"] for r in rows}
    return _TRANSITIVE_CACHE[user_id]


def sp_assignments(sp_id: str, fresh: bool = False) -> list[dict]:
    """Cached within one invocation; pass fresh=True after a write."""
    if fresh or sp_id not in _ASSIGN_CACHE:
        rows, err = graph_get_all(f"/servicePrincipals/{sp_id}/appRoleAssignedTo",
                                  {"$select": "id,principalId,principalDisplayName,principalType,appRoleId"})
        if err:
            die(f"appRoleAssignedTo read failed for {sp_id}: {err}")
        _ASSIGN_CACHE[sp_id] = rows
    return _ASSIGN_CACHE[sp_id]


def product_names(args_products: list[str]) -> list[str]:
    """Expand map-defined aliases; validate names."""
    aliases = MAP.get("aliases", {})
    out = []
    for p in args_products:
        if p in aliases:
            out += aliases[p]
        elif p in PRODUCTS:
            out.append(p)
        else:
            die(f"unknown product {p!r}. Known: {', '.join(sorted(PRODUCTS))}"
                f" (+ aliases: {', '.join(sorted(aliases))})")
    return list(dict.fromkeys(out))


def save_map():
    """Atomic rewrite of the map file (write temp, then replace)."""
    tmp = MAP_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(MAP, indent=2) + "\n", encoding="utf-8")
    tmp.replace(MAP_PATH)


def resolve_sp(ident: str) -> dict:
    """Resolve an SP by display name, appId, or object id → full SP object."""
    ident = ident.strip()
    if len(ident) == 36 and ident.count("-") == 4:
        flt = f"id eq '{ident}' or appId eq '{ident}'"
    else:
        flt = f"displayName eq '{odata_quote(ident)}'"
    sps, err = graph_get_all("/servicePrincipals", {
        "$filter": flt,
        "$select": "id,appId,displayName,appRoleAssignmentRequired,appRoles"})
    if err:
        die(f"SP lookup failed: {err}")
    if len(sps) != 1:
        die(f"SP {ident!r}: {len(sps)} matches (need exactly 1)")
    return sps[0]


# ---------------------------------------------------------------- status ----
def effective_paths(principal: dict, product: str) -> tuple[bool, list[str]]:
    """(has_access, [description of every granting path])."""
    spec = PRODUCTS[product]
    if spec.get("open_to_tenant"):
        return True, ["open to every tenant user (no gate exists)"]
    pid = principal["id"]
    member_of = transitive_group_ids(pid) if principal["type"] == "user" else set()
    paths = []
    for sp in spec["service_principals"]:
        rows = sp_assignments(sp["sp_id"])
        granting = {r["principalId"]: r for r in rows if r["appRoleId"] == sp["role_id"]}
        hit = []
        if pid in granting:
            hit.append(f"direct assignment ({principal['type']})")
        for gid in member_of & set(granting):
            hit.append(f"member of {granting[gid]['principalDisplayName']!r}")
        if hit:
            paths.append(f"{sp['name']}: " + "; ".join(hit))
        else:
            paths.append(f"{sp['name']}: NO PATH")
    has = all("NO PATH" not in p for p in paths)
    return has, paths


def cmd_status(principal: dict):
    print(f"principal: {principal['display']} ({principal['type']}, {principal['id']})\n")
    for name in sorted(PRODUCTS):
        has, paths = effective_paths(principal, name)
        print(f"{'HAS  ' if has else 'LACKS'} {name}")
        for p in paths:
            print(f"        {p}")
        if has and PRODUCTS[name].get("second_gate"):
            print("        (a non-Entra second gate also applies — see `products`)")
    print("\n(status = union of ALL transitive groups + direct assignments; a single")
    print(" group removal does not necessarily remove access — use revoke, it re-checks.)")


# ----------------------------------------------------------------- grant ----
def grant_user(principal: dict, product: str, via: str | None):
    spec = PRODUCTS[product]
    group_name = via or spec.get("canonical_group")
    if not group_name:
        die(f"{product}: no canonical group — name one with --via "
            f"({', '.join(spec.get('requires_named_group', []))})")
    if spec.get("requires_named_group") and group_name not in spec["requires_named_group"]:
        die(f"{product}: --via must be one of {spec['requires_named_group']}")
    gid = GROUPS.get(group_name) or die(f"group {group_name!r} not in map")
    print(f"  TARGET: add {principal['display']} to group {group_name} ({gid})")
    res, err = graph_add_group_member(gid, principal["id"])
    if err:
        die(f"add failed: {err}")
    print(f"  {'already a member' if res == 'ALREADY_MEMBER' else 'ADDED'}")


def grant_group(principal: dict, product: str):
    spec = PRODUCTS[product]
    for sp in spec["service_principals"]:
        print(f"  TARGET: assign group {principal['display']} -> {sp['name']} role {sp['role']}")
        body = {"principalId": principal["id"], "resourceId": sp["sp_id"], "appRoleId": sp["role_id"]}
        _, err = graph_post(f"/servicePrincipals/{sp['sp_id']}/appRoleAssignedTo", body=body)
        if err and "already exist" in err.lower():
            print("  already assigned")
        elif err:
            die(f"assign failed: {err}")
        else:
            print("  ASSIGNED")
    if spec.get("second_gate"):
        print(f"  NOTE second gate (NOT done by this tool): {spec['second_gate']}")


def cmd_grant(principal: dict, products: list[str], via: str | None):
    for product in products:
        spec = PRODUCTS[product]
        print(f"\n=== grant {product} ===")
        if spec.get("open_to_tenant"):
            print("  nothing to grant — open to tenant. Per-user prerequisite: " + spec["note"])
            continue
        if principal["type"] == "user":
            grant_user(principal, product, via)
        else:
            grant_group(principal, product)
    verify(principal, products, expect=True)


# ---------------------------------------------------------------- revoke ----
def cmd_revoke(principal: dict, products: list[str], via: str | None):
    for product in products:
        spec = PRODUCTS[product]
        print(f"\n=== revoke {product} ===")
        if spec.get("open_to_tenant"):
            print("  cannot revoke — no gate exists on this product.")
            continue
        if principal["type"] == "user":
            group_name = via or spec.get("canonical_group")
            if not group_name:
                die(f"{product}: name the group with --via")
            gid = GROUPS[group_name]
            print(f"  TARGET: remove {principal['display']} from group {group_name} ({gid})")
            res, err = graph_remove_group_member(gid, principal["id"])
            if err:
                die(f"remove failed: {err}")
            print(f"  {'was not a member' if res == 'NOT_A_MEMBER' else 'REMOVED'}")
        else:
            for sp in spec["service_principals"]:
                rows = sp_assignments(sp["sp_id"])
                mine = [r for r in rows if r["principalId"] == principal["id"]
                        and r["appRoleId"] == sp["role_id"]]
                if not mine:
                    print(f"  {sp['name']}: no assignment to remove")
                    continue
                print(f"  TARGET: remove group assignment {principal['display']} from {sp['name']}")
                _, err = graph_delete(f"/servicePrincipals/{sp['sp_id']}/appRoleAssignedTo/{mine[0]['id']}")
                if err:
                    die(f"unassign failed: {err}")
                print("  REMOVED")
    verify(principal, products, expect=False)


def verify(principal: dict, products: list[str], expect: bool):
    """Read back effective access; on revoke, name every path that still grants."""
    # Never verify from pre-write caches — a stale read here would either
    # false-MISMATCH a successful revoke or, worse, stale-pass a failed grant.
    _ASSIGN_CACHE.clear()
    _TRANSITIVE_CACHE.clear()
    print("\n--- read-back verification ---")
    ok = True
    for product in products:
        if PRODUCTS[product].get("open_to_tenant"):
            continue
        has, paths = effective_paths(principal, product)
        verdict = "OK" if has == expect else "MISMATCH"
        if verdict == "MISMATCH":
            ok = False
        print(f"  {verdict}: {product} effective access = {has} (expected {expect})")
        if has and not expect:
            for p in paths:
                if "NO PATH" not in p:
                    print(f"      STILL GRANTED via {p}")
    print("VERDICT:", "PASS" if ok else "PARTIAL — see paths above (union rule)")
    if expect:
        print("Reminder: role changes need a full sign-out/sign-in; Open WebUI's "
              "'Check Again' does not re-run OAuth.")


# ------------------------------------------------------------------ list ----
def cmd_list(product: str):
    spec = PRODUCTS.get(product) or die(f"unknown product {product!r}")
    if spec.get("open_to_tenant"):
        print(spec["note"]); return
    for sp in spec["service_principals"]:
        rows = sp_assignments(sp["sp_id"])
        rel = [r for r in rows if r["appRoleId"] == sp["role_id"]]
        print(f"\n{sp['name']} — role {sp['role']} — {len(rel)} principal(s):")
        for r in sorted(rel, key=lambda x: (x["principalType"], x["principalDisplayName"] or "")):
            print(f"  {r['principalType']:6s} {r['principalDisplayName']}")


# --------------------------------------------------------------- onboard ----
def cmd_onboard(a):
    """Discover a live SP and write a map entry for it — the extension path.

    New frontend/MCP = one command, not hand-measured JSON. Reads the SP live,
    resolves the role id by NAME, records current group assignments, and
    refuses shapes that would lie (a 'gated' product whose SP does not enforce
    assignment, an ambiguous role, a duplicate product name).
    """
    if a.product in PRODUCTS:
        die(f"product {a.product!r} already exists — edit the map or pick a new name")
    if a.product in MAP.get("aliases", {}):
        die(f"{a.product!r} collides with an alias")
    if a.open and a.add_sp:
        die("--open takes a single SP (the one whose openness is verified); drop --add-sp")
    sps = []
    for ident in [a.sp] + (a.add_sp or []):
        sp = resolve_sp(ident)
        roles = {r["value"]: r["id"] for r in (sp.get("appRoles") or []) if r.get("isEnabled")}
        role_name, role_id = "default-access", DEFAULT_ROLE
        if a.open:
            pass  # no role needed; we record the SP only to VERIFY openness
        elif roles and not a.role:
            die(f"{sp['displayName']!r} defines appRoles {sorted(roles)} — pick one with --role")
        elif a.role:
            if a.role not in roles:
                die(f"{sp['displayName']!r} has no enabled role {a.role!r} (has {sorted(roles)})")
            role_name, role_id = a.role, roles[a.role]
        else:
            role_name, role_id = "default-access", DEFAULT_ROLE
        if not a.open and not sp.get("appRoleAssignmentRequired"):
            die(f"{sp['displayName']!r} has appRoleAssignmentRequired=false — an assignment "
                f"there grants NOTHING. Onboard with --open (ungated) or fix the SP first.")
        if a.open:
            sps.append({"verify_sp": sp})
        else:
            entry = {"name": sp["displayName"], "sp_id": sp["id"],
                     "role": role_name, "role_id": role_id}
            assigned = [r["principalDisplayName"] for r in sp_assignments(sp["id"])]
            print(f"  {sp['displayName']}: role={role_name} currently assigned: "
                  f"{sorted(set(assigned)) or '(none)'}")
            sps.append(entry)

    entry: dict = {"display": a.display or a.sp}
    if a.open:
        sp0 = sps[0]["verify_sp"]
        entry["open_to_tenant"] = True
        entry["verify_open"] = {"sp_id": sp0["id"], "expect_assignment_required": False}
        entry["service_principals"] = []
        entry["note"] = a.note or "No gate: appRoleAssignmentRequired=false (verified at onboard)."
    else:
        entry["service_principals"] = sps
        if a.canonical_group:
            g = resolve_principal(a.canonical_group)
            if g["type"] != "group":
                die(f"--canonical-group {a.canonical_group!r} is not a group")
            GROUPS.setdefault(g["display"], g["id"])
            entry["canonical_group"] = g["display"]
        else:
            entry["canonical_group"] = None
            print("  NOTE: no canonical group — user grants will require --via")
        if a.second_gate:
            entry["second_gate"] = a.second_gate
    PRODUCTS[a.product] = entry
    save_map()
    print(f"\nwrote product {a.product!r} to {MAP_PATH.name}:")
    print(json.dumps(entry, indent=2))
    print("\nvalidating the new entry against live Entra:")
    validate_product(a.product)


# -------------------------------------------------------------- validate ----
def validate_product(name: str) -> bool:
    """Re-measure one map entry against live Entra. Returns ok."""
    spec = PRODUCTS[name]
    ok = True
    if spec.get("open_to_tenant"):
        vo = spec.get("verify_open")
        if not vo:
            print(f"  WARN {name}: open_to_tenant is UNVERIFIABLE (no verify_open sp_id)")
            return True
        sp, err = graph_get(f"/servicePrincipals/{vo['sp_id']}",
                            params={"$select": "id,displayName,appRoleAssignmentRequired"})
        if err:
            print(f"  FAIL {name}: verify_open SP unreadable: {err}"); return False
        if sp["appRoleAssignmentRequired"] != vo["expect_assignment_required"]:
            print(f"  FAIL {name}: {sp['displayName']!r} appRoleAssignmentRequired flipped to "
                  f"{sp['appRoleAssignmentRequired']} — this product is NO LONGER open; "
                  f"the map is lying until updated")
            return False
        print(f"  ok   {name}: still open ({sp['displayName']!r} assignmentRequired="
              f"{sp['appRoleAssignmentRequired']})")
        return True
    for spd in spec["service_principals"]:
        sp, err = graph_get(f"/servicePrincipals/{spd['sp_id']}",
                            params={"$select": "id,displayName,appRoleAssignmentRequired,appRoles"})
        if err:
            print(f"  FAIL {name}: SP {spd['name']!r} unreadable: {err}"); ok = False; continue
        live_roles = {r["id"] for r in (sp.get("appRoles") or []) if r.get("isEnabled")}
        live_roles.add(DEFAULT_ROLE)
        if spd["role_id"] not in live_roles:
            print(f"  FAIL {name}: role {spd['role']!r} ({spd['role_id']}) no longer on "
                  f"{sp['displayName']!r}"); ok = False
        if not sp.get("appRoleAssignmentRequired"):
            print(f"  FAIL {name}: {sp['displayName']!r} appRoleAssignmentRequired=false — "
                  f"the gate is COSMETIC"); ok = False
        if sp["displayName"] != spd["name"]:
            print(f"  WARN {name}: SP renamed {spd['name']!r} -> {sp['displayName']!r}")
    cg = spec.get("canonical_group")
    if cg:
        gid = GROUPS.get(cg)
        g, err = graph_get(f"/groups/{gid}", params={"$select": "id,displayName"})
        if err:
            print(f"  FAIL {name}: canonical group {cg!r} ({gid}) unreadable: {err}"); ok = False
        elif g["displayName"] != cg:
            print(f"  WARN {name}: canonical group renamed {cg!r} -> {g['displayName']!r}")
    if ok:
        print(f"  ok   {name}")
    return ok


def cmd_validate():
    print(f"validating {len(PRODUCTS)} products against live Entra:")
    results = [validate_product(n) for n in sorted(PRODUCTS)]
    bad = results.count(False)
    print(f"\nVERDICT: {'PASS — map matches live state' if not bad else f'{bad} product(s) DRIFTED'}")
    sys.exit(0 if not bad else 1)


def cmd_products():
    for name in sorted(PRODUCTS):
        spec = PRODUCTS[name]
        gate = ("OPEN (no gate)" if spec.get("open_to_tenant")
                else f"canonical group: {spec.get('canonical_group') or '--via required: ' + '/'.join(spec.get('requires_named_group', []))}")
        print(f"{name:18s} {spec['display']}\n{'':18s} {gate}")
        for sp in spec.get("service_principals", []):
            print(f"{'':18s} SP {sp['name']} ({sp['role']})")
        if spec.get("second_gate"):
            print(f"{'':18s} SECOND GATE: {spec['second_gate']}")
        print()


def main():
    ap = argparse.ArgumentParser(
        description="ai-access — grant / revoke / inspect access to Private AI, "
                    "Open WebUI, LibreChat, and the MCPs from one callable.")
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("products")
    sub.add_parser("validate")
    ob = sub.add_parser("onboard", help="add a new frontend/MCP from live Entra state")
    ob.add_argument("--sp", required=True, help="SP displayName, appId, or object id")
    ob.add_argument("--product", required=True, help="new product key")
    ob.add_argument("--role", help="appRole value when the SP defines roles")
    ob.add_argument("--add-sp", action="append", help="additional SP (e.g. the API SP)")
    ob.add_argument("--canonical-group", help="gating group for user grants")
    ob.add_argument("--open", action="store_true", help="ungated product (verified live)")
    ob.add_argument("--display", help="display name")
    ob.add_argument("--second-gate", help="text describing a non-Entra gate")
    ob.add_argument("--note", help="note for open products")
    for v in ("status",):
        p = sub.add_parser(v); p.add_argument("principal")
    for v in ("grant", "revoke"):
        p = sub.add_parser(v)
        p.add_argument("principal")
        p.add_argument("products", nargs="+")
        p.add_argument("--via", help="gating group when the product has no canonical group")
    p = sub.add_parser("list"); p.add_argument("product")
    a = ap.parse_args()

    if a.verb == "products":
        cmd_products(); return
    if a.verb == "validate":
        cmd_validate(); return
    if a.verb == "onboard":
        cmd_onboard(a); return
    if a.verb == "list":
        cmd_list(a.product); return
    principal = resolve_principal(a.principal)
    if a.verb == "status":
        cmd_status(principal)
    elif a.verb == "grant":
        cmd_grant(principal, product_names(a.products), a.via)
    elif a.verb == "revoke":
        cmd_revoke(principal, product_names(a.products), a.via)


if __name__ == "__main__":
    main()
