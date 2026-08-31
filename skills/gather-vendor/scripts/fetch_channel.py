#!/usr/bin/env python3
"""Fetch a standing channel, assert its content marker, persist the artifact.

Collapses gather-vendor Step 3's fetch/diagnose double-fetch loop (measured 3x
on 2026-08-22: OpenAI changelog date-format drift, llms.txt restructure, pricing
table rewrite each needed a second fetch to diagnose). One call = fetch + marker
assert + write, with the failure classes separated so the caller can act without
re-reading the body:

  exit 0  fetched, marker present, artifact written
  exit 2  HTTP/network failure (transient class — status printed; retry later)
  exit 3  HTTP 200 but marker MISSING (dead/rewritten channel — a FINDING per
          gather-conventions §4, not a retry; first bytes printed for diagnosis)

Usage:
  fetch_channel.py <url> <marker> <outpath> [--ua UA] [--no-retry-429]

The marker is a literal substring (soft-404 defense: vendors return 200 with a
"Page not found" body — see references/openai.md gotchas). A single 429 is
retried once after 12s (Discourse cloud_60_secs_limit, measured 2026-08-22).

INTERRUPTION: safe — writes the artifact atomically via temp file + rename;
a killed run leaves either the prior artifact or none, never a partial body.
"""

import argparse
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

DEFAULT_UA = "Mozilla/5.0 (gather-vendor channel fetch)"
RETRY_429_SLEEP_S = 12


def fetch(url: str, ua: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"FETCH-ERROR {url}: {e}", file=sys.stderr)
        sys.exit(2)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Fetch a standing channel, assert its content marker, persist the artifact.")
    ap.add_argument("url")
    ap.add_argument("marker", help="literal substring that must appear in the body")
    ap.add_argument("outpath")
    ap.add_argument("--ua", default=DEFAULT_UA)
    ap.add_argument("--no-retry-429", action="store_true")
    args = ap.parse_args()

    status, body = fetch(args.url, args.ua)
    if status == 429 and not args.no_retry_429:
        print(f"429 on {args.url} — retrying once in {RETRY_429_SLEEP_S}s", file=sys.stderr)
        time.sleep(RETRY_429_SLEEP_S)
        status, body = fetch(args.url, args.ua)

    if status != 200:
        print(f"HTTP {status} {args.url} — transient class, not a marker verdict",
              file=sys.stderr)
        sys.exit(2)

    text = body.decode("utf-8", errors="replace")
    if args.marker not in text:
        print(f"MARKER MISS on 200 body: {args.url}", file=sys.stderr)
        print(f"  expected literal: {args.marker!r}", file=sys.stderr)
        print(f"  first 200 bytes: {text[:200]!r}", file=sys.stderr)
        print("  -> dead/rewritten channel (gather-conventions §4): open a channel-drift "
              "finding; do NOT advance this channel's Sources Log date", file=sys.stderr)
        sys.exit(3)

    out_dir = os.path.dirname(os.path.abspath(args.outpath)) or "."
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=".fetch_channel-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        os.replace(tmp, args.outpath)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    print(f"OK 200 {len(body)}B marker={args.marker!r} -> {args.outpath}")


if __name__ == "__main__":
    main()
