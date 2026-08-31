#!/usr/bin/env python3
"""Claude Code status line: context %, cost, duration, model, rate limits."""
import json, sys, os, subprocess
from pathlib import Path

data = json.load(sys.stdin)
model = data['model']['display_name']
directory = os.path.basename(data.get('workspace', {}).get('current_dir', '.'))
cost = data.get('cost', {}).get('total_cost_usd', 0) or 0
pct = int(data.get('context_window', {}).get('used_percentage', 0) or 0)
duration_ms = data.get('cost', {}).get('total_duration_ms', 0) or 0

GREEN, YELLOW, RED, CYAN, RESET = '\033[32m', '\033[33m', '\033[31m', '\033[36m', '\033[0m'

bar_color = RED if pct >= 70 else YELLOW if pct >= 50 else GREEN
filled = pct // 10
bar = '\u2588' * filled + '\u2591' * (10 - filled)

mins, secs = duration_ms // 60000, (duration_ms % 60000) // 1000

try:
    subprocess.check_output(['git', 'rev-parse', '--git-dir'], stderr=subprocess.DEVNULL)
    branch = subprocess.check_output(
        ['git', 'branch', '--show-current'],
        stderr=subprocess.DEVNULL,
    ).decode('utf-8', errors='replace').strip()
    branch_str = f" | {branch}" if branch else ""
except Exception:
    branch_str = ""

# Rate limit indicator (v2.1.80+)
rate_str = ""
rl = data.get('rate_limits', {})
if rl:
    five_hr = rl.get('five_hour', {}).get('used_percentage', 0) or 0
    if five_hr >= 80:
        rate_str = f" | {RED}RL:{five_hr}%{RESET}"
    elif five_hr >= 50:
        rate_str = f" | {YELLOW}RL:{five_hr}%{RESET}"


# Compaction detection (logs threshold for empirical measurement)
_compact_log = Path.home() / ".claude" / "compaction-log.jsonl"
_last_pct_file = Path.home() / ".claude" / ".last-context-pct"
try:
    last_pct = int(_last_pct_file.read_text(encoding="utf-8").strip()) if _last_pct_file.exists() else 0
    if last_pct > 30 and pct < last_pct - 20:
        import time as _time
        with open(_compact_log, "a", encoding="utf-8") as _lf:
            _lf.write(json.dumps({
                "ts": _time.time(),
                "pre_pct": last_pct,
                "post_pct": pct,
                "model": model,
            }) + "\n")
    _last_pct_file.write_text(str(pct), encoding="utf-8")
except Exception:
    pass

print(f"{CYAN}[{model}]{RESET} {directory}{branch_str}")
print(f"{bar_color}{bar}{RESET} {pct}% | {YELLOW}${cost:.2f}{RESET} | {mins}m {secs}s{rate_str}")
