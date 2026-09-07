#!/usr/bin/env python3
"""bin/ledger-audit-report.py rolls up the PostCompact ledger audits."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parent
TOOL = BIN / "ledger-audit-report.py"
_spec = importlib.util.spec_from_file_location("ledger_audit_report", TOOL)
lar = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = lar
_spec.loader.exec_module(lar)


def _row(date, sid, entries, not_found, trigger="auto", cwd="/w"):
    return {"ts": 0, "date": date, "session_id": sid, "cwd": cwd, "trigger": trigger, "compaction_count": 1,
            "total_entries": entries, "not_found_count": len(not_found),
            "rejected_dropped_count": sum(1 for m in not_found if m["kind"] == "rejected"),
            "not_found": not_found, "summary_chars": 100}


def _write(audit_dir: Path):
    audit_dir.mkdir(parents=True, exist_ok=True)
    rej = {"kind": "rejected", "text": "Do not add a Stop hook phrase blocker"}
    day1 = [_row("2026-09-01", "s1", 5, [rej, {"kind": "constraint", "text": "no changes outside hooks"}]),
            _row("2026-09-01", "s2", 0, [])]
    day2 = [_row("2026-09-02", "s1", 5, [rej]), _row("2026-09-02", "s3", 2, [], trigger="manual")]
    (audit_dir / "ledger-audit-20260901.jsonl").write_text("\n".join(json.dumps(r) for r in day1) + "\n", encoding="utf-8")
    (audit_dir / "ledger-audit-20260902.jsonl").write_text("\n".join(json.dumps(r) for r in day2) + "\n{garbage\n", encoding="utf-8")


def test_summary_totals_and_recurrence(tmp_path):
    _write(tmp_path)
    s = lar.summarize(lar.load_rows(tmp_path))
    assert s["rows"] == 4
    assert s["totals"]["compactions"] == 4 and s["totals"]["with_ledger"] == 3
    assert s["totals"]["rejected_dropped"] == 2 and s["totals"]["compactions_dropping_a_rejection"] == 2
    assert s["rejected_drop_rate_pct"] == 50.0
    assert s["worst_sessions"][0]["session_id"] == "s1"
    assert s["recurring_dropped_rejections"] == [{"text": "do not add a stop hook phrase blocker", "times": 2}]
    assert s["per_day"]["2026-09-02"]["compactions"] == 2


def test_days_filter_uses_the_file_date(tmp_path):
    _write(tmp_path)
    assert lar.load_rows(tmp_path, days=0) == []          # both files are in the past
    assert len(lar.load_rows(tmp_path, days=100_000)) == 4


def test_cli_text_and_json(tmp_path):
    _write(tmp_path)
    text = subprocess.run([sys.executable, str(TOOL), "--dir", str(tmp_path), "--dropped"],
                          capture_output=True, text=True, timeout=60)
    assert text.returncode == 0
    assert "compactions audited        4" in text.stdout
    assert "Do not add a Stop hook phrase blocker" in text.stdout
    assert "not a verdict" in text.stdout
    js = subprocess.run([sys.executable, str(TOOL), "--dir", str(tmp_path), "--json"],
                        capture_output=True, text=True, timeout=60)
    assert json.loads(js.stdout)["totals"]["compactions"] == 4


def test_empty_dir_says_so(tmp_path):
    res = subprocess.run([sys.executable, str(TOOL), "--dir", str(tmp_path)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0 and "no rows" in res.stdout
