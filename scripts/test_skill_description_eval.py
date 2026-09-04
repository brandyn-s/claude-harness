"""Deterministic tests for bin/skill-description-eval.py (no network).

A fake client stands in for the Anthropic SDK so corpus building, routing and
the report math are exercised end to end; the report is also checked against a
hand-built results fixture with known recall, confusion and false-fire numbers.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "skill_description_eval", REPO / "bin" / "skill-description-eval.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sde = _load()


# --------------------------------------------------------------------------- fakes

def _response(text, *, model="fake", stop_reason="end_turn", usage=None):
    usage = usage or {}
    return SimpleNamespace(
        model=model,
        stop_reason=stop_reason,
        stop_details=None,
        content=[SimpleNamespace(type="thinking", thinking=""),
                 SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=usage.get("input_tokens", 10),
            output_tokens=usage.get("output_tokens", 5),
            cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
        ),
    )


class FakeMessages:
    """Records every create() call; answers come from a callable(kwargs) -> text."""

    def __init__(self, answer, system_tokens=2000):
        self.answer = answer
        self.system_tokens = system_tokens
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.answer(kwargs)
        if isinstance(result, tuple):
            text, extra = result
            return _response(text, model=kwargs["model"], **extra)
        return _response(result, model=kwargs["model"])

    def count_tokens(self, **kwargs):
        return SimpleNamespace(input_tokens=self.system_tokens)


class FakeClient:
    def __init__(self, answer, system_tokens=2000):
        self.messages = FakeMessages(answer, system_tokens)


def _user_text(call):
    content = call["messages"][0]["content"]
    if isinstance(content, str):
        return content
    return " ".join(block.get("text", "") for block in content)


# --------------------------------------------------------------------------- fixtures

def _write_skill(root, name, description, when_to_use=None, body="## Steps\n\n1. Do the thing.\n", **extra):
    lines = ["---", f"name: {name}", f"description: {json.dumps(description)}"]
    if when_to_use is not None:
        lines.append(f"when_to_use: {json.dumps(when_to_use)}")
    for key, value in extra.items():
        lines.append(f"{key}: {json.dumps(value)}")
    lines.append("---")
    (root / name).mkdir(parents=True)
    (root / name / "SKILL.md").write_text("\n".join(lines) + "\n\n# " + name + "\n\n" + body, encoding="utf-8")


@pytest.fixture
def skills_dir(tmp_path):
    root = tmp_path / "skills"
    _write_skill(root, "alpha", "Scan code for alpha-class bugs.",
                 "Use when the user asks for an alpha scan. Trigger phrases: \"alpha scan\".",
                 body="## When to use\n\nWhen alpha bugs are suspected.\n\n## Steps\n\n1. Run alpha.\n")
    _write_skill(root, "beta", "Summarise a beta report.", "Use when a beta report needs a summary.")
    _write_skill(root, "gamma", "Hidden maintenance procedure.", "Use when maintaining.",
                 **{"disable-model-invocation": True})
    _write_skill(root, "delta", "Explicitly visible.", "Use when delta.",
                 **{"disable-model-invocation": False})
    (root / "_shared").mkdir()
    (root / "_shared" / "SKILL.md").write_text("---\nname: shared\ndescription: not a skill\n---\n")
    return root


# --------------------------------------------------------------------------- skills

def test_load_skills_marks_visibility_and_composes_listing(skills_dir):
    skills = sde.load_skills(skills_dir)
    by_name = {s["name"]: s for s in skills}
    assert set(by_name) == {"alpha", "beta", "gamma", "delta"}
    assert by_name["gamma"]["model_visible"] is False
    assert by_name["delta"]["model_visible"] is True
    assert by_name["alpha"]["listing"] == (
        'Scan code for alpha-class bugs. Use when the user asks for an alpha scan. '
        'Trigger phrases: "alpha scan".'
    )
    assert [s["name"] for s in sde.visible_skills(skills)] == ["alpha", "beta", "delta"]


def test_listing_is_capped_like_the_runtime():
    assert len(sde.listing_text("x" * 1600, "y" * 100)) == sde.LISTING_CHARACTER_CAP
    assert sde.listing_text("A.", "") == "A."


def test_body_excludes_frontmatter(skills_dir):
    alpha = {s["name"]: s for s in sde.load_skills(skills_dir)}["alpha"]
    assert "alpha-class" not in alpha["body"]          # description text gone
    assert "Trigger phrases" not in alpha["body"]      # when_to_use text gone
    assert "description:" not in alpha["body"]
    assert "## Steps" in alpha["body"]                 # body kept


def test_routing_system_prompt_lists_every_visible_skill_once(skills_dir):
    skills = sde.visible_skills(sde.load_skills(skills_dir))
    prompt = sde.routing_system_prompt(skills)
    assert prompt.count("- alpha: Scan code for alpha-class bugs.") == 1
    assert "- beta: Summarise a beta report." in prompt
    assert "gamma" not in prompt
    assert prompt == sde.routing_system_prompt(skills), "must be deterministic (it is cached)"


# --------------------------------------------------------------------------- corpus

def test_generic_requests_are_thirty_unique_non_empty_strings():
    generic = sde.GENERIC_REQUESTS
    assert len(generic) == 30
    assert len(set(generic)) == 30
    assert all(isinstance(g, str) and len(g.strip()) > 10 for g in generic)


def test_build_corpus_uses_body_only_and_labels_items(skills_dir):
    skills = sde.load_skills(skills_dir)
    client = FakeClient(lambda kw: json.dumps({"requests": ["r1", "r2", "r3", "r4-extra"]}))
    corpus = sde.build_corpus(skills, client, model="claude-sonnet-5", positives=3)

    visible = [s for s in skills if s["model_visible"]]
    assert len(client.messages.calls) == len(visible)
    for skill in visible:
        # generation runs in a small thread pool, so match calls by body, not by order
        call = next(c for c in client.messages.calls if f"# {skill['name']}\n" in _user_text(c))
        assert call["model"] == "claude-sonnet-5"
        text = _user_text(call)
        assert skill["description"] not in text, "positives must be generated without the description"
        assert skill["when_to_use"] not in text
        assert "## Steps" in text
        fmt = call["output_config"]["format"]
        assert fmt["type"] == "json_schema"

    items = corpus["items"]
    positives = [i for i in items if i["kind"] == "positive"]
    negatives = [i for i in items if i["kind"] == "negative"]
    assert len(positives) == 3 * len(visible), "surplus requests are dropped, exactly 3 per skill"
    assert len(negatives) == 30
    assert all(i["expected"] == "none" for i in negatives)
    assert {i["expected"] for i in positives} == {"alpha", "beta", "delta"}
    assert len({i["id"] for i in items}) == len(items)
    assert corpus["meta"]["model"] == "claude-sonnet-5"
    assert corpus["meta"]["skills"] == 3
    assert corpus["meta"]["cost_usd"] > 0


def test_build_corpus_records_a_refusal_instead_of_crashing(skills_dir):
    skills = sde.load_skills(skills_dir)

    def answer(kw):
        if "Scan" not in _user_text(kw) and "alpha" in _user_text(kw):
            return ("", {"stop_reason": "refusal"})
        return json.dumps({"requests": ["a", "b", "c"]})

    corpus = sde.build_corpus(skills, client=FakeClient(answer), model="claude-sonnet-5", positives=3)
    assert "alpha" in corpus["meta"]["generation_errors"]
    assert sum(1 for i in corpus["items"] if i["expected"] == "alpha") == 0
    assert sum(1 for i in corpus["items"] if i["expected"] == "beta") == 3


# --------------------------------------------------------------------------- routing

def _corpus_for(skills):
    items = []
    for s in sde.visible_skills(skills):
        for n in range(1, 3):
            items.append({"id": f"{s['name']}-{n}", "request": f"please {s['name']} {n}",
                          "expected": s["name"], "kind": "positive"})
    items.append({"id": "generic-01", "request": "rename a variable", "expected": "none", "kind": "negative"})
    items.append({"id": "generic-02", "request": "explain a regex", "expected": "none", "kind": "negative"})
    return {"meta": {"model": "fake"}, "items": items}


def test_route_corpus_caches_the_routing_table_and_records_answers(skills_dir):
    skills = sde.load_skills(skills_dir)
    corpus = _corpus_for(skills)
    routes = {"please alpha 1": "alpha", "please alpha 2": "beta", "please beta 1": "beta",
              "please beta 2": "beta", "please delta 1": "none", "please delta 2": "delta",
              "rename a variable": "none", "explain a regex": "alpha"}

    def answer(kw):
        req = _user_text(kw)
        usage = {"input_tokens": 20, "output_tokens": 30,
                 "cache_read_input_tokens": 0 if len(client.messages.calls) == 1 else 2000,
                 "cache_creation_input_tokens": 2000 if len(client.messages.calls) == 1 else 0}
        return (json.dumps({"skill": routes[req]}), {"usage": usage})

    client = FakeClient(answer, system_tokens=2000)
    results = sde.route_corpus(corpus, skills, client, model="claude-fable-5-1", effort="low",
                               concurrency=2, max_cost_usd=10.0)

    first = client.messages.calls[0]
    assert first["model"] == "claude-fable-5-1"
    assert "thinking" not in first, "Fable 5.1: thinking is always on, the parameter must be omitted"
    assert first["output_config"]["effort"] == "low"
    enum = first["output_config"]["format"]["schema"]["properties"]["skill"]["enum"]
    assert enum == ["alpha", "beta", "delta", "none"]
    system = first["system"]
    assert isinstance(system, list) and len(system) == 1
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert "- alpha: Scan code for alpha-class bugs." in system[0]["text"]
    assert all(call["system"] == system for call in client.messages.calls), "identical prefix -> cache hits"

    assert [r["id"] for r in results["routes"]] == sorted(i["id"] for i in corpus["items"])
    by_id = {r["id"]: r for r in results["routes"]}
    assert by_id["alpha-2"]["answer"] == "beta"
    assert by_id["generic-02"]["answer"] == "alpha"
    assert by_id["delta-1"]["answer"] == "none"

    usage = results["meta"]["usage"]
    assert usage["requests"] == 8
    assert usage["input_tokens"] == 8 * 20
    assert usage["output_tokens"] == 8 * 30
    assert usage["cache_creation_input_tokens"] == 2000
    assert usage["cache_read_input_tokens"] == 7 * 2000
    rates = sde.PRICING["claude-fable-5-1"]
    expected_cost = (160 * rates["input"] + 240 * rates["output"]
                     + 2000 * rates["cache_write"] + 14000 * rates["cache_read"]) / 1e6
    assert results["meta"]["cost_usd"] == pytest.approx(expected_cost)
    assert results["meta"]["model"] == "claude-fable-5-1"
    assert results["meta"]["estimate"]["total_usd"] > 0
    assert results["meta"]["system_prompt_sha256"]


def test_route_corpus_aborts_before_spending_when_estimate_exceeds_budget(skills_dir):
    skills = sde.load_skills(skills_dir)
    client = FakeClient(lambda kw: json.dumps({"skill": "none"}), system_tokens=50_000_000)
    with pytest.raises(sde.BudgetExceeded):
        sde.route_corpus(_corpus_for(skills), skills, client, model="claude-fable-5-1", max_cost_usd=10.0)
    assert client.messages.calls == [], "no request may be sent once the estimate is over budget"


def test_route_limit_and_refusal_handling(skills_dir):
    skills = sde.load_skills(skills_dir)

    def answer(kw):
        if "alpha 1" in _user_text(kw):
            return ("", {"stop_reason": "refusal"})
        return json.dumps({"skill": "none"})

    client = FakeClient(answer)
    results = sde.route_corpus(_corpus_for(skills), skills, client, model="claude-fable-5-1", limit=3)
    assert len(results["routes"]) == 3
    assert {r["id"]: r["answer"] for r in results["routes"]}["alpha-1"] == "refusal"


def test_estimate_route_cost_math():
    est = sde.estimate_route_cost(system_tokens=10_000, n_items=100, model="claude-fable-5-1",
                                  request_tokens=50, output_tokens=200)
    rates = sde.PRICING["claude-fable-5-1"]
    assert est["cache_write_usd"] == pytest.approx(2 * 10_000 * rates["cache_write"] / 1e6)
    assert est["cache_read_usd"] == pytest.approx(100 * 10_000 * rates["cache_read"] / 1e6)
    assert est["input_usd"] == pytest.approx(100 * 50 * rates["input"] / 1e6)
    assert est["output_usd"] == pytest.approx(100 * 200 * rates["output"] / 1e6)
    assert est["total_usd"] == pytest.approx(
        est["cache_write_usd"] + est["cache_read_usd"] + est["input_usd"] + est["output_usd"])


# --------------------------------------------------------------------------- report

def _route(id_, expected, answer, kind=None):
    kind = kind or ("negative" if expected == "none" else "positive")
    return {"id": id_, "request": id_, "expected": expected, "kind": kind, "answer": answer,
            "stop_reason": "refusal" if answer == "refusal" else "end_turn"}


RESULTS_FIXTURE = {
    "meta": {"model": "claude-fable-5-1", "effort": "low", "cost_usd": 1.25, "skills": ["alpha", "beta", "gamma"],
             "usage": {"requests": 13}, "date": "2026-09-03"},
    "routes": [
        _route("alpha-1", "alpha", "alpha"), _route("alpha-2", "alpha", "alpha"), _route("alpha-3", "alpha", "beta"),
        _route("beta-1", "beta", "beta"), _route("beta-2", "beta", "beta"), _route("beta-3", "beta", "beta"),
        _route("gamma-1", "gamma", "none"), _route("gamma-2", "gamma", "none"), _route("gamma-3", "gamma", "alpha"),
        _route("generic-01", "none", "none"), _route("generic-02", "none", "none"),
        _route("generic-03", "none", "alpha"), _route("generic-04", "none", "refusal"),
    ],
}


def test_report_math_on_fixture():
    report = sde.compute_report(RESULTS_FIXTURE)
    per = report["per_skill"]
    assert per["alpha"]["positives"] == 3 and per["alpha"]["hits"] == 2
    assert per["alpha"]["recall"] == pytest.approx(2 / 3)
    assert per["beta"]["recall"] == 1.0
    assert per["gamma"]["recall"] == 0.0
    assert per["gamma"]["to_none"] == 2
    # alpha captured gamma-3 and generic-03; beta captured alpha-3
    assert per["alpha"]["captured"] == 2
    assert per["beta"]["captured"] == 1
    assert per["gamma"]["captured"] == 0
    assert report["confusion"] == [
        {"expected": "alpha", "got": "beta", "count": 1},
        {"expected": "gamma", "got": "alpha", "count": 1},
    ]
    ff = report["false_fire"]
    assert ff["negatives"] == 4 and ff["fired"] == 1 and ff["rate"] == pytest.approx(0.25)
    assert ff["fired_items"] == [{"id": "generic-03", "request": "generic-03", "got": "alpha"}]
    overall = report["overall"]
    assert overall["positives"] == 9 and overall["hits"] == 5
    assert overall["micro_recall"] == pytest.approx(5 / 9)
    assert overall["macro_recall"] == pytest.approx((2 / 3 + 1.0 + 0.0) / 3)
    assert overall["refusals"] == 1
    assert overall["skills_never_hit"] == ["gamma"]
    assert [(m["id"], m["got"]) for m in report["misses"]] == [
        ("alpha-3", "beta"), ("gamma-1", "none"), ("gamma-2", "none"), ("gamma-3", "alpha")]


def test_readme_renders_tables_and_cost():
    report = sde.compute_report(RESULTS_FIXTURE)
    text = sde.render_readme(report, RESULTS_FIXTURE["meta"], results_name="results-2026-09-03.json")
    assert "| gamma | 3 | 0 | 0.00 | 2 | 0 | 0 |" in text      # positives, hits, recall, to none, refused, captured
    assert "| alpha | beta | 1 |" in text
    assert "## Missed positives (4)" in text
    assert "| gamma-3 | gamma | alpha | gamma-3 |" in text
    assert "False-fire rate" in text and "1/4" in text
    assert "$1.25" in text
    assert "results-2026-09-03.json" in text


def test_report_cli_writes_results_and_readme(tmp_path):
    results_path = tmp_path / "results-2026-09-03.json"
    results_path.write_text(json.dumps(RESULTS_FIXTURE), encoding="utf-8")
    readme = tmp_path / "README.md"
    rc = sde.main(["report", "--results", str(results_path), "--readme", str(readme)])
    assert rc == 0
    written = json.loads(results_path.read_text(encoding="utf-8"))
    assert written["report"]["overall"]["hits"] == 5
    assert "| gamma | 3 | 0 | 0.00 |" in readme.read_text(encoding="utf-8")
