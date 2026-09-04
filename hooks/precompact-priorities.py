#!/usr/bin/env python3
"""PreCompact hook: append a fidelity checklist to the compaction summarizer's prompt.

WHAT IT DOES
    Prints a static, ASCII, sub-3 KB checklist to stdout and exits 0. Nothing is
    read, nothing is written, nothing can block.

WHY STDOUT WORKS HERE (verified against the installed binary, 2026-09-03)
    The hooks reference documents PreCompact as: exit 2 / `decision: block`
    blocks compaction; input carries `trigger` and `custom_instructions`;
    `systemMessage` and `continue` are discarded. It does not say what happens
    to plain stdout. `strings -n 8 ~/.local/share/claude/versions/2.1.260` does:

    executePreCompactHooks (minified `VX`, from the export map
    `VX as executePreCompactHooks`) collects the successful, non-blocking,
    non-empty outputs and returns them as new custom instructions:

        let C=E.filter((U)=>U.succeeded&&!U.blocked&&U.output.trim().length>0)
             .map((U)=>U.output.trim())
        ...
        return{newCustomInstructions:C.length>0?C.join(`\\n`):void 0, ...}

    Every compaction path hands that field to the summarizer. Manual /compact:

        f=I6t(f,Ce.newCustomInstructions)   // I6t: `${user text}\\n${hook text}`
        ...Oe=i$e(f)

    Auto and precomputed compaction:

        summarize:()=>Gdn(d,f,{customInstructions:Ne.newCustomInstructions,...})
        fMe(r,de,{customInstructions:Ne.newCustomInstructions,allowFallback:!1})

    and the prompt builder (`i$e`, same shape in `kYn`) appends it after the
    default nine-section template, before the REMINDER tail:

        if(e&&e.trim()!=="")n+=`\\nAdditional Instructions:\\n${e}`

    So fcakyon's intelligent-compact claim is correct and the docs are merely
    silent. Two details the same fragments settle:

      * `parseHookOutput` (`vKe`): "Hook output does not start with {, treating
        as plain text". The checklist therefore starts with a tag, never `{`.
      * Subagent compaction ignores the text: `VX` returns only `blockedBy`
        when `Xi(r.agentContext)` is set. This is a main-thread aid.

    Matcher: `tcr` maps PreCompact to `e.trigger`, so the documented values are
    `manual` and `auto`; the registration omits the matcher, which `ocr`
    (`if(!n||n==="*")return!0`) treats as match-all.

WHY THESE FIVE
    The default template asks for errors, files and user messages but never says
    to distinguish unanswered questions, to separate confirmed root causes from
    ruled-out hypotheses, to keep digits and ids exact, to treat subagent
    reports as evidence, or to record which alternative was chosen and why.
    Those are the facts a resumed session pays most to rediscover. Substance
    adapted from fcakyon/claude-codex-settings (intelligent-compact, Apache-2.0),
    rewritten for this harness. Measured A/B: skills/_shared/compaction-eval/.

CONTRACT
    exit 0 always; plain text on stdout only for hook_event_name PreCompact (or
    when the payload is unreadable, since this script is wired only there);
    silent on any other event so a mis-wiring cannot spam the model's context.
"""
import json
import sys

PRIORITIES = """\
<compaction-priorities>
Fidelity requirements for this summary. They refine the sections above; they do not replace them.

1. Unanswered questions. When listing user messages, mark each question the user asked as answered, partially answered, or unanswered. Start the pending-tasks section with a "Pending questions" list that quotes every unanswered or partially answered user question verbatim.
2. Root causes vs ruled-out hypotheses. Record each confirmed root cause with its file path and line (path/to/file.py:42). Keep every hypothesis that was tested and ruled out, marked as ruled out, so it is not retried. Quote error messages, error codes and stack frames verbatim; do not paraphrase them.
3. Exact identifiers and numbers. Keep ticket ids, PR and issue numbers, commit shas, run ids, ports, hostnames, paths, version strings, timings, counts, costs and token numbers exactly as they appeared. Do not round or paraphrase a quantitative value.
4. Subagent reports are primary evidence. For every Agent or Task tool result, carry the agent's final report forward with its paths, references and numbers intact. Re-running an agent is expensive; its findings are not filler.
5. A-vs-B decisions. Where the user weighed alternatives (tool X vs Y, approach 1 vs 2), record both options, which one was chosen, and the stated reason. If the choice is still open, list it under pending questions.

When cutting for length, drop conversational filler, repeated tool output and intermediate reasoning before anything covered by 1-5.
</compaction-priorities>"""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    event = payload.get("hook_event_name")
    if event not in (None, "PreCompact"):
        return 0
    sys.stdout.write(PRIORITIES + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # never block a compaction
        sys.exit(0)
