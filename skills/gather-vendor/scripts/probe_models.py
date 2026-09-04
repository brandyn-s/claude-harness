#!/usr/bin/env python3
"""Pinned-model liveness probe — the vendor analog of gather-claude's
installed-version sweep, shared by /gather-vendor and the probe-before-panel
preflight in roundtable + x-monitor.

Confirms each pinned model ID still resolves on the vendor's models endpoint,
and — as far as a metadata call CAN — flags the retirement shapes that have
burned this org. Prints STATUS ONLY (never keys, never bodies beyond
id/version/fingerprint), so output is transcript-safe and cron-safe.

What this DOES detect (metadata GET):
  - pin fully retired (404/410)
  - xAI silent slug-redirect (200 served by a DIFFERENT canonical id)
  - xAI same-slug weight swap (version/fingerprint change on a stable id)
  - auth failure vs retirement (401/403 branch — NOT a retirement)
  - Gemini catalog truncation (full pagination + cap tripwire)

What it does NOT detect (documented limits — see the skill's Step 2 notes):
  - endpoint/path INVOCABILITY (the Live-Search-410 class): a model id can
    resolve 200 while the endpoint the tooling rides is retired.
  - Gemini listing != serving: a model can appear in ListModels after its
    shutdown date. Cross-check the deprecations table (skill Step 2).

Usage: python3 probe_models.py <vendor> [model_id ...]
Vendors: openai | gemini | xai   (grok is accepted as an alias for xai — the
skill's vendor token). Pass the LIVE pins as args — do not rely on the
DEFAULTS, which are a documented fallback that drifts from the tooling.

Exit codes (so a preflight can gate precisely):
  0 = every probed pin PRESENT (canonical)
  1 = RETIREMENT class — a pin is retired / silently redirected / missing /
      schema-drifted. Actionable now; a caller SHOULD abort.
  2 = TRANSIENT or AUTH-INFRA — network blip / 5xx / 429 / 401/403 / key not
      found. Re-runnable or an infra fix; a caller should WARN, not abort.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

OK, RETIRE, TRANSIENT = 0, 1, 2

DEFAULTS = {
    "openai": ["gpt-5.5-pro"],
    "xai": ["grok-4.3", "grok-4.20-0309-reasoning"],
    "gemini": [],  # no runtime pin; probe enumerates the flagship set instead
}
ALIASES = {"grok": "xai"}  # the skill's vendor token -> the API's vendor key
# Each vendor lists candidate names in priority order: env var first, then Keychain
# items. OpenAI Keychain items were renamed 2026-08-04 (OPENAI_API_KEY is gone;
# inference key is OPENAI_PLATFORM_API) — see memory/openai-keychain-items.md.
KEY_SERVICE = {
    "openai": ["OPENAI_API_KEY", "OPENAI_PLATFORM_API"],
    "xai": ["XAI_API_KEY"],
    "gemini": ["GEMINI_API_KEY"],
}
GEMINI_PAGE_CAP = 25  # tripwire: a real catalog is ~50/page; more pages = paging bug/loop


def resolve_key(services):
    """env first (adapters resolve from env), then Keychain, per candidate name."""
    for service in services:
        key = os.environ.get(service) or _keychain(service)
        if key:
            return key
    return None


def _keychain(service):
    out = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True,
    )
    return out.stdout.decode("utf-8").strip() if out.returncode == 0 else None


def get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        return None, str(e.reason).encode()


def _verdict_for_status(status, model):
    """Return (message, severity) for a non-200 status."""
    if status in (401, 403):
        return f"{model}: HTTP {status} — AUTH FAILURE (key problem, NOT retirement; check key/rotation)", TRANSIENT
    if status == 429:
        return f"{model}: HTTP 429 — RATE LIMITED (transient); re-run before concluding", TRANSIENT
    if status in (404, 410):
        return f"{model}: HTTP {status} — RETIREMENT candidate (check the deprecations page for a successor)", RETIRE
    if status is None:
        return f"{model}: NETWORK/URL error — transient? re-run before concluding", TRANSIENT
    if status >= 500:
        return f"{model}: HTTP {status} — vendor 5xx (transient); re-run before concluding", TRANSIENT
    return f"{model}: HTTP {status} — unexpected; investigate", RETIRE


def probe_gemini(models, key):
    """Full-pagination catalog read (fixes the pageSize=50 page-1-only truncation).

    A recorded flagship SHOULD be passed as a pin (the skill's Step 2 requires
    it); a pin-less call only lists the catalog and cannot detect a retired or
    superseded flagship, so it returns a non-OK 'no pin' signal rather than a
    silent OK.
    """
    names, token, pages = [], None, 0
    while True:
        url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"
        if token:
            url += f"&pageToken={token}"
        status, body = get(url, {"x-goog-api-key": key})
        if status != 200:
            v, sev = _verdict_for_status(status, "gemini models list")
            print(v)
            return sev
        data = json.loads(body)
        names.extend(m["name"].split("/")[-1] for m in data.get("models", []))
        pages += 1
        token = data.get("nextPageToken")
        if not token:
            break
        if pages >= GEMINI_PAGE_CAP:  # tripwire: never seen this many pages legitimately
            print(f"gemini models list: TRIPWIRE — {pages} pages and still paginating "
                  "(pageToken loop or API change?); treating catalog as INCOMPLETE")
            return TRANSIENT
    print(f"gemini models list: HTTP 200, {len(names)} models across {pages} page(s)")
    flagship = sorted(n for n in names if "pro" in n and not n.endswith(("-tts", "-vision")))
    print("  pro-tier visible:", ", ".join(flagship) or "(none)")
    if not models:
        print("  NO flagship pin passed — cannot verify currency. Pass the recorded "
              "flagship id (skill Step 2) so a retired/superseded flagship is caught.")
        return RETIRE  # a currency check that verified nothing is not a pass
    sev = OK
    for m in models:
        if m in names:
            print(f"  pinned {m}: PRESENT in catalog "
                  "(NOTE: listing != serving — cross-check the deprecations table for shutdown date)")
        else:
            print(f"  pinned {m}: MISSING — RETIREMENT?")
            sev = RETIRE
    return sev


def probe_rest(vendor, models, key):
    base, hdr = {
        "openai": ("https://api.openai.com/v1/models/{}", {"Authorization": f"Bearer {key}"}),
        "xai": ("https://api.x.ai/v1/language-models/{}", {"Authorization": f"Bearer {key}"}),
    }[vendor]
    sev = OK
    non200 = 0
    for m in models:
        status, body = get(base.format(m), hdr)
        if status != 200:
            v, s = _verdict_for_status(status, m)
            print(v)
            sev = max(sev, s)
            non200 += 1
            continue
        doc = json.loads(body)
        returned = doc.get("id")
        if returned is None:
            print(f"{m}: HTTP 200 but response has no 'id' field — SCHEMA DRIFT; verify endpoint/version")
            sev = max(sev, RETIRE)
            continue
        if returned != m:
            print(f"{m}: HTTP 200 but canonical id is '{returned}' — "
                  "SILENT REDIRECT (retirement?); update the pin deliberately")
            sev = max(sev, RETIRE)
            continue
        drift = [f"{f}={doc[f]}" for f in ("version", "fingerprint", "created") if f in doc]
        suffix = f"  [{', '.join(drift)}]" if drift else ""
        print(f"{m}: PRESENT (canonical){suffix}")
    if non200 == len(models) and models:
        print(f"NOTE: ALL {len(models)} {vendor} pins non-200 — suspect ENDPOINT/AUTH drift, not mass retirement")
    return sev


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    vendor = ALIASES.get(raw, raw)
    if vendor not in DEFAULTS:
        print(__doc__, file=sys.stderr)
        sys.exit(2)  # usage error is infra, not a retirement finding
    models = sys.argv[2:] or DEFAULTS[vendor]
    key = resolve_key(KEY_SERVICE[vendor])
    if not key:
        print(f"{'/'.join(KEY_SERVICE[vendor])}: not in env or Keychain — AUTH-INFRA, not retirement",
              file=sys.stderr)
        print("  (tried env then `security find-generic-password -s <name>` per candidate; "
              "if the user renamed Keychain items, update KEY_SERVICE — "
              "see memory/openai-keychain-items.md for the 2026-08-04 OpenAI rename)",
              file=sys.stderr)
        sys.exit(TRANSIENT)
    sev = probe_gemini(models, key) if vendor == "gemini" else probe_rest(vendor, models, key)
    sys.exit(sev)


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__ or "<usage TBD>")
        sys.exit(0)
    main()
