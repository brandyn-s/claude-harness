#!/usr/bin/env python3
"""transcript_condense.py — condense a full session transcript into the diagnostic SIGNAL SLICE
that /distill consumes with WHOLE-SESSION judgment.

WHY this replaces the map/synthesize/meta apparatus (red-team 2026-06-21): the prior mega-retro
fanned 79 context-ISOLATED extractors over a 56MB transcript and emitted ~995 disconnected
findings — a transcript CENSUS, not a diagnosis. distill/monitor are valuable precisely because
they are LOSSY in the right direction: they discard ~99% of noise and keep the load-bearing few,
using whole-session/live context to judge what matters. The 995-finding inventory destroyed the
session ARC (goal → error → pivot) by chunking, and frequency-ranking (24× a guard-block) is not
importance-ranking (one data-sovereignty violation > 24 inline-python blocks).

The fix: mega-retro is a COMPACTION-RECOVERY FRONT-END, not a parallel retro engine. After
auto-compaction (10× on a 56MB session) the live context has lost ~90% of the session, so distill
running in-context only sees the surviving tail. This script reconstructs the COMPLETE session as a
condensed, chronological signal slice (measured 3.7–4.2% of raw: ~2–3MB / ~2–4K signal items) that
fits a context window — so distill applies its NORMAL whole-session judgment to the WHOLE session.

KEEP (the diagnostic signal): user text, assistant text, tool calls (name + 1-line input, in
order), ERROR tool_results (capped), compaction-boundary markers, chronological order.
DROP (the noise): thinking, images, SUCCESS tool_result bodies, file-history-snapshot, attachments,
bookkeeping records (pr-link/mode/ai-title/last-prompt/...).

If the slice exceeds --max-tokens (est), prefer compaction boundaries and fall back to diagnostic
record boundaries so every part fits. A single record larger than the budget fails explicitly.
Order + boundary markers are preserved so the arc survives.

Usage:
  python3 transcript_condense.py <transcript.jsonl> --out-dir <dir> [--max-tokens 180000]
                                 [--err-cap 1500] [--tool-input-cap 160]
Emits slice_000.txt .. slice_NNN.txt + condense-manifest.json (part count, signal counts, bytes).
"""
from __future__ import annotations

import argparse
import json
import os
import re

# UTF-8-byte/token ratio for the condensed slice. The slice is prose-heavy
# (user/assistant text) with some structured tool lines; 2.5 bytes/token is
# conservative on measured real slices and remains conservative for multibyte
# text because splitting and manifest reporting use the same byte measure.
BYTES_PER_TOKEN = 2.5
DEFAULT_MAX_TOKENS = 180_000
_KEEP_TYPES = ("user", "assistant")
_TOOL_INPUT_KEYS = (
    "command",
    "cmd",
    "file_path",
    "pattern",
    "path",
    "query",
    "description",
    "prompt",
    "subject",
)
_CODEX_IGNORED_USER_PREFIXES = (
    "<environment_context>",
    "<skill>",
    "<permissions instructions>",
)
_SLICE_NAME_RE = re.compile(r"^slice_[0-9]{3,}\.txt$")
_OUTER_STATUS_RE = re.compile(
    r"(?m)^(?:Process exited with code |Exit code: )(-?\d+)\s*$"
)
_LABELED_STATUS_RE = re.compile(r"(?m)^exit(?:_code)?=(-?\d+)\s*$")
_TEXT_ERROR_RE = re.compile(
    r"(?im)^(?:"
    r"Error:|Script failed|ToolError|"
    r"[a-z_][\w.-]*(?: [a-z_][\w.-]*){0,3} failed:|"
    r"failed to [^:\n]+:|[a-z_][\w.-]* must be\b"
    r")"
)
_SECRET_PATTERNS = (
    (
        "JWT",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\b"
        ),
    ),
    (
        "GITHUB_TOKEN",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    ),
    ("API_KEY", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("AWS_ACCESS_KEY", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
)


def _redact_secrets(text: str) -> str:
    """Redact high-confidence credential shapes before a slice leaves the process."""
    for label, pattern in _SECRET_PATTERNS:
        text = pattern.sub(f"[REDACTED:{label}]", text)
    return text


def _summarize_tool_input(value, tool_input_cap):
    """Return the first useful field from a structured or JSON-encoded tool input."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            value = parsed
        else:
            return f"input={value[:tool_input_cap]}".replace("\n", " ")
    if not isinstance(value, dict):
        return ""
    for key in _TOOL_INPUT_KEYS:
        if value.get(key):
            return f"{key}={str(value[key])[:tool_input_cap]}".replace("\n", " ")
    return ""


def _render_text_blocks(content, prefix):
    """Render only plaintext blocks, excluding encrypted reasoning and media."""
    lines = []
    for block in content or []:
        if not isinstance(block, dict) or block.get("type") not in {
            "input_text",
            "output_text",
            "text",
        }:
            continue
        text = (block.get("text") or "").strip()
        if text:
            lines.append(f"{prefix}: {text}")
    return lines


def _render_codex_message(payload):
    """Render response-item dialogue for rollouts without event-message mirrors."""
    role = payload.get("role")
    if role not in {"user", "assistant"}:
        return []
    prefix = "USER" if role == "user" else "ASST"
    content = payload.get("content")
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    lines = _render_text_blocks(content, prefix)
    if role == "user":
        lines = [
            line
            for line in lines
            if not line.removeprefix("USER: ").lstrip().startswith(
                _CODEX_IGNORED_USER_PREFIXES
            )
        ]
    return lines


def _maybe_json(value):
    """Decode JSON-looking strings while leaving ordinary text unchanged."""
    if not isinstance(value, str) or not value.lstrip().startswith(("{", "[")):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _flatten_text(value):
    """Extract readable diagnostic text from nested Codex output envelopes."""
    value = _maybe_json(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(filter(None, (_flatten_text(item) for item in value)))
    if isinstance(value, dict):
        return " ".join(
            filter(
                None,
                (
                    _flatten_text(value[key])
                    for key in ("error", "message", "output", "content", "text")
                    if key in value
                ),
            )
        )
    return ""


def _explicit_status(value):
    """Return ``(has_status, failed)`` with outer status taking precedence."""
    value = _maybe_json(value)
    if isinstance(value, str):
        outer = [int(code) for code in _OUTER_STATUS_RE.findall(value)]
        if outer:
            return True, outer[0] != 0
        labeled = [int(code) for code in _LABELED_STATUS_RE.findall(value)]
        return (True, any(code != 0 for code in labeled)) if labeled else (False, False)
    if isinstance(value, list):
        states = [_explicit_status(item) for item in value]
        present = [failed for has_status, failed in states if has_status]
        return (True, any(present)) if present else (False, False)
    if isinstance(value, dict):
        code = value.get("exit_code")
        if isinstance(code, (int, str)):
            try:
                return True, int(code) != 0
            except ValueError:
                pass
        boolean_states = []
        success = value.get("success")
        if isinstance(success, bool):
            boolean_states.append(not success)
        for key in ("is_error", "isError"):
            is_error = value.get(key)
            if isinstance(is_error, bool):
                boolean_states.append(is_error)
        if boolean_states:
            return True, any(boolean_states)
        states = [_explicit_status(item) for item in value.values()]
        present = [failed for has_status, failed in states if has_status]
        return (True, any(present)) if present else (False, False)
    return False, False


def _codex_error_body(raw):
    """Return diagnostic text only when a Codex output is explicitly error-shaped."""
    text = _flatten_text(raw).strip()
    has_status, failed = _explicit_status(raw)
    if has_status:
        return text if failed else ""
    if _TEXT_ERROR_RE.search(text):
        return text
    return ""


def _render_codex_response(payload, err_cap, tool_input_cap):
    """Render one Codex Desktop ``response_item`` payload."""
    payload_type = payload.get("type")
    if payload_type == "message":
        return _render_codex_message(payload)
    if payload_type == "agent_message":
        return _render_text_blocks(payload.get("content"), "ASST")
    if payload_type in {"function_call", "custom_tool_call", "tool_search_call"}:
        name = payload.get("name") or "tool_search"
        raw_input = payload.get("arguments") if payload_type != "custom_tool_call" else payload.get("input")
        summary = _summarize_tool_input(raw_input, tool_input_cap)
        return [f"  TOOL {name}({summary})"]
    if payload_type in {
        "function_call_output",
        "custom_tool_call_output",
        "tool_search_output",
    }:
        body = _codex_error_body(payload.get("output"))
        if body:
            return [f"  ERROR: {body[:err_cap]}"]
    return []


def _render_codex_event(payload, err_cap):
    """Render user-visible Codex dialogue events without bookkeeping events."""
    event_type = payload.get("type")
    if event_type == "mcp_tool_call_end":
        invocation = payload.get("invocation") or {}
        name = ".".join(
            filter(None, (invocation.get("server"), invocation.get("tool")))
        ) or "mcp"
        result_envelope = payload.get("result") or {}
        if "Err" in result_envelope and result_envelope.get("Err") is not None:
            error = result_envelope["Err"]
            body = _flatten_text(error).strip() or str(error)
            return [f"  ERROR: {name}: {body[:err_cap]}"]
        result = result_envelope.get("Ok")
        if isinstance(result, dict) and result.get("isError") is True:
            structured = result.get("structuredContent")
            body = (
                structured.get("error")
                if isinstance(structured, dict)
                else ""
            ) or _flatten_text(result.get("content")).strip()
            return [f"  ERROR: {name}: {str(body)[:err_cap]}"]
        return []
    message = (payload.get("message") or "").strip()
    if not message:
        return []
    if event_type == "user_message":
        return [f"USER: {message}"]
    if event_type == "agent_message":
        return [f"ASST: {message}"]
    return []


def _render_record(r, err_cap, tool_input_cap):
    """Return a list of condensed signal lines for one JSONL record (empty if pure noise)."""
    if r.get("isCompactSummary") or r.get("type") == "compacted":
        return ["\n===== [COMPACTION BOUNDARY] =====\n"]
    t = r.get("type")
    if t == "event_msg":
        payload = r.get("payload")
        if isinstance(payload, dict):
            if payload.get("type") == "context_compacted":
                return ["\n===== [COMPACTION BOUNDARY] =====\n"]
            return _render_codex_event(payload, err_cap)
        return []
    if t == "response_item":
        payload = r.get("payload")
        if isinstance(payload, dict):
            return _render_codex_response(payload, err_cap, tool_input_cap)
        return []
    if t not in _KEEP_TYPES:
        return []  # drop file-history-snapshot, attachment, pr-link, mode, ai-title, etc.
    msg = r.get("message") or {}
    c = msg.get("content")
    lines = []
    if isinstance(c, str):
        if t == "user" and c.strip():
            lines.append(f"USER: {c.strip()}")
        return lines
    if not isinstance(c, list):
        return lines
    for b in c:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text":
            txt = (b.get("text") or "").strip()
            if txt:
                lines.append(f"{'USER' if t == 'user' else 'ASST'}: {txt}")
        elif bt == "tool_use":
            nm = b.get("name", "tool")
            inp = b.get("input", {})
            summ = _summarize_tool_input(inp, tool_input_cap)
            lines.append(f"  TOOL {nm}({summ})")
        elif bt == "tool_result" and b.get("is_error"):
            body = b.get("content", "")
            if isinstance(body, list):
                body = " ".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in body)
            lines.append(f"  ERROR: {str(body)[:err_cap]}")
        # drop: thinking, image, SUCCESS tool_result
    return lines


def condense(path, err_cap, tool_input_cap):
    """Stream the transcript once; return (lines, counts).

    Each line carries an is_boundary flag so the splitter can prefer
    compaction boundaries before falling back to record boundaries.
    """
    rendered_records = []  # list of (text, response_message_role_or_none)
    event_dialogue_roles = set()
    # Upstream #81843: four writer domains append to one session .jsonl with no
    # shared lock, so a record can be spliced mid-write (still present on 2.1.220;
    # observed 2026-01..07 across 16 versions). Skipping those lines is correct,
    # but skipping them SILENTLY would let a corrupt transcript masquerade as a
    # complete mine — the exact completeness claim transcript-over-summary.md
    # makes. Count them and surface the count instead.
    malformed = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                malformed += 1
                continue
            payload = r.get("payload")
            response_fallback_role = (
                payload.get("role")
                if (
                    r.get("type") == "response_item"
                    and isinstance(payload, dict)
                    and payload.get("type") == "message"
                )
                else None
            )
            if (
                r.get("type") == "response_item"
                and response_fallback_role not in {"user", "assistant"}
            ):
                response_fallback_role = None
            if r.get("type") == "event_msg" and isinstance(payload, dict):
                event_type = payload.get("type")
                if event_type in {"user_message", "agent_message"} and (
                    payload.get("message") or ""
                ).strip():
                    event_dialogue_roles.add(
                        "user" if event_type == "user_message" else "assistant"
                    )
            for rendered in _render_record(r, err_cap, tool_input_cap):
                rendered_records.append((rendered, response_fallback_role))

    # Current rollouts mirror visible dialogue in event_msg records and may put
    # injected context in response-item messages. Use response messages only as
    # a per-role fallback for older/mixed rollouts that lack the corresponding
    # event dialogue role.
    selected = [
        _redact_secrets(rendered)
        for rendered, response_fallback_role in rendered_records
        if response_fallback_role not in event_dialogue_roles
    ]
    lines = []
    counts = {
        "user": 0,
        "asst": 0,
        "tool": 0,
        "error": 0,
        "compaction": 0,
        "malformed_lines": malformed,
    }
    for rendered in selected:
        boundary = rendered.startswith("\n=====")
        # Current Codex rollouts emit a top-level ``compacted`` record
        # immediately followed by an event_msg/context_compacted mirror.
        # Coalesce adjacent rendered boundaries so one compaction is not
        # counted twice; legacy event-only transcripts remain supported.
        if boundary and lines and lines[-1][1]:
            continue
        lines.append((rendered, boundary))
        if boundary:
            counts["compaction"] += 1
        elif rendered.startswith("USER:"):
            counts["user"] += 1
        elif rendered.startswith("ASST:"):
            counts["asst"] += 1
        elif rendered.startswith("  TOOL "):
            counts["tool"] += 1
        elif rendered.startswith("  ERROR:"):
            counts["error"] += 1
    return lines, counts


def split_to_parts(lines, max_tokens):
    """Split signal records into ordered parts that never exceed max_tokens.

    Prefer the latest compaction boundary in the current part. If one
    boundary-delimited segment is itself oversized, fall back to a record
    boundary. A single diagnostic record larger than the entire budget fails
    explicitly rather than producing a part the next model cannot read.
    """
    budget_bytes = int(max_tokens * BYTES_PER_TOKEN)
    if budget_bytes <= 0:
        raise ValueError("max_tokens must be positive")
    parts = []
    cur = []
    cur_bytes = 0
    for text, is_boundary in lines:
        text_bytes = len(text.encode("utf-8")) + 1
        if text_bytes > budget_bytes:
            raise ValueError(
                "single diagnostic record exceeds the per-part token budget; "
                "increase --max-tokens or reduce the source record"
            )
        if cur and cur_bytes + text_bytes > budget_bytes:
            boundary_index = next(
                (i for i in range(len(cur) - 1, 0, -1) if cur[i][1]),
                None,
            )
            if boundary_index is not None:
                parts.append([item[0] for item in cur[:boundary_index]])
                cur = cur[boundary_index:]
                cur_bytes = sum(
                    len(item[0].encode("utf-8")) + 1
                    for item in cur
                )
            if cur and cur_bytes + text_bytes > budget_bytes:
                parts.append([item[0] for item in cur])
                cur = []
                cur_bytes = 0
        cur.append((text, is_boundary))
        cur_bytes += text_bytes
    if cur:
        parts.append([item[0] for item in cur])
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                    help="per-part token budget (est @2.5 UTF-8 bytes/token); slice splits at compaction "
                         "boundaries to fit. 180K leaves headroom for the active model's "
                         "prompt, rules, and distill output.")
    ap.add_argument("--err-cap", type=int, default=1500)
    ap.add_argument("--tool-input-cap", type=int, default=160)
    args = ap.parse_args()

    if not os.path.isfile(args.transcript):
        raise SystemExit(f"not a file: {args.transcript}")
    os.makedirs(args.out_dir, exist_ok=True)

    lines, counts = condense(args.transcript, args.err_cap, args.tool_input_cap)
    if not lines:
        raise SystemExit(
            "no diagnostic signal recognized in nonempty transcript; "
            "the transcript envelope may be unsupported"
        )
    try:
        parts = split_to_parts(lines, args.max_tokens)
    except ValueError as error:
        raise SystemExit(str(error)) from None

    part_info = []
    # The documented workflow reuses a session-scoped output directory. Remove
    # only condenser-owned prior artifacts so an older, longer run cannot leave
    # stale tail slices for downstream consumers.
    for name in os.listdir(args.out_dir):
        if _SLICE_NAME_RE.fullmatch(name) or name == "condense-manifest.json":
            os.unlink(os.path.join(args.out_dir, name))
    for i, p in enumerate(parts):
        text = "\n".join(p)
        fn = os.path.join(args.out_dir, f"slice_{i:03d}.txt")
        with open(fn, "w", encoding="utf-8") as fh:
            fh.write(text)
        nb = len(text.encode("utf-8"))
        part_info.append({"part": i, "bytes": nb, "est_tokens": int(nb / BYTES_PER_TOKEN), "path": fn})

    total_bytes = sum(p["bytes"] for p in part_info)
    manifest = {
        "transcript": args.transcript,
        "signal_counts": counts,
        "n_parts": len(parts),
        "total_slice_bytes": total_bytes,
        "total_est_tokens": int(total_bytes / BYTES_PER_TOKEN),
        "parts": part_info,
    }
    with open(os.path.join(args.out_dir, "condense-manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    print(f"condensed {args.transcript}")
    print(f"  signal: user={counts['user']} asst={counts['asst']} tool={counts['tool']} "
          f"error={counts['error']} compaction={counts['compaction']}")
    if counts["malformed_lines"]:
        print(f"  WARNING: {counts['malformed_lines']} malformed JSONL line(s) skipped "
              f"(upstream #81843 writer race) — this slice is NOT a complete mine")
    print(f"  slice: {total_bytes:,} bytes (~{int(total_bytes/BYTES_PER_TOKEN):,} est tokens) "
          f"-> {len(parts)} part(s) each <= {args.max_tokens:,} tokens")
    for p in part_info:
        print(f"    slice_{p['part']:03d}.txt  {p['bytes']:,}b  ~{p['est_tokens']:,} tok")
    print(f"  manifest: {os.path.join(args.out_dir, 'condense-manifest.json')}")


if __name__ == "__main__":
    main()
