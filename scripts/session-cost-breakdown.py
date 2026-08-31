#!/usr/bin/env python3
"""Session cost breakdown — parses the active transcript and attributes cost by activity.

Usage:
    python session-cost-breakdown.py                        # auto-reads from hud cache
    python session-cost-breakdown.py --cost 14.28           # pin to /cost snapshot
    python session-cost-breakdown.py <file.jsonl>           # specific transcript
"""
import json
import sys
import os
import glob
import argparse
from collections import defaultdict
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

HUD_COST_CACHE = os.path.expanduser('~/.claude/plugins/claude-hud/.cost-cache.json')


def read_hud_cost() -> float | None:
    try:
        with open(HUD_COST_CACHE, 'r', encoding='utf-8') as f:
            cost = json.load(f).get('totalCost')
        if isinstance(cost, (int, float)) and cost > 0:
            return float(cost)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None

# ── Pricing (per 1M tokens) — used for RELATIVE weighting ────────────────────
# Actual Claude Code billing differs from raw API rates (especially caching).
# These rates determine cost PROPORTIONS between activities, not absolute $.
PRICING = {
    'claude-fable-5': {
        'input': 10.00, 'output': 50.00,
        'cache_write': 12.50, 'cache_read': 1.00,
    },
    'claude-sonnet-5': {
        'input': 3.00, 'output': 15.00,
        'cache_write': 3.75, 'cache_read': 0.30,
    },
    # Opus 4.5+ all bill 5/25; the 15/75 previously on this row was Opus-4.1-era.
    'claude-opus-4-6': {
        'input': 5.00, 'output': 25.00,
        'cache_write': 6.25, 'cache_read': 0.50,
    },
    'claude-sonnet-4-5-20250929': {
        'input': 3.00, 'output': 15.00,
        'cache_write': 3.75, 'cache_read': 0.30,
    },
    'claude-haiku-4-5-20251001': {
        'input': 1.00, 'output': 5.00,
        'cache_write': 1.25, 'cache_read': 0.10,
    },
}
DEFAULT_PRICING = PRICING['claude-opus-4-6']


def get_pricing(model: str) -> dict:
    for key, rates in PRICING.items():
        if key in model:
            return rates
    lower = model.lower()
    if 'opus' in lower:
        return PRICING['claude-opus-4-6']
    if 'sonnet' in lower:
        return PRICING['claude-sonnet-4-5-20250929']
    if 'haiku' in lower:
        return PRICING['claude-haiku-4-5-20251001']
    return DEFAULT_PRICING


def compute_message_cost(usage: dict, rates: dict) -> dict:
    input_tok = usage.get('input_tokens', 0)
    output_tok = usage.get('output_tokens', 0)
    cache_write_tok = usage.get('cache_creation_input_tokens', 0)
    cache_read_tok = usage.get('cache_read_input_tokens', 0)

    cost_input = input_tok * rates['input'] / 1_000_000
    cost_output = output_tok * rates['output'] / 1_000_000
    cost_cache_write = cache_write_tok * rates['cache_write'] / 1_000_000
    cost_cache_read = cache_read_tok * rates['cache_read'] / 1_000_000
    cost_total = cost_input + cost_output + cost_cache_write + cost_cache_read

    return {
        'input_tokens': input_tok,
        'output_tokens': output_tok,
        'cache_write_tokens': cache_write_tok,
        'cache_read_tokens': cache_read_tok,
        'cost_input': cost_input,
        'cost_output': cost_output,
        'cost_cache_write': cost_cache_write,
        'cost_cache_read': cost_cache_read,
        'cost_total': cost_total,
    }


def find_session_transcripts(arg: str | None = None) -> list[str]:
    """Find all transcript files for a session (main + subagents).

    Returns a list of paths: [main_transcript, subagent1, subagent2, ...].
    """
    if arg and os.path.isfile(arg):
        main = arg
    else:
        # Search all project dirs, pick most recently modified main transcript
        base = os.path.expanduser('~/.claude/projects')
        main = None
        if os.path.isdir(base):
            all_jsonl = glob.glob(os.path.join(base, '*', '*.jsonl'))
            # Only main transcripts (not inside subagents/)
            all_jsonl = [f for f in all_jsonl if '/subagents/' not in f.replace('\\', '/')]
            if all_jsonl:
                main = max(all_jsonl, key=os.path.getmtime)

        if not main:
            # Fallback to session-transcripts
            pattern = os.path.expanduser('~/.claude/session-transcripts/*.jsonl')
            files = glob.glob(pattern)
            if files:
                main = max(files, key=os.path.getmtime)

        if not main:
            print("ERROR: No transcript files found.")
            sys.exit(1)

    paths = [main]

    # Find subagent transcripts: <session-id>/subagents/*.jsonl
    session_id = os.path.splitext(os.path.basename(main))[0]
    session_dir = os.path.join(os.path.dirname(main), session_id, 'subagents')
    if os.path.isdir(session_dir):
        subagent_files = glob.glob(os.path.join(session_dir, '*.jsonl'))
        paths.extend(sorted(subagent_files))

    return paths


def parse_transcripts(paths: list[str]) -> dict:
    by_activity = defaultdict(lambda: defaultdict(float))
    by_model = defaultdict(lambda: defaultdict(float))
    by_category = defaultdict(float)
    tool_call_counts = defaultdict(int)
    total_messages = 0
    subagent_messages = 0
    first_ts = None
    last_ts = None
    models_seen = set()

    for file_idx, filepath in enumerate(paths):
        is_subagent = file_idx > 0  # first file is main transcript

        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get('type') != 'assistant':
                    continue

                msg = entry.get('message', {})
                usage = msg.get('usage', {})
                model = msg.get('model', 'unknown')
                if not usage:
                    continue

                total_messages += 1
                if is_subagent:
                    subagent_messages += 1
                models_seen.add(model)

                ts_str = entry.get('timestamp')
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                        if first_ts is None or ts < first_ts:
                            first_ts = ts
                        if last_ts is None or ts > last_ts:
                            last_ts = ts
                    except (ValueError, TypeError):
                        pass

                rates = get_pricing(model)
                costs = compute_message_cost(usage, rates)

                for key in ('cost_total', 'input_tokens', 'output_tokens',
                            'cache_write_tokens', 'cache_read_tokens'):
                    by_model[model][key] += costs[key]

                by_category['input'] += costs['cost_input']
                by_category['output'] += costs['cost_output']
                by_category['cache_write'] += costs['cost_cache_write']
                by_category['cache_read'] += costs['cost_cache_read']

                content = msg.get('content', [])
                tools_in_msg = []
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_use':
                        tool_name = block.get('name', 'unknown')
                        tools_in_msg.append(tool_name)
                        tool_call_counts[tool_name] += 1

                # Attribute subagent messages to "Agent (model)" activity
                if is_subagent:
                    short_model = model.replace('claude-', '').split('-202')[0]
                    activity = f"Agent ({short_model})"
                    by_activity[activity]['cost'] += costs['cost_total']
                    by_activity[activity]['output_tokens'] += costs['output_tokens']
                    by_activity[activity]['messages'] += 1
                elif tools_in_msg:
                    share = costs['cost_total'] / len(tools_in_msg)
                    out_share = costs['output_tokens'] / len(tools_in_msg)
                    for tool in tools_in_msg:
                        by_activity[tool]['cost'] += share
                        by_activity[tool]['output_tokens'] += out_share
                        by_activity[tool]['messages'] += 1
                else:
                    by_activity['Thinking']['cost'] += costs['cost_total']
                    by_activity['Thinking']['output_tokens'] += costs['output_tokens']
                    by_activity['Thinking']['messages'] += 1

    return {
        'path': paths[0],
        'total_messages': total_messages,
        'subagent_messages': subagent_messages,
        'subagent_count': len(paths) - 1,
        'first_ts': first_ts,
        'last_ts': last_ts,
        'models': models_seen,
        'by_activity': dict(by_activity),
        'by_model': dict(by_model),
        'by_category': dict(by_category),
        'tool_call_counts': dict(tool_call_counts),
    }


def shorten_tool(name: str) -> str:
    if name.startswith('mcp__'):
        parts = name.split('__')
        if len(parts) >= 3:
            return f"{parts[1]}:{parts[2]}"
    return name


def fmt_cost(val: float) -> str:
    if abs(val) >= 1.0:
        return f"${val:.2f}"
    if abs(val) >= 0.01:
        return f"${val:.3f}"
    return f"${val:.4f}"


def fmt_tokens(val: float) -> str:
    if val >= 1_000_000:
        return f"{val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"{val / 1_000:.1f}K"
    return str(int(val))


def print_report(data: dict, actual_cost: float | None = None):
    raw_total = sum(v.get('cost_total', 0) for v in data['by_model'].values())
    scale = (actual_cost / raw_total) if (actual_cost and raw_total > 0) else 1.0
    total_cost = actual_cost if actual_cost else raw_total
    is_scaled = actual_cost is not None

    duration = None
    if data['first_ts'] and data['last_ts']:
        duration = data['last_ts'] - data['first_ts']

    # ── Header ──
    print("=" * 60)
    print("  SESSION COST BREAKDOWN")
    print("=" * 60)
    print(f"  Transcript : {os.path.basename(data['path'])}")
    if duration:
        mins = duration.total_seconds() / 60
        print(f"  Duration   : {int(mins)}m")
        if mins > 0:
            rate = total_cost / (mins / 60)
            print(f"  Burn rate  : {fmt_cost(rate)}/hr")
    msg_detail = f"{data['total_messages']} assistant turns"
    if data.get('subagent_count', 0) > 0:
        msg_detail += f" ({data['subagent_messages']} from {data['subagent_count']} subagent{'s' if data['subagent_count'] > 1 else ''})"
    print(f"  Messages   : {msg_detail}")
    print(f"  Models     : {', '.join(sorted(data['models']))}")
    if is_scaled:
        print(f"  Total cost : {fmt_cost(total_cost)}")
    else:
        print(f"  Total cost : {fmt_cost(total_cost)} (estimated)")
    print()

    # ── Cost by category ──
    print("── Cost by Token Type ──────────────────────────────────────")
    cats = data['by_category']
    cat_raw_total = sum(cats.values())
    for cat in ('cache_write', 'cache_read', 'output', 'input'):
        raw_val = cats.get(cat, 0)
        pct = (raw_val / cat_raw_total * 100) if cat_raw_total > 0 else 0
        display_val = raw_val * scale
        bar = '█' * int(pct / 2)
        label = cat.replace('_', ' ').title()
        print(f"  {label:<14} {fmt_cost(display_val):>10}  {pct:5.1f}%  {bar}")
    print()

    # ── Cost by model ──
    print("── Cost by Model ───────────────────────────────────────────")
    header = f"  {'Model':<28} {'Cost':>10} {'Input':>8} {'Output':>8} {'Cache W':>8} {'Cache R':>8}"
    print(header)
    print("  " + "─" * 76)
    for model in sorted(data['by_model'], key=lambda m: -data['by_model'][m].get('cost_total', 0)):
        m = data['by_model'][model]
        short = model.replace('claude-', '').replace('-20250929', '')
        print(f"  {short:<28} {fmt_cost(m.get('cost_total', 0) * scale):>10} "
              f"{fmt_tokens(m.get('input_tokens', 0)):>8} "
              f"{fmt_tokens(m.get('output_tokens', 0)):>8} "
              f"{fmt_tokens(m.get('cache_write_tokens', 0)):>8} "
              f"{fmt_tokens(m.get('cache_read_tokens', 0)):>8}")
    print()

    # ── Cost by activity ──
    print("── Cost by Activity ────────────────────────────────────────")
    activities = sorted(data['by_activity'].items(), key=lambda x: -x[1].get('cost', 0))
    header = f"  {'Activity':<32} {'Cost':>10} {'%':>6} {'Calls':>6} {'Out Tok':>8}"
    print(header)
    print("  " + "─" * 68)
    for name, metrics in activities:
        raw_cost = metrics.get('cost', 0)
        pct = (raw_cost / raw_total * 100) if raw_total > 0 else 0
        display_cost = raw_cost * scale
        calls = int(metrics.get('messages', 0))
        out_tok = metrics.get('output_tokens', 0)
        display = shorten_tool(name)
        print(f"  {display:<32} {fmt_cost(display_cost):>10} {pct:5.1f}% {calls:>6} {fmt_tokens(out_tok):>8}")
    print()

    # ── Tool call frequency ──
    if data['tool_call_counts']:
        print("── Tool Call Frequency ─────────────────────────────────────")
        for tool, count in sorted(data['tool_call_counts'].items(), key=lambda x: -x[1])[:15]:
            display = shorten_tool(tool)
            bar = '▪' * min(count, 40)
            print(f"  {display:<32} {count:>4}  {bar}")
        print()

    if not is_scaled:
        print("Costs estimated from API rates. Install claude-hud for accurate $.")


def main():
    parser = argparse.ArgumentParser(description='Session cost breakdown')
    parser.add_argument('transcript', nargs='?', help='Path to transcript JSONL')
    parser.add_argument('--cost', type=float, help='Pin to /cost snapshot (default: reads hud cache)')
    args = parser.parse_args()

    actual_cost = args.cost if args.cost else read_hud_cost()
    paths = find_session_transcripts(args.transcript)
    data = parse_transcripts(paths)
    print_report(data, actual_cost)


if __name__ == '__main__':
    main()
