# Subagent dispatch (improvement 2)

For parallel multi-API ingestion, dispatch the dedicated `api-ingest-worker`
agent instead of `general-purpose`. Its positive `tools:` allowlist exposes local
tools plus five Firecrawl tools; Linear, GitHub, CrowdStrike, and unrelated MCP
tool schemas do not enter the child tool surface. Tool filtering does not by
itself prove how many server processes start, so keep process claims empirical.

```
Agent(
  description: "Ingest {api-name} API docs",
  subagent_type: "api-ingest-worker",
  prompt: "api_name: {api-name}\ndoc_url: {url}\n\nProbe for spec first..."
)
```

**Parallel dispatch limits (current plan: Standard):**
- Up to 10 parallel workers safe (500 scrapes/min = 50 scrapes/worker headroom)
- `/crawl` usable at 50/min — deep-site crawls unproblematic
- Keep the operational cap at 5 until a target-host probe records child process count and resident memory. Do not estimate process fan-out as workers × configured servers: the allowlist proves tool exposure, while server startup behavior is a separate runtime contract.
- Agents MUST write helpers to `$TEMP`, not the output dir
- Other plans: Free=2 workers, Hobby=5, Growth+=10
