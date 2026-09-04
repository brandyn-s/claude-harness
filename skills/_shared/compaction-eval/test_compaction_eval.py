"""Deterministic, key-free tests for the compaction A/B harness.

Covers the fixture's planted-fact counts and self-consistency, the grader's
match rules, the faithful compaction-prompt assembly, and run_live.py's
--plan-only and cost-cap paths (no network, no anthropic import needed).
Run: python3 -m pytest skills/_shared/compaction-eval -q
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
HOOK = REPO / "hooks" / "precompact-priorities.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fixture_mod = _load("ce_fixture", HERE / "fixture.py")
grade = _load("ce_grade", HERE / "grade.py")
compact_prompt = _load("ce_prompt", HERE / "compact_prompt.py")
hook = _load("ce_hook", HOOK)

FX = fixture_mod.build_fixture()
TEXT = fixture_mod.transcript_text(FX)
BY_ID = {q["id"]: q for q in FX["questions"]}


# ---------------------------------------------------------------- fixture ----

def test_fixture_is_deterministic():
    assert fixture_mod.fixture_sha(fixture_mod.build_fixture()) == fixture_mod.fixture_sha(FX)
    assert json.dumps(fixture_mod.build_fixture(), sort_keys=True) == json.dumps(FX, sort_keys=True)


def test_fixture_is_deterministic_across_processes():
    """Caught 2026-09-04: `hash(name) % 4` in a worker tag made the fixture differ
    per process (str hashing is salted), so a results.json could not be tied to
    a rebuildable fixture. Two different hash seeds must yield one sha."""
    shas = []
    for seed in ("1", "2"):
        proc = subprocess.run(
            [sys.executable, "-c",
             "import importlib.util,sys; s=importlib.util.spec_from_file_location('f', sys.argv[1]); "
             "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.fixture_sha(m.build_fixture()))",
             str(HERE / "fixture.py")],
            capture_output=True, text=True, timeout=60, env={**os.environ, "PYTHONHASHSEED": seed})
        assert proc.returncode == 0, proc.stderr
        shas.append(proc.stdout.strip())
    assert shas[0] == shas[1] == fixture_mod.fixture_sha(FX), shas


def test_transcript_is_about_sixty_alternating_turns_starting_with_the_user():
    roles = [t["role"] for t in FX["transcript"]]
    assert 55 <= len(roles) <= 70, len(roles)
    assert roles[0] == "user"
    assert all(roles[i] != roles[i - 1] for i in range(1, len(roles))), "roles must alternate"
    assert all(t["content"].strip() for t in FX["transcript"])


def test_transcript_is_realistically_long():
    assert len(TEXT) >= 45_000, f"{len(TEXT)} chars is too thin to exercise compaction"


def test_planted_fact_counts_match_the_brief():
    cats = {}
    for q in FX["questions"]:
        cats[q["category"]] = cats.get(q["category"], 0) + 1
    assert cats == {"identifiers": 6, "errors": 4, "questions": 3, "root_causes": 3,
                    "hypotheses": 2, "decisions": 3, "subagent": 1}
    assert len(FX["questions"]) == 22
    planted = FX["planted"]
    assert len(planted["identifiers"]) == 6 and len(planted["errors"]) == 4
    assert len(planted["questions"]["unanswered"]) == 2 and len(planted["questions"]["answered"]) == 1
    assert len(planted["root_causes"]) == 3 and len(planted["ruled_out"]) == 2
    assert len(planted["decisions"]) == 3


def test_every_literal_answer_appears_in_the_transcript():
    for q in FX["questions"]:
        if q["match"] in ("contains", "sha", "number", "verbatim", "fileline"):
            assert any(a in TEXT for a in q["answers"]), (q["id"], q["answers"])
    for question in FX["planted"]["questions"]["answered"] + FX["planted"]["questions"]["unanswered"]:
        assert question in TEXT
    for hyp in FX["planted"]["ruled_out"]:
        assert hyp in TEXT and "ruled out" in TEXT.lower()


def test_subagent_number_appears_only_in_the_subagent_report():
    n = FX["planted"]["subagent_only_number"]
    hits = [t for t in FX["transcript"] if re.search(r"(?<!\d)" + n + r"(?!\d)", t["content"])]
    assert len(hits) == 1, [h["content"][:80] for h in hits]
    assert "Explore agent report" in hits[0]["content"]
    assert hits[0]["role"] == "user", "a tool result arrives as a user turn"


def test_distractors_are_present_so_digits_must_be_the_right_ones():
    assert fixture_mod.TICKET_DISTRACTOR in TEXT
    assert "5432" in TEXT and fixture_mod.PORT_TEST_PG != "5432"


def test_fixture_cli_writes_json(tmp_path):
    out = tmp_path / "fx.json"
    proc = subprocess.run([sys.executable, str(HERE / "fixture.py"), "--write", str(out)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["questions"]) == 22


# ----------------------------------------------------------------- grader ----

def _perfect_answers() -> dict[str, str]:
    ans = {}
    for q in FX["questions"]:
        if q["match"] == "decision":
            ans[q["id"]] = f"{q['answers'][0]} because {q['reason_any'][0]}"
        else:
            ans[q["id"]] = q["answers"][0]
    return ans


def test_perfect_answers_score_full_recall_in_every_category():
    scored = grade.score_run(FX, _perfect_answers())
    assert scored["recall"] == 1.0
    for cat in grade.CATEGORIES:
        assert scored[f"recall_{cat}"] == 1.0, cat


def test_unknown_and_empty_answers_score_zero():
    scored = grade.score_run(FX, {q["id"]: "UNKNOWN" for q in FX["questions"]})
    assert scored["recall"] == 0.0
    assert grade.score_run(FX, {})["recall"] == 0.0
    assert not grade.grade_answer(BY_ID["id1"], "Unknown - the summary does not say.")


def test_partial_recall_is_the_fraction_correct():
    ans = _perfect_answers()
    for qid in ("id1", "id2", "err1", "rc1"):
        ans[qid] = "UNKNOWN"
    scored = grade.score_run(FX, ans)
    assert scored["recall"] == pytest.approx(18 / 22)
    assert scored["recall_identifiers"] == pytest.approx(4 / 6)
    assert scored["recall_errors"] == pytest.approx(3 / 4)
    assert scored["recall_root_causes"] == pytest.approx(2 / 3)


def test_sha_accepts_seven_char_prefix_and_rejects_other_shas():
    q = BY_ID["id3"]
    assert grade.grade_answer(q, f"the regression landed in {fixture_mod.SHA_REGRESSION[:7]}")
    assert grade.grade_answer(q, f"commit {fixture_mod.SHA_REGRESSION}")
    assert not grade.grade_answer(q, f"commit {fixture_mod.SHA_FIX}")
    assert not grade.grade_answer(q, "commit a3f9c2")  # too short to be a sha


def test_number_match_is_standalone_and_comma_tolerant():
    q = BY_ID["id6"]
    assert grade.grade_answer(q, "metrics on port 18080.")
    assert grade.grade_answer(q, "18,080")
    assert not grade.grade_answer(q, "port 180800")
    assert not grade.grade_answer(q, "port 8000")
    assert grade.grade_answer(BY_ID["sub1"], "It scanned 214 test modules")
    assert not grade.grade_answer(BY_ID["sub1"], "2140 modules") and not grade.grade_answer(BY_ID["sub1"], "1214")


def test_verbatim_requires_the_whole_line_but_tolerates_quotes_and_case():
    q = BY_ID["err1"]
    assert grade.grade_answer(q, f"`{fixture_mod.ERR_POOL}`")
    assert grade.grade_answer(q, fixture_mod.ERR_POOL.upper())
    assert not grade.grade_answer(q, "E0412 connection pool exhausted")      # paraphrased / truncated
    assert not grade.grade_answer(q, "the pool was exhausted with 13 waiting")
    q2 = BY_ID["err2"]
    assert grade.grade_answer(q2, fixture_mod.ERR_TXN.replace("'", "’"))


def test_label_match_is_exact_and_not_a_substring_hit():
    q = BY_ID["uq2"]                       # expected UNANSWERED
    assert grade.grade_answer(q, "UNANSWERED")
    assert grade.grade_answer(q, "unanswered - the assistant said it would come back to it")
    assert not grade.grade_answer(q, "ANSWERED")
    assert not grade.grade_answer(q, "ANSWERED or UNANSWERED, unclear")
    assert not grade.grade_answer(q, "UNKNOWN")
    q1 = BY_ID["uq1"]                      # expected ANSWERED
    assert grade.grade_answer(q1, "Answered.")
    assert not grade.grade_answer(q1, "Unanswered")
    h = BY_ID["hyp1"]
    assert grade.grade_answer(h, "RULED_OUT") and grade.grade_answer(h, "ruled out")
    assert not grade.grade_answer(h, "CONFIRMED")


def test_fileline_match_accepts_basename_and_line_forms():
    q = BY_ID["rc1"]
    assert grade.grade_answer(q, "ledger/db/pool.py:47")
    assert grade.grade_answer(q, "pool.py:47")
    assert grade.grade_answer(q, "pool.py line 47")
    assert not grade.grade_answer(q, "pool.py:470")
    assert not grade.grade_answer(q, "pool.py:52")
    assert not grade.grade_answer(q, "transfer.py:118")


def test_decision_needs_choice_plus_reason_and_rejects_the_wrong_choice():
    q = BY_ID["dec1"]
    assert grade.grade_answer(q, "psycopg3, because SQLAlchemy 2.0 async support is first-class")
    assert not grade.grade_answer(q, "psycopg3")                                # no reason
    assert not grade.grade_answer(q, "chose asyncpg because SQLAlchemy supports it")
    q3 = BY_ID["dec3"]
    assert grade.grade_answer(q3, "kept --frozen and regenerated uv.lock so builds stay reproducible")
    assert not grade.grade_answer(q3, "dropped --frozen so the build re-resolves; reproducibility")


def test_parse_answers_handles_fenced_bare_and_line_forms():
    ids = ["id1", "id2"]
    assert grade.parse_answers('```json\n{"id1": "A", "id2": "B"}\n```', ids) == {"id1": "A", "id2": "B"}
    assert grade.parse_answers('{"id1": "A"}', ids) == {"id1": "A", "id2": ""}
    assert grade.parse_answers('id1: A\nid2: "B"\n', ids) == {"id1": "A", "id2": "B"}
    assert grade.parse_answers("garbage", ids) == {"id1": "", "id2": ""}


def test_aggregate_and_ci_verdict_shapes():
    runs_w = [grade.score_run(FX, _perfect_answers()) for _ in range(3)]
    partial = _perfect_answers()
    for qid in ("id1", "id2", "err1", "err2", "sub1", "uq2"):
        partial[qid] = "UNKNOWN"
    runs_b = [grade.score_run(FX, partial) for _ in range(3)]
    agg_w, agg_b = grade.aggregate_runs(runs_w), grade.aggregate_runs(runs_b)
    assert agg_w["recall"]["values"] == [1.0, 1.0, 1.0]
    verdict = grade.decide_verdict(agg_w, agg_b)
    assert verdict["verdict"] == "keep" and verdict.get("ci_aware") is True
    assert verdict["delta_mean"] == pytest.approx(6 / 22, abs=1e-3)
    same = grade.decide_verdict(grade.aggregate_runs(runs_b), grade.aggregate_runs(runs_b))
    assert same["verdict"] == "BLOCKED ON MEASUREMENT"


def test_grader_and_fixture_import_no_network_modules():
    banned = {"anthropic", "urllib", "http", "socket", "requests", "httpx", "httpx2", "ssl", "subprocess"}
    for name in ("grade.py", "fixture.py", "compact_prompt.py"):
        tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert not imported & banned, (name, imported & banned)


# ------------------------------------------------------- compaction prompt ----

def test_baseline_prompt_is_the_default_template_and_with_arm_appends_the_hook_text():
    base = compact_prompt.build_compact_prompt(None)
    withp = compact_prompt.build_compact_prompt(hook.PRIORITIES)
    assert base.startswith("CRITICAL: Respond with TEXT ONLY.")
    assert "9. Optional Next Step" in base and base.endswith("you will fail the task.")
    assert "Additional Instructions:" not in base
    assert withp.count("\nAdditional Instructions:\n") == 1
    head, tail = withp.split("\nAdditional Instructions:\n")
    assert head == base[: len(head)]
    assert tail == hook.PRIORITIES + compact_prompt.REMINDER
    assert compact_prompt.build_compact_prompt("   ") == base


def test_extract_summary_keeps_only_what_survives_compaction():
    raw = "<analysis>private reasoning 214</analysis>\n<summary>\n1. A\n\n\n2. B\n</summary>\ntrailing"
    out = compact_prompt.extract_summary(raw)
    assert "private reasoning" not in out
    assert out.startswith("Summary:\n1. A\n2. B")
    assert compact_prompt.extract_summary("no tags at all") == "no tags at all"


# ---------------------------------------------------------------- run_live ----

def _plan(tmp_path: Path, *extra: str, env_overlay: dict | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"   # unroutable: any network attempt fails fast
    env.update(env_overlay or {})
    return subprocess.run(
        [sys.executable, str(HERE / "run_live.py"), "--plan-only", "--model", "claude-fable-5-1",
         "--output", str(tmp_path / "out.json"), *extra],
        capture_output=True, text=True, timeout=120, cwd=str(HERE), env=env)


def test_plan_only_needs_no_key_no_sdk_and_writes_nothing(tmp_path):
    proc = _plan(tmp_path, "--runs", "3", "--max-tokens", "4000")
    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout)
    assert receipt["requested_model"] == "claude-fable-5-1"
    assert receipt["max_tokens"] == 4000 and receipt["runs"] == 3
    assert receipt["arms"] == ["baseline", "with_priorities"]
    assert receipt["credential_bytes"] == 0
    assert receipt["cost_cap_usd"] == 15.0 and receipt["within_budget"] is True
    assert 0 < receipt["estimate_heuristic"]["estimated_cost_usd"] < 15
    assert receipt["hook_text_bytes"] == len(hook.PRIORITIES.encode("utf-8"))
    assert not (tmp_path / "out.json").exists()
    assert "sk-" not in proc.stdout and "sk-" not in proc.stderr


def test_default_budget_is_sixteen_thousand_and_still_under_the_cap(tmp_path):
    """The 2026-09-03 smoke at 4000 truncated both arms on claude-fable-5-1; the
    default must be the budget results.json was produced with."""
    proc = _plan(tmp_path)
    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout)
    assert receipt["max_tokens"] == 16000
    assert receipt["within_budget"] is True


class _FakeBlock:
    def __init__(self, text):
        self.type, self.text = "text", text


class _FakeUsage:
    def __init__(self, i, o):
        self.input_tokens, self.output_tokens = i, o


class _FakeMsg:
    def __init__(self, text, stop_reason="end_turn", model="claude-fable-5-1"):
        self.content = [_FakeBlock(text)]
        self.stop_reason, self.model, self.usage = stop_reason, model, _FakeUsage(100, 50)


class _FakeClient:
    """Returns the queued messages in order; records every request."""
    def __init__(self, replies):
        self._replies, self.requests = list(replies), []
        outer = self

        class _Messages:
            def create(self, **kwargs):
                outer.requests.append(kwargs)
                return outer._replies.pop(0)
        self.messages = _Messages()


def _runner_with_fakes(monkeypatch, replies):
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))
    run_live = _load("ce_run_live", HERE / "run_live.py")
    run_live.MODEL, run_live.MAX_TOKENS = "claude-fable-5-1", 16000
    return run_live, _FakeClient(replies)


def test_truncated_summary_is_an_invalid_trial_not_a_low_score(monkeypatch):
    run_live, client = _runner_with_fakes(monkeypatch, [_FakeMsg("<analysis>cut", stop_reason="max_tokens")])
    with pytest.raises(run_live.TrialError, match="truncated at max_tokens"):
        run_live.run_trial(client, "baseline", FX, 0)
    assert len(client.requests) == 1, "the reader must not be paid for a cut summary"


def test_refusal_and_model_mismatch_fail_the_trial(monkeypatch):
    run_live, client = _runner_with_fakes(monkeypatch, [_FakeMsg("<summary>x</summary>", stop_reason="refusal")])
    with pytest.raises(run_live.TrialError, match="refusal"):
        run_live.run_trial(client, "baseline", FX, 0)
    run_live, client = _runner_with_fakes(monkeypatch, [_FakeMsg("<summary>x</summary>", model="claude-opus-5")])
    with pytest.raises(run_live.TrialError, match="model mismatch"):
        run_live.run_trial(client, "baseline", FX, 0)


def test_complete_trial_reads_only_the_summary_body_and_grades_it(monkeypatch):
    summary = ("<analysis>ZEBRA-PRIVATE-9 214 modules</analysis>\n<summary>\n1. Ticket PLAT-4821.\n"
               "7. Pending questions: none\n</summary>")
    reader_json = json.dumps({q["id"]: ("PLAT-4821" if q["id"] == "id1" else "UNKNOWN") for q in FX["questions"]})
    run_live, client = _runner_with_fakes(monkeypatch, [_FakeMsg(summary), _FakeMsg(reader_json)])
    rec = run_live.run_trial(client, "with_priorities", FX, 2)
    assert rec["summary_tag_found"] is True
    assert "ZEBRA-PRIVATE-9" not in client.requests[1]["messages"][0]["content"], "analysis must be stripped before the reader"
    assert client.requests[0]["messages"][-1]["content"] == run_live.ARMS["with_priorities"]
    assert client.requests[0]["messages"][:-1] == FX["transcript"]
    assert client.requests[0]["max_tokens"] == 16000 and client.requests[0]["output_config"] == {"effort": "medium"}
    assert client.requests[1]["output_config"] == {"effort": "low"} and client.requests[1]["system"]
    assert rec["scores"]["recall"] == pytest.approx(1 / 22)
    assert rec["scores"]["recall_identifiers"] == pytest.approx(1 / 6)
    assert rec["run_idx"] == 2 and rec["arm"] == "with_priorities"
    assert all(p["effective_model"] == "claude-fable-5-1" for p in rec["_response_provenance"])


def test_plan_only_reports_when_the_estimate_exceeds_the_cap(tmp_path):
    proc = _plan(tmp_path, "--max-cost-usd", "0.01")
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["within_budget"] is False


def test_live_path_aborts_before_any_request_when_over_the_cap(tmp_path, monkeypatch):
    """Injects a hollow `anthropic` module: if the runner reached the client it
    would raise AttributeError, not the cost abort."""
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-not-a-key")
    run_live = _load("ce_run_live", HERE / "run_live.py")
    out = tmp_path / "out.json"
    rc = run_live.main(["--model", "claude-fable-5-1", "--output", str(out), "--max-cost-usd", "0.01"])
    assert rc == 2
    assert not out.exists()


def test_live_path_refuses_without_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    run_live = _load("ce_run_live", HERE / "run_live.py")
    rc = run_live.main(["--model", "claude-fable-5-1", "--output", str(tmp_path / "o.json")])
    assert rc == 2
    assert "credentials" in capsys.readouterr().err


def test_estimate_scales_with_runs_and_is_priced_from_the_table():
    run_live = _load("ce_run_live", HERE / "run_live.py")
    one = run_live.estimate_cost("claude-fable-5-1", 20_000, {"a": 2000, "b": 2500}, 1000, 4000, 1)
    three = run_live.estimate_cost("claude-fable-5-1", 20_000, {"a": 2000, "b": 2500}, 1000, 4000, 3)
    assert three["estimated_cost_usd"] == pytest.approx(3 * one["estimated_cost_usd"], abs=0.02)
    assert one["price_per_mtok"] == {"input": 10.0, "output": 50.0}
    unknown = run_live.estimate_cost("claude-future-9", 20_000, {"a": 2000}, 1000, 4000, 1)
    assert "top tier assumed" in unknown["model_priced_as"]


def test_with_priorities_arm_uses_the_exact_hook_text():
    run_live = _load("ce_run_live", HERE / "run_live.py")
    assert run_live.PRIORITIES == hook.PRIORITIES
    assert run_live.ARMS["with_priorities"] == compact_prompt.build_compact_prompt(hook.PRIORITIES)
    assert run_live.ARMS["baseline"] == compact_prompt.build_compact_prompt(None)


# ------------------------------------------------------ committed results ----

RESULTS = HERE / "results.json"


@pytest.mark.skipif(not RESULTS.exists(), reason="no committed results.json yet")
def test_committed_results_are_reproducible_from_their_own_records():
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert data["fixture_sha"] == fixture_mod.fixture_sha(FX), "fixture changed since the run; re-run"
    assert data["hook_text_sha"] == run_live_sha(hook.PRIORITIES), "hook text changed since the run; re-run"
    for rec in data["records"]:
        rescored = grade.score_run(FX, rec["answers"])
        assert rescored["recall"] == pytest.approx(rec["scores"]["recall"]), (rec["arm"], rec["run_idx"])
    assert data["verdict"]["verdict"] in ("keep", "trim", "BLOCKED ON MEASUREMENT")
    assert data["cost"]["actual_usd"] <= data["receipt"]["cost_cap_usd"]


def run_live_sha(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
