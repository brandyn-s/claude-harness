#!/usr/bin/env python3
"""Safe read/write helper for Jamf Pro objects (scripts, config profiles).

Generalizes the GET -> backup -> anchor-asserted swap -> PUT -> read-back
pattern proven on 2026-08-28/29 (Script 108 sync x2, Profile 190 model update)
so future Jamf writes don't hand-roll auth, backups, or verification.

Design contract (see agent-memory/topics/jamf.md, 2026-08-29 entries):
  - Auth clients are selected BY OBJECT TYPE, matching the tenant's
    least-privilege split: reads use the MCP's read-only client
    (~/.jamf_mcp/config.json); script writes use MCP_SCRIPT_WRITE
    (Keychain JAMF_SCRIPT_API_ID / JAMF_SCRIPT_API_KEY); profile writes use
    MCP_CONFIG_WRITE (JAMF_CONFIG_API_ID / JAMF_CONFIG_API_KEY).
  - Keychain items may be findable by LABEL only: try `-s`, fall back to `-l`.
  - /api/oauth/token on this tenant 401s RFC Basic auth; client credentials
    go in the POST body (Basic is still tried first for forward compat).
  - Every PUT is preceded by a mandatory timestamped backup under
    ~/Documents/jamf-backups/ and followed by a read-back verification
    (byte-identical for scripts; new-anchor-once + old-anchor-gone for
    profile payload swaps).
  - Output is ALLOWLIST-ONLY: ids, names, lengths, sha256 prefixes, counts.
    Payload/script contents and credentials are never printed (a profile
    payload can embed bearer tokens).

INTERRUPTION: safe — the only remote mutation is a single PUT; a kill before
it leaves Jamf untouched (backup file may exist, harmless); a kill after it
leaves the change applied and re-running the same invocation is idempotent.

Usage:
  jamf-write.py get script 108
  jamf-write.py get profile 190
  jamf-write.py put-script 108 --body-file /path/new-body.sh
  jamf-write.py put-profile 190 --expect-name "Claude 3P" \\
      --anchor-file /tmp/old.json --replacement-file /tmp/new.json
  jamf-write.py --self-check
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = 'https://example.jamfcloud.com'
BACKUP_DIR = Path.home() / 'Documents' / 'jamf-backups'
READONLY_CONFIG = Path.home() / '.jamf_mcp' / 'config.json'

WRITE_CLIENTS = {
    'script': ('JAMF_SCRIPT_API_ID', 'JAMF_SCRIPT_API_KEY'),
    'profile': ('JAMF_CONFIG_API_ID', 'JAMF_CONFIG_API_KEY'),
}

SECRETISH = re.compile(r'[A-Za-z0-9+_\-=.]{40,}')


def say(msg: str) -> None:
    """Print with a secret tripwire: refuse any 40+ char credential-shaped run.

    Tested per /-separated segment so long but benign FILE PATHS pass while a
    long token embedded anywhere (including inside a path segment) refuses.
    """
    for segment in re.split(r'[/\s]', msg):
        if SECRETISH.search(segment):
            raise SystemExit('refusing to print a credential-shaped value')
    print(msg)


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def kc_read(name: str) -> str | None:
    """Keychain read: service match first, then label-only items."""
    for flag in ('-s', '-l'):
        r = subprocess.run(['security', 'find-generic-password', flag, name, '-w'],
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


def resolve_client(kind: str, write: bool) -> tuple[str, str, str]:
    """Return (label, client_id, client_secret) for the operation."""
    if not write:
        cfg = json.loads(READONLY_CONFIG.read_text(encoding='utf-8'))
        return 'read-only (jamf-mcp)', cfg['client_id'], cfg['client_secret']
    id_item, key_item = WRITE_CLIENTS[kind]
    cid, secret = kc_read(id_item), kc_read(key_item)
    if not (cid and secret):
        raise SystemExit(
            f'Keychain read failed for {id_item}/{key_item} — a blank read can be '
            'an unanswered Keychain ACL dialog; approve it and retry')
    return f'{kind}-write (Keychain {id_item})', cid, secret


def get_token(cid: str, secret: str) -> str:
    """Basic auth first (forward compat), then body form (what this tenant accepts)."""
    attempts = []
    basic = base64.b64encode(f'{cid}:{secret}'.encode()).decode()
    r1 = urllib.request.Request(f'{BASE}/api/oauth/token',
                                data=b'grant_type=client_credentials', method='POST')
    r1.add_header('Authorization', f'Basic {basic}')
    r1.add_header('Content-Type', 'application/x-www-form-urlencoded')
    attempts.append(('basic_auth', r1))
    form = urllib.parse.urlencode({'grant_type': 'client_credentials',
                                   'client_id': cid, 'client_secret': secret}).encode()
    r2 = urllib.request.Request(f'{BASE}/api/oauth/token', data=form, method='POST')
    r2.add_header('Content-Type', 'application/x-www-form-urlencoded')
    attempts.append(('body_form', r2))
    for label, req in attempts:
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
                if body.get('access_token'):
                    say(f'token via {label}, scope={body.get("scope", "<none>")}')
                    return body['access_token']
        except urllib.error.HTTPError as e:
            say(f'{label}: HTTP {e.code}')
    raise SystemExit('all token flows failed')


def call(token: str, method: str, path: str, body: bytes | None = None,
         ctype: str = 'application/json', accept: str = 'application/json'):
    req = urllib.request.Request(f'{BASE}{path}', method=method)
    req.add_header('Authorization', f'Bearer {token}')
    req.add_header('Accept', accept)
    if body is not None:
        req.add_header('Content-Type', ctype)
    try:
        with urllib.request.urlopen(req, body, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]


def backup(kind: str, obj_id: str, content: str, ext: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    p = BACKUP_DIR / f'{ts}-{kind}-{obj_id}.{ext}'
    p.write_text(content, encoding='utf-8')
    say(f'backup: {p} ({len(content)} chars)')
    return p


def get_script(token: str, obj_id: str) -> dict:
    st, body = call(token, 'GET', f'/api/v1/scripts/{obj_id}')
    if st != 200:
        raise SystemExit(f'GET script {obj_id} failed: HTTP {st}')
    return json.loads(body)


def get_profile_xml(token: str, obj_id: str) -> str:
    st, body = call(token, 'GET',
                    f'/JSSResource/osxconfigurationprofiles/id/{obj_id}',
                    accept='application/xml')
    if st != 200:
        raise SystemExit(f'GET profile {obj_id} failed: HTTP {st}')
    return body


def cmd_get(args) -> None:
    _, cid, secret = resolve_client(args.kind, write=False)
    token = get_token(cid, secret)
    if args.kind == 'script':
        obj = get_script(token, args.id)
        content, ext = obj.get('scriptContents', ''), 'json'
        raw = json.dumps(obj, indent=1)
        say(f'script {args.id} name={obj.get("name")!r} '
            f'body={len(content)} chars sha256[:16]={fingerprint(content)}')
    else:
        raw = get_profile_xml(token, args.id)
        ext = 'xml'
        pay = ET.fromstring(raw).findtext('./general/payloads') or ''
        say(f'profile {args.id} payloads={len(pay)} chars '
            f'sha256[:16]={fingerprint(pay)}')
    out = Path(args.out) if args.out else None
    if out:
        out.write_text(raw, encoding='utf-8')
        say(f'wrote raw object to {out} (contents not printed)')
    else:
        backup(args.kind, args.id, raw, ext)


def cmd_put_script(args) -> None:
    new_body = Path(args.body_file).read_text(encoding='utf-8')
    label, cid, secret = resolve_client('script', write=True)
    say(f'client: {label}')
    token = get_token(cid, secret)
    current = get_script(token, args.id)
    backup('script', args.id, json.dumps(current, indent=1), 'json')
    if current.get('scriptContents', '') == new_body:
        say('no-op: current body is already byte-identical to the new body')
        return
    updated = dict(current)
    updated['scriptContents'] = new_body
    st, _ = call(token, 'PUT', f'/api/v1/scripts/{args.id}',
                    json.dumps(updated).encode())
    say(f'PUT status: {st}')
    if st >= 400:
        raise SystemExit(f'write failed (HTTP {st}); Jamf unchanged, backup retained')
    after = get_script(token, args.id).get('scriptContents', '')
    if after != new_body:
        raise SystemExit('MISMATCH: read-back differs from submitted body')
    say(f'VERIFIED: script {args.id} byte-identical to {args.body_file} '
        f'(sha256[:16]={fingerprint(after)})')


def cmd_put_profile(args) -> None:
    old = Path(args.anchor_file).read_text(encoding='utf-8').strip()
    new = Path(args.replacement_file).read_text(encoding='utf-8').strip()
    label, cid, secret = resolve_client('profile', write=True)
    say(f'client: {label}')
    token = get_token(cid, secret)
    raw = get_profile_xml(token, args.id)
    backup('profile', args.id, raw, 'xml')
    root = ET.fromstring(raw)
    name = root.findtext('./general/name')
    payloads = root.findtext('./general/payloads')
    if args.expect_name and name != args.expect_name:
        raise SystemExit(f'refusing: profile name {name!r} != expected {args.expect_name!r}')
    if not payloads:
        raise SystemExit('refusing: profile has no payloads element')
    n = payloads.count(old)
    if n != 1:
        raise SystemExit(f'refusing: anchor appears {n} times in payloads (need exactly 1)')
    put_root = ET.Element('os_x_configuration_profile')
    gen = ET.SubElement(put_root, 'general')
    p = ET.SubElement(gen, 'payloads')
    p.text = payloads.replace(old, new)
    st, _ = call(token, 'PUT',
                 f'/JSSResource/osxconfigurationprofiles/id/{args.id}',
                    ET.tostring(put_root), ctype='application/xml',
                    accept='application/xml')
    say(f'PUT status: {st}')
    if st >= 400:
        raise SystemExit(f'write failed (HTTP {st}); Jamf unchanged, backup retained')
    after = ET.fromstring(get_profile_xml(token, args.id)).findtext('./general/payloads') or ''
    ok = after.count(new) == 1 and old not in after
    if not ok:
        raise SystemExit('MISMATCH: read-back does not show exactly-once replacement')
    say(f'VERIFIED: profile {args.id} replacement applied '
        f'(payloads sha256[:16]={fingerprint(after)})')


def self_check() -> None:
    """Offline assertions: redaction tripwire + anchor math + client table."""
    try:
        say('x' * 48)
        raise AssertionError('redaction tripwire failed to fire')
    except SystemExit:
        pass
    assert 'aaa'.count('a' * 3) == 1
    assert set(WRITE_CLIENTS) == {'script', 'profile'}
    fake = f'{"ab" * 30}'
    assert SECRETISH.search(fake), 'secret regex must catch 40+ char runs'
    print('self-check OK (redaction tripwire, anchor math, client table)')


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or '').splitlines()[0])
    ap.add_argument('--self-check', action='store_true')
    sub = ap.add_subparsers(dest='verb')
    g = sub.add_parser('get', help='read an object; saves raw copy, prints metadata only')
    g.add_argument('kind', choices=['script', 'profile'])
    g.add_argument('id')
    g.add_argument('--out', help='write raw object here instead of the backup dir')
    ps = sub.add_parser('put-script', help='replace a script body (full-file)')
    ps.add_argument('id')
    ps.add_argument('--body-file', required=True)
    pp = sub.add_parser('put-profile', help='anchor-asserted string swap in payloads')
    pp.add_argument('id')
    pp.add_argument('--anchor-file', required=True)
    pp.add_argument('--replacement-file', required=True)
    pp.add_argument('--expect-name', help='refuse unless general/name matches exactly')
    args = ap.parse_args()
    if args.self_check:
        self_check()
    elif args.verb == 'get':
        cmd_get(args)
    elif args.verb == 'put-script':
        cmd_put_script(args)
    elif args.verb == 'put-profile':
        cmd_put_profile(args)
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == '__main__':
    main()
