# Staged hook: tool-receipt-log

STATUS: **STAGED — do NOT auto-install.** Validated prototype, not yet enabled (scope-discipline).

## What
PostToolUse hook (`tool-receipt-log.py`) that writes an HMAC-signed receipt of every real
tool result to `~/.claude/logs/tool-receipts-<session>.jsonl`. Paired verifier:
`bin/tool-receipt-verify.py`.

## Why
Defense against the live Opus-4.8 tool-result fabrication class (#68332). Measured 2026-06-14:
46.5% of agent turns run on the reasoning-amplified Opus-4.8 fallback (The Reasoning Trap,
arXiv:2510.22977 — reasoning causally amplifies tool hallucination, mitigation only training-side).
Inspired by NabaOS (arXiv:2603.10060: signed tool-execution receipts, 94.2% catch @ <15 ms).
The model can fabricate a result; it cannot forge an HMAC of a real execution.

## Validation (done 2026-06-14)
- `bin/tool-receipt-verify.py --selftest` PASSES: forged result (no receipt) flagged; real
  result cleared; HMAC key-bound (wrong key != real receipt → model cannot forge).
- Coverage (honest): catches injected/forged tool_RESULT BLOCKS (no receipt; cf. #64095).
  The pure in-extended-thinking #68332 (fake tool_use never enters the transcript as a real
  block) needs a content-claim matcher over the narrative — documented follow-on.

## To install (when ready)
settings.json PostToolUse, matcher `*`, command `tool-receipt-log.py` via the run-hook
launcher, timeout 5. Set `CLAUDE_TOOL_RECEIPT_KEY` (a secret the model never sees, in the
hook env, NOT context) for a real deployment; without it a forgeable session-derived dev
key is used (prototype only).

## Decision gate before enabling (scope-discipline)
Enable only if the in-session fabrication rate justifies per-tool-call overhead.

**RUN 2026-06-14 — STAYS STAGED.** Forged/injected tool-RESULT rate over 97 local transcripts
(12,991 tool calls, all project dirs via `bin/tool-receipt-scan.py`) = **0.0000%** (0 orphan
results). A per-tool-call HMAC defending a 0% phenomenon is overhead. (The first Item-3 run
scanned one project dir: 76 transcripts / 11,553 calls, same 0.0000%.)

**How to re-run the gate (the verifier alone cannot do it retrospectively):**
`tool-receipt-verify.py` needs a receipt LOG, which only exists once the hook is enabled — so
it cannot measure HISTORICAL transcripts. The receipt-equivalent for past transcripts is the
issued-`tool_use` set: had the hook been running, every issued call would have produced a
receipt, so `issued` == the receipt set. An orphan (a consumed `tool_result` whose
`tool_use_id` was never issued) is the #64095/#68332 injected-result signature.
`bin/tool-receipt-scan.py` computes this over `~/.claude/projects/*/*.jsonl`.
COVERAGE: transcript-visible injected-RESULT class only; the pure in-extended-thinking #68332
(fake `tool_use` never enters the transcript) needs the content-claim matcher (the follow-on).
