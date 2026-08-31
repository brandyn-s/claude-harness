# launchd templates — scheduled maintenance on macOS

LaunchAgents for the recurring maintenance jobs (the macOS counterpart to
anything Task Scheduler would have run on Windows). Each job runs through
`/bin/zsh -lc`, so PATH and `~/.zshenv` resolve exactly as in a terminal,
and wraps long work in `caffeinate -i` so sleep doesn't stall it.

| Template | Schedule | What it runs |
|---|---|---|
| `com.example.claude.garden.plist` | nightly 03:30 | `claude -p "/garden"` — knowledge-base curation |
| `com.example.claude.gather-intel.plist` | Mon 08:30 | `claude -p "/gather-intel"` — community intel sweep |
| `com.example.claude.hook-fire-report.plist` | Mon 09:00 | `bin/hook-fire-report.py` — hook fire-rate/obsolescence report |
| `com.example.claude.session-receipt-enrichment.plist` | every 15 minutes + login | `bin/enrich-session-end-receipts.py` — local-only model/fallback/refusal metadata enrichment for pending SessionEnd receipts; no model or network calls |
| `com.example.claude.usage-review.plist` | Mon 07:30 | `mcp-servers/scripts/compliance_chat_weekly.py` — weekly Chat usage-review queue (semantic body-scan; outputs to `~/Documents/usage-review/<date>/`, OUTSIDE git; needs `ANTHROPIC_COMPLIANCE_ACCESS_KEY` + `ANTHROPIC_API_KEY` in env or Keychain `claude/<VAR>` — preflight aborts loudly if absent) |
| `com.example.red-main-sweep.plist` | daily 08:15 | `bin/red-main-sweep.py` — red default-branch workflow detection across example-org + example-org + example-labs-org (uses existing `gh` auth, no secrets); writes `~/.claude/red-mains.json` for the session-start banner, macOS-notifies on NEW reds. Instrument failures exit 2 and never overwrite state as "all green" |
| `com.example.x-monitor-daily.plist` | daily 07:45 | `bin/x-monitor-daily.sh` — X perception/adversarial delta sweep (full mode, 2-day window), engagement recheck on tracked negative findings (velocity alerts), and a refreshed 7-day consolidated collection. Keys from login Keychain (`XAI_API_KEY`/`TAVILY_API_KEY`/`FIRECRAWL_API_KEY`, never in this file); reports + state in `~/Documents/x-monitor/`, OUTSIDE git |

## Install

```bash
cp ~/.claude/templates/launchd/com.example.claude.garden.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.claude.garden.plist
```

(repeat per job; `launchctl load` is the legacy spelling of `bootstrap`)

## Operate

```bash
launchctl list | grep com.example.claude          # status (PID/last exit code)
launchctl kickstart gui/$(id -u)/com.example.claude.garden   # run now (test)
launchctl bootout gui/$(id -u)/com.example.claude.garden     # remove
tail -f ~/.claude/audit/launchd/garden.log        # logs
```

After editing a plist: `bootout` then `bootstrap` again (launchd caches).

## Caveats

- The `claude` CLI must be authenticated for the user account; an expired
  login fails silently into the job log — check the logs after the first
  scheduled run, not just `kickstart`.
- Missed `StartCalendarInterval` runs (laptop asleep/off) coalesce into ONE
  run at next wake — jobs never stack.
- `claude -p` here is a single scheduled invocation — the batch-≥20
  FORBIDDEN in `rules/platform-constraints.md` does not apply.
- Jobs run unattended: they inherit your permission config, so keep the
  invoked skills read/curate-only (garden, gather, report) — don't schedule
  anything that pushes or deletes without reviewing its permission surface.
