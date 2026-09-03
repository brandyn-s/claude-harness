"""Tests for subagent-stop.py (SubagentStop)."""
import json
from datetime import datetime, timezone, timedelta

from conftest import run_hook

HOOK = "subagent-stop.py"


def _d_record(session_id, verdict, finding_id="fid1", skill="foo", ts=None):
    """Build one Layer-D oracle trace record (JSONL line)."""
    ts = ts or datetime.now(timezone.utc).isoformat(timespec="seconds")
    return json.dumps({
        "ts": ts, "layer": "D", "finding_id": finding_id, "skill": skill,
        "verdict": verdict, "evidence": "test", "procedure_version": "t",
        "model_version": None, "latency_ms": 1, "cost_usd": None,
        "input": {"session_id": session_id}, "schema_version": "1.0",
        "breadth": None,
    })


def _topics_env(tmp_path, topic="crowdstrike.md", seed="# seed\n"):
    """Point the hook's TOPICS_DIR at a tmp dir (CLAUDE_TOPICS_DIR) with one
    topic file present, so capture tests exercise the write path WITHOUT
    polluting the real ~/.claude/agent-memory/topics files. (run_hook does
    not override HOME, so the default TOPICS_DIR is the real one.)"""
    topics = tmp_path / "topics"
    topics.mkdir(parents=True, exist_ok=True)
    tp = topics / topic
    tp.write_text(seed, encoding="utf-8")
    return {"CLAUDE_TOPICS_DIR": str(topics)}, tp


def test_no_learnings_passes():
    rc, out, err = run_hook(HOOK, {
        "agent_type": "search",
        "session_id": "abc12345",
        "transcript": "No markers here",
    })
    assert rc == 0
    assert out.strip() == ""  # a pass emits nothing; {"result": "pass"} never reached the model
    assert "SubagentStop" in err


def test_with_learning_marker():
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "xyz98765",
        "transcript": "[observed] generic synthetic learning for test",
    })
    assert rc == 0
    assert out.strip() == ""  # a pass emits nothing; {"result": "pass"} never reached the model


def test_empty_input():
    rc, out, err = run_hook(HOOK, {})
    assert rc == 0
    assert out.strip() == ""  # a pass emits nothing; {"result": "pass"} never reached the model
    assert "unknown-agent" in err or "SubagentStop" in err


def test_transcript_path_is_read(tmp_path):
    """Claude Code's canonical SubagentStop field is `transcript_path` (a
    file path), not inline `transcript` content. Hook must read the file."""
    tr = tmp_path / "transcript.txt"
    tr.write_text("[observed] generic synthetic learning via transcript_path", encoding="utf-8")
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "pathkey1",
        "transcript_path": str(tr),
    })
    assert rc == 0
    assert out.strip() == ""  # a pass emits nothing; {"result": "pass"} never reached the model


def test_transcript_path_missing_file_does_not_crash(tmp_path):
    rc, out, _ = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "missing",
        "transcript_path": str(tmp_path / "does-not-exist.txt"),
    })
    assert rc == 0
    assert out.strip() == ""  # a pass emits nothing; {"result": "pass"} never reached the model


def test_jsonl_hook_attachment_with_observed_marker_does_not_capture(tmp_path):
    """REGRESSION (2026-05-28 msgraph.md pollution): a JSONL transcript line
    that embeds "[observed]" inside an attachment payload (e.g., the
    auto-topic-loader hook injects topic-file content as additionalContext,
    and topic files literally contain that token) must NOT be captured as
    a learning. Only user/assistant text-block content counts.

    Before the fix the hook split the raw JSONL by newline, regex-matched
    the substring inside the JSON value, and appended the entire ~26 KB
    event payload to msgraph.md as a "Worker learning."
    """
    tr = tmp_path / "transcript.jsonl"
    payload = (
        '{"parentUuid":"abc","isSidechain":false,'
        '"attachment":{"type":"hook_additional_context","hookName":"PreToolUse",'
        '"content":["topic file content including [observed] marker text and the word graph"]},'
        '"type":"attachment"}'
    )
    tr.write_text(payload + "\n", encoding="utf-8")
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "regress01",
        "transcript_path": str(tr),
    })
    assert rc == 0
    assert out.strip() == ""  # a pass emits nothing; {"result": "pass"} never reached the model
    # Negative assertion on stderr: no "Captured learning -> ..." emitted
    assert "Captured learning" not in err


def test_jsonl_assistant_text_with_observed_marker_is_captured(tmp_path):
    """JSONL assistant message with [observed] in a text content block IS a
    legitimate learning — the marker appears in agent prose, not inside
    another tool's payload string."""
    env, tp = _topics_env(tmp_path, "msgraph.md")
    tr = tmp_path / "transcript.jsonl"
    payload = (
        '{"type":"assistant","message":{"role":"assistant","content":['
        '{"type":"text","text":"[observed] graph token expiry behavior differs in GCC High"}'
        ']}}'
    )
    tr.write_text(payload + "\n", encoding="utf-8")
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "positive1",
        "transcript_path": str(tr),
    }, env=env)
    assert rc == 0
    assert out.strip() == ""  # a pass emits nothing; {"result": "pass"} never reached the model
    assert "Captured learning" in err
    assert tp.read_text(encoding="utf-8").count("### [auto-captured]") == 1


def test_layer_d_gate_blocks_on_fix_ineffective(tmp_path):
    """Enforced Layer-D gate: a FIX-INEFFECTIVE verdict attributed to this
    session blocks the subagent from finishing (exit 2)."""
    trace = tmp_path / "oracle-trace.jsonl"
    trace.write_text(_d_record("gate-sess", "FIX-INEFFECTIVE") + "\n", encoding="utf-8")
    rc, out, err = run_hook(
        HOOK,
        {"agent_type": "fix", "session_id": "gate-sess", "transcript": ""},
        env={"AUDIT_SKILL_ORACLE_TRACE": str(trace)},
    )
    assert rc == 2, f"expected block (exit 2), got {rc}; err={err}"
    assert "BLOCK" in err and "Layer-D gate" in err


def test_layer_d_gate_blocks_on_introduced_regression(tmp_path):
    trace = tmp_path / "oracle-trace.jsonl"
    trace.write_text(_d_record("gate-sess", "INTRODUCED") + "\n", encoding="utf-8")
    rc, _out, err = run_hook(
        HOOK,
        {"agent_type": "fix", "session_id": "gate-sess", "transcript": ""},
        env={"AUDIT_SKILL_ORACLE_TRACE": str(trace)},
    )
    assert rc == 2, f"expected block on INTRODUCED, got {rc}; err={err}"


def test_layer_d_gate_fail_safe_on_session_mismatch(tmp_path):
    """Fail-safe: a FIX-INEFFECTIVE for a DIFFERENT session must NOT block."""
    trace = tmp_path / "oracle-trace.jsonl"
    trace.write_text(_d_record("other-sess", "FIX-INEFFECTIVE") + "\n", encoding="utf-8")
    rc, out, _err = run_hook(
        HOOK,
        {"agent_type": "fix", "session_id": "gate-sess", "transcript": ""},
        env={"AUDIT_SKILL_ORACLE_TRACE": str(trace)},
    )
    assert rc == 0
    assert out.strip() == ""


def test_layer_d_gate_latest_verdict_wins(tmp_path):
    """A FIX-INEFFECTIVE superseded by a later VERIFIED for the same finding
    (fix succeeded on retry) must NOT block."""
    trace = tmp_path / "oracle-trace.jsonl"
    old = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(timespec="seconds")
    new = datetime.now(timezone.utc).isoformat(timespec="seconds")
    trace.write_text(
        _d_record("gate-sess", "FIX-INEFFECTIVE", finding_id="fidX", ts=old) + "\n"
        + _d_record("gate-sess", "VERIFIED", finding_id="fidX", ts=new) + "\n",
        encoding="utf-8",
    )
    rc, out, _err = run_hook(
        HOOK,
        {"agent_type": "fix", "session_id": "gate-sess", "transcript": ""},
        env={"AUDIT_SKILL_ORACLE_TRACE": str(trace)},
    )
    assert rc == 0, "latest VERIFIED should supersede the earlier FIX-INEFFECTIVE"
    assert out.strip() == ""


def test_layer_d_gate_window_excludes_stale_records(tmp_path):
    """A FIX-INEFFECTIVE older than the gate window must NOT block (avoids
    re-blocking on ancient records across a long session)."""
    trace = tmp_path / "oracle-trace.jsonl"
    ancient = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
    trace.write_text(_d_record("gate-sess", "FIX-INEFFECTIVE", ts=ancient) + "\n", encoding="utf-8")
    rc, out, _err = run_hook(
        HOOK,
        {"agent_type": "fix", "session_id": "gate-sess", "transcript": ""},
        env={"AUDIT_SKILL_ORACLE_TRACE": str(trace), "AUDIT_SKILL_ORACLE_GATE_WINDOW": "1800"},
    )
    assert rc == 0
    assert out.strip() == ""


def test_jsonl_huge_prose_does_not_crash_or_bypass_cap(tmp_path):
    """Even when a learning marker fires on legitimate prose, the hook must
    not crash on a multi-KB block. Length cap is asserted indirectly: the
    hook returns pass instead of stalling or erroring."""
    huge = "[observed] " + ("x " * 3000)  # ~6000 chars
    tr = tmp_path / "transcript.jsonl"
    payload = json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "text", "text": huge}
        ]},
    })
    tr.write_text(payload + "\n", encoding="utf-8")
    rc, out, _ = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "bounded1",
        "transcript_path": str(tr),
    })
    assert rc == 0
    assert out.strip() == ""  # a pass emits nothing; {"result": "pass"} never reached the model


def test_genuine_learning_is_captured_to_topic(tmp_path):
    """A real domain learning IS captured once to the routed topic file —
    proves the fix doesn't break the feature's intended behavior."""
    env, tp = _topics_env(tmp_path, "crowdstrike.md")
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "real0001",
        "transcript": "[observed] crowdstrike FQL date filters need quoted timestamps",
    }, env=env)
    assert rc == 0
    assert out.strip() == ""
    assert "Captured learning" in err
    body = tp.read_text(encoding="utf-8")
    assert body.count("### [auto-captured]") == 1
    assert "quoted timestamps" in body


def test_captured_title_is_derived_not_hardcoded(tmp_path):
    """REGRESSION (2026-07-03 review-learnings: 7 entries titled identically
    "Worker learning" across 6 topic files, indistinguishable without opening
    each). The header must reflect the snippet's own content, not a constant."""
    env, tp = _topics_env(tmp_path, "crowdstrike.md")
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "titl0001",
        "transcript": "[observed] crowdstrike FQL date filters need quoted timestamps",
    }, env=env)
    assert rc == 0
    body = tp.read_text(encoding="utf-8")
    assert "### [auto-captured] crowdstrike FQL date filters need quoted timestamps (" in body
    assert "### [auto-captured] Worker learning (" not in body


def test_captured_title_falls_back_when_first_line_too_short(tmp_path):
    """A snippet whose first line is too short/empty after stripping tags and
    markup falls back to the generic label rather than an empty/junk title."""
    env, tp = _topics_env(tmp_path, "crowdstrike.md")
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "titl0002",
        "transcript": "[observed]\ncrowdstrike containment note continues on this line",
    }, env=env)
    assert rc == 0
    assert "### [auto-captured] Worker learning (" in tp.read_text(encoding="utf-8")


def test_distill_table_meta_output_is_not_captured(tmp_path):
    """REGRESSION (2026-06-07 airlock.md 60+ rows): a distill lessons-table
    row with the promote-notation '[observed] -> [confirmed]' and a tier cell
    is skill meta-output, not a learning. Must NOT be captured."""
    env, tp = _topics_env(tmp_path, "crowdstrike.md")
    row = "| 3 | crowdstrike alerts v3 pagination | T4: Agent | CONFIRM [observed] -> [confirmed] |"
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "meta0001",
        "transcript": row,
    }, env=env)
    assert rc == 0
    assert out.strip() == ""
    assert "Captured learning" not in err
    assert "### [auto-captured]" not in tp.read_text(encoding="utf-8")


def test_example_header_meta_output_is_not_captured(tmp_path):
    """A SKILL.md '**Example N:**' block within the 3-line capture window is
    skill documentation, not a learning."""
    env, tp = _topics_env(tmp_path, "crowdstrike.md")
    # Marker on line 0 so the 3-line snippet includes the Example header.
    transcript = "[observed] crowdstrike note\nfiller\n**Example 2: Novel rule + system fact**"
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "exmp0001",
        "transcript": transcript,
    }, env=env)
    assert rc == 0
    assert "Captured learning" not in err
    assert "### [auto-captured]" not in tp.read_text(encoding="utf-8")


def test_pipe_delimited_tier_cell_not_captured(tmp_path):
    """REGRESSION (2026-06-12 slack.md): distill lessons tables use pipe-
    delimited tier cells like `| T5 |`, which the colon-only `| T4:` pattern
    missed. Skill meta-output, not a learning."""
    env, tp = _topics_env(tmp_path, "slack.md")
    row = "| 3 | slack conversations_history needs channels:read | T5 | confirmed | SKIP |"
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker", "session_id": "pipe0001", "transcript": row,
    }, env=env)
    assert rc == 0
    assert "Captured learning" not in err
    assert "### [auto-captured]" not in tp.read_text(encoding="utf-8")


def test_distill_routing_arrow_not_captured(tmp_path):
    """REGRESSION (2026-06-12 slack.md): distill routing prose like
    `→ **T5 skip**` / `→ **SKILL-ROUTED**` is bridge-table meta-output."""
    env, tp = _topics_env(tmp_path, "slack.md")
    snippet = "- slack drift: retired tool named → **SKILL-ROUTED fix**; channels:read → **T5 skip**"
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker", "session_id": "arrw0001", "transcript": snippet,
    }, env=env)
    assert rc == 0
    assert "Captured learning" not in err
    assert "### [auto-captured]" not in tp.read_text(encoding="utf-8")


def test_marker_inside_table_cell_not_captured(tmp_path):
    """REGRESSION (2026-06-12 architecture.md): a review-learnings checklist
    table row with `[confirmed]` INSIDE a cell is analysis output, not prose."""
    env, tp = _topics_env(tmp_path, "architecture.md")
    row = "| Pattern check | Any skill with 3+ [confirmed] memory tags to promote? |"
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker", "session_id": "cell0001", "transcript": row,
    }, env=env)
    assert rc == 0
    assert "Captured learning" not in err
    assert "### [auto-captured]" not in tp.read_text(encoding="utf-8")


def test_retro_narration_not_captured(tmp_path):
    """REGRESSION (2026-06-12 slack.md): /retro narration like `**Postmortem**`
    and `Skipped (T5):` is skill output, not a domain learning."""
    env, tp = _topics_env(tmp_path, "slack.md")
    snippet = "**Postmortem** — not triggered. Skipped (T5): slack channels:read already [confirmed]."
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker", "session_id": "retr0001", "transcript": snippet,
    }, env=env)
    assert rc == 0
    assert "Captured learning" not in err
    assert "### [auto-captured]" not in tp.read_text(encoding="utf-8")


def test_real_learning_with_bare_tier_word_is_still_captured(tmp_path):
    """GUARD-NOT-TOO-BROAD: a genuine learning that merely mentions a tier
    token (`T5`) in prose — no table cell, no routing arrow — must STILL be
    captured. The broadened SKILL_META_OUTPUT must reject distill SHAPES, not
    any text containing 'T5'."""
    env, tp = _topics_env(tmp_path, "slack.md")
    learning = "[observed] slack admin scopes require T5 escalation for an org-grid install"
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker", "session_id": "real0001", "transcript": learning,
    }, env=env)
    assert rc == 0
    assert tp.read_text(encoding="utf-8").count("### [auto-captured]") == 1


def test_duplicate_learning_is_not_reappended(tmp_path):
    """REGRESSION (2026-06-07 60+ duplicate blocks): a learning already present
    in the topic file must NOT be appended again. Every SubagentStop re-reads
    the full (growing) transcript, so dedup prevents the N-duplicate
    amplification that produced the airlock.md/infrastructure.md pollution."""
    learning = "[observed] crowdstrike containment is reversible but pages the SOC"
    env, tp = _topics_env(
        tmp_path, "crowdstrike.md",
        seed="# seed\n\n### [auto-captured] Worker learning (2026-01-01)\n"
             + learning + "\n- Source: prior agent (session old)\n",
    )
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "dup00001",
        "transcript": learning,
    }, env=env)
    assert rc == 0
    assert out.strip() == ""
    assert "Captured learning" not in err
    assert tp.read_text(encoding="utf-8").count("### [auto-captured]") == 1


def test_jsonl_user_dispatch_prompt_is_not_captured(tmp_path):
    """REGRESSION (2026-06-12 msgraph.md pollution): in a subagent transcript
    the first USER message is the dispatch prompt (skill body + ARGUMENTS),
    which routinely quotes [observed]/[confirmed] vocabulary. A /ship agent's
    ARGUMENTS string was captured verbatim as a "Worker learning." Learnings
    come from ASSISTANT prose only — user messages must never be scanned."""
    env, tp = _topics_env(tmp_path, "msgraph.md")
    tr = tmp_path / "transcript.jsonl"
    payload = (
        '{"type":"user","message":{"role":"user","content":['
        '{"type":"text","text":"ARGUMENTS: Ship the distill artifacts: '
        'agent-memory/topics/github.md ([observed] to [confirmed] flip), '
        'rules/platform-constraints.md"}'
        ']}}'
    )
    tr.write_text(payload + "\n", encoding="utf-8")
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "dispatch1",
        "transcript_path": str(tr),
    }, env=env)
    assert rc == 0
    assert out.strip() == ""
    assert "Captured learning" not in err
    assert "### [auto-captured]" not in tp.read_text(encoding="utf-8")


def test_unicode_arrow_promote_notation_is_not_captured(tmp_path):
    """REGRESSION (2026-06-12): distill promote notation with the UNICODE
    arrow — "[observed]→[confirmed]" — bypassed the ASCII-only "->" form in
    SKILL_META_OUTPUT and was captured as a learning."""
    env, tp = _topics_env(tmp_path, "msgraph.md")
    tr = tmp_path / "transcript.jsonl"
    payload = (
        '{"type":"assistant","message":{"role":"assistant","content":['
        '{"type":"text","text":"Promoted the graph entry: [observed]\\u2192[confirmed], confirmation date added"}'
        ']}}'
    )
    tr.write_text(payload + "\n", encoding="utf-8")
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "uniarrow",
        "transcript_path": str(tr),
    }, env=env)
    assert rc == 0
    assert out.strip() == ""
    assert "Captured learning" not in err
    assert "### [auto-captured]" not in tp.read_text(encoding="utf-8")


def test_code_graph_learning_routes_to_code_graph_dev_not_msgraph(tmp_path):
    """REGRESSION (2026-06-12 msgraph.md pollution): bare-substring keyword
    matching routed every "code-graph" learning to msgraph.md because
    "graph" is a substring of "code-graph". Boundary-aware matching plus the
    explicit "code-graph" key must route it to code-graph-dev.md."""
    topics = tmp_path / "topics"
    topics.mkdir(parents=True, exist_ok=True)
    cg = topics / "code-graph-dev.md"
    msg = topics / "msgraph.md"
    cg.write_text("# seed\n", encoding="utf-8")
    msg.write_text("# seed\n", encoding="utf-8")
    tr = tmp_path / "transcript.jsonl"
    payload = (
        '{"type":"assistant","message":{"role":"assistant","content":['
        '{"type":"text","text":"[confirmed] code-graph crash-marker retry poisoning: delete_project leaves the marker behind"}'
        ']}}'
    )
    tr.write_text(payload + "\n", encoding="utf-8")
    rc, out, err = run_hook(HOOK, {
        "agent_type": "worker",
        "session_id": "cgroute1",
        "transcript_path": str(tr),
    }, env={"CLAUDE_TOPICS_DIR": str(topics)})
    assert rc == 0
    assert out.strip() == ""
    assert "Captured learning" in err
    assert cg.read_text(encoding="utf-8").count("### [auto-captured]") == 1
    assert "### [auto-captured]" not in msg.read_text(encoding="utf-8")
