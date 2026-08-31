"""Write distill coordination marker for current session post-Phase-D."""
import json
import pathlib

marker = {
    "session_id": "code-search-tier-1-2-3-mechanisms-2026-05-03",
    "timestamp": "2026-05-03T18:00:00+00:00",
    "topic": "code-search Tier 1+2+3 mechanism execution: Phase A multi-target gold + Phase B/C 5 mechanism experiments + Phase D synthesis",
    "metrics": {
        "total_turns_post_compaction": 35,
        "tool_calls_attempted": 60,
        "tool_calls_failed": 3,
        "retries": 1,
        "abandoned_approaches": 0,
        "dead_end_turns": 3,
        "efficiency_pct": 91,
        "files_touched": 10,
        "prs_shipped": 4,
        "api_spend_actual": "$3 (vs $20 plan estimate)",
        "wall_time": "~3.5hr (vs 5-6hr plan estimate)",
    },
    "phase_results": {
        "A_multitarget_gold_relabel": {"delta_mrr": 0.491, "verdict": "win"},
        "B1_llm_router": {"delta_mrr": -0.030, "verdict": "null"},
        "B2_thompson_bandit_online": {"delta_mrr": -0.018, "verdict": "null"},
        "B2_static_vw_0_65": {"delta_mrr": 0.016, "verdict": "free win, ship as default"},
        "C1_clarinet": {"delta_mrr_gold": 0.112, "delta_mrr_random_ablation": -0.109, "verdict": "positive with leakage caveat; real-world ~+0.05"},
        "C2_nmir": {"delta_mrr": -0.043, "verdict": "null"},
        "C3_pmra_topic": {"delta_mrr": -0.006, "verdict": "null"},
    },
    "lesson_count": 1,
    "lessons": [
        {
            "title": "Multi-target gold relabel reveals MRR hidden by single-target eval (medium bucket +0.491)",
            "tier": "T4",
            "target": "agent-memory/topics/code-search-dev.md",
        },
    ],
    "verdict": "Productive session. The 7-experiment 'architectural ceiling' found in PR #88 was a single-target gold artifact, not retrieval failure. Multi-target gold relabel + static vw=0.65 deliver projected ~0.65 MRR on full real_session (vs original 0.353). 4/5 mechanism experiments null on this strong-baseline corpus; CLARINET shows clarification turns work in principle but require UX surface for production. Total spend ~$3 / 3.5hr, 7x and 1.5x under plan estimate.",
}
out = pathlib.Path.home() / ".claude" / "last-distill.json"
out.write_text(json.dumps(marker, indent=2), encoding="utf-8")
print(f"Wrote: {out}")
