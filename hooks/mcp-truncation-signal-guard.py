"""Advisory PostToolUse guard: surface MCP truncation signals on the main thread.

Generated from staged spec: hooks/staged/mcp-truncation-signal-guard.spec.md
Installed by /ship-hook on 2026-08-29.

Three signal families (spec section "Detection"):
  1. gateway size cap  — plain-text trailing marker `_mcp_truncated=true`
  2. cap-signaling     — JSON fields `capped: true` / `capped_hint`
  3. page exhaustion   — integer compare `scannedCount < totalCount`

Marker: TRUNCATION_SIGNAL (staleness tracking).
Advisory ONLY (systemMessage; exit 0 always). Sampling is often deliberate —
blocking would train routing-around, which platform-constraints forbids.
INTERRUPTION: safe — read-only observer, no state.
"""
import json
import re
import sys

MARKER = '_mcp_truncated=true'
CAP_RE = re.compile(r'effective_cap=(\d+)')


def _texts(resp):
    """Flatten a tool_response into text blocks, tolerating every shape seen."""
    out = []
    if isinstance(resp, str):
        out.append(resp)
    elif isinstance(resp, list):
        for b in resp:
            if isinstance(b, dict) and isinstance(b.get('text'), str):
                out.append(b['text'])
            elif isinstance(b, str):
                out.append(b)
    elif isinstance(resp, dict):
        c = resp.get('content')
        if c is not None:
            out.extend(_texts(c))
        elif isinstance(resp.get('text'), str):
            out.append(resp['text'])
        else:
            out.append(json.dumps(resp))
    return out


def _parse_json(text):
    """json.loads, falling back to raw_decode so JSON-plus-trailing-marker parses."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        try:
            obj, _ = json.JSONDecoder().raw_decode(text.lstrip())
            return obj
        except (json.JSONDecodeError, AttributeError):
            return None


def _walk(obj):
    """Yield every dict nested anywhere in obj."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def detect(tool_name, resp):
    """Return a list of advisory strings (empty = silent)."""
    findings = []
    for text in _texts(resp):
        if MARKER in text:
            cap = CAP_RE.search(text)
            findings.append(
                f'[truncation] {tool_name}: response carries {MARKER}'
                + (f' effective_cap={cap.group(1)}' if cap else '')
                + ' — the payload was size-capped by the gateway; treat it as PARTIAL.')
        obj = _parse_json(text)
        if obj is None:
            continue
        for d in _walk(obj):
            if d.get('capped') is True:
                hint = d.get('capped_hint')
                findings.append(
                    f'[truncation] {tool_name}: capped=true'
                    + (f' ({hint})' if isinstance(hint, str) else '')
                    + ' — this is a SAMPLE, not a census.')
            sc, tc = d.get('scannedCount'), d.get('totalCount')
            if isinstance(sc, int) and isinstance(tc, int) and sc < tc:
                pages = ''
                sp, mp = d.get('scannedPages'), d.get('maxPages')
                if isinstance(sp, int) and isinstance(mp, int):
                    pages = f' (scannedPages {sp} / maxPages {mp})'
                findings.append(
                    f'[truncation] {tool_name} returned scannedCount={sc} of '
                    f'totalCount={tc}{pages}. This is a SAMPLE, not a census. '
                    'Re-run with a higher max_pages/page_size, or state the cap '
                    'in any count claim.')
    # Dedup while preserving order; cap the advisory to 2 lines.
    seen, uniq = set(), []
    for f in findings:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq[:2]


def main():
    try:
        data = json.loads(sys.stdin.read())
        tool_name = data.get('tool_name', '')
        if not tool_name.startswith('mcp__'):
            sys.exit(0)
        findings = detect(tool_name, data.get('tool_response'))
        if findings:
            print(json.dumps({'systemMessage': '\n'.join(findings)}))
        sys.exit(0)
    except Exception:
        sys.exit(0)  # a guard that raises on odd shapes is worse than silence


if __name__ == '__main__':
    main()
