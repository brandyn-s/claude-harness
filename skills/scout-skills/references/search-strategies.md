# Search Strategies (Step 0 detail)

## Search strategies (rotate, don't sequence)

| Strategy | When to use | Query style |
|----------|-------------|-------------|
| **Category sweep** | First pass, or new session | Noun-heavy: "security vulnerability", "testing tdd" |
| **Gap-driven** | After category sweep | Problem descriptions of what we lack: "verify test quality via mutation", "track workaround staleness against library changelogs" |
| **Refinement** | After building/modifying skills | Search for what we just built: "plan estimation ambiguity resolution", "context window token audit". Better versions may exist. |
| **Suggest API** | Any time | `POST /api/v2/skills/suggest` with varied inputs: skill names, technology deps, behavioral descriptions |
| **Queue mining** | Any time | Use `gh api` to list skills in repos from assessment queue (the Context7 `?project=` endpoint may return unexpected formats — use GitHub API tree listing instead) |
| **Deep-dive expansion** | After a productive repo | List ALL skills in a repo that produced 1+ findings — explore the rest |

**Query creativity matters more than strategy selection.** The same strategy
with different query phrasing returns entirely different results.

| Stale query | Creative alternative |
|-------------|-------------------|
| "testing strategy tdd" | "verify test quality via mutation injection" |
| "security vulnerability" | "prevent starting work on underspecified tickets" |
| "code review pr review" | "evidence-grounded option comparison before decision" |
| "debugging root cause" | "how to know when a workaround is no longer needed" |

**When to ACTUALLY stop**: Report "session search space narrowing" when:
- You've tried 3+ creative query variations across 2+ strategies and ALL
  returned only already-seen repos with no unread skills
- The user explicitly says to stop
- NOT after running each strategy once with obvious inputs

(Revised after 2026-04-06 session: the original 5-level linear escalation
created a false completion signal. Passes 2-3 reran exhausted queries, pass 5
declared "saturated" after running each level once with obvious inputs. The
registry had thousands of unseen skills the entire time.)

## Default categories (search all unless scoped)

| Category | Search queries |
|----------|---------------|
| Security | "security vulnerability", "threat model", "compliance audit" |
| Testing | "testing strategy tdd", "property testing", "mutation testing" |
| Debugging | "debugging", "root cause analysis" |
| Infrastructure | "terraform aws", "docker", "ci cd github actions" |
| Rust | "rust development", "rust async tokio error" |
| Python | "python best practices", "python async httpx pydantic" |
| Prompt/Agent | "prompt engineering agent", "skill creator" |
| Code review | "code review", "pr review" |
| Documentation | "documentation technical writing runbook" |
| Git workflow | "git workflow commit" |
| Observability | "logging monitoring observability", "tracing opentelemetry" |
| API design | "api design patterns rest graphql openapi" |

**Coverage ratings removed.** Three runs (2026-04-05/06) showed "Weak"
categories (Documentation, API design) produced mostly generic templates,
while the highest-value patterns came from **recurring high-trust repos**
regardless of category. Don't prioritize by coverage gap — prioritize by
repo signal in Step 1.

## Search via Context7 REST API

```bash
# Search — returns JSON with name, project, trustScore, benchmarkScore, relevance
curl -s "https://context7.com/api/v2/skills?query=<keywords>" \
  -o /tmp/scout-<category>.json

# List all skills in a specific repo (use GitHub API — Context7 project
# endpoint returns unexpected format as of 2026-04-07)
gh api 'repos/{owner}/{repo}/git/trees/HEAD?recursive=1' \
  --jq '.tree[].path' | grep -i "skill.md"
```

Response shape: `{results: [{name, description, url, project, trustScore, benchmarkScore, relevance, verified}]}`

The `url` field is a Context7 internal reference, NOT a reliable raw GitHub
URL. Do not `curl` it directly — it will 404. Always use the GitHub API
(Method 2 in Step 2) as the default fetch method. (Confirmed 2026-04-11:
9/9 URLs from search results returned 404 when fetched with curl.)

Run all category searches in parallel:

```bash
for query in "security vulnerability" "testing strategy tdd" ...; do
  curl -s "https://context7.com/api/v2/skills?query=$(echo $query | tr ' ' '+')" \
    -o "/tmp/scout-$(echo $query | tr ' ' '-').json" &
done
wait
```

Minimum: 8 categories per run when unscoped. For focused scans, use 3+
query variations on the focus area plus 2-3 adjacent categories.

## Optional: technique-vocabulary queries (frontier-imported patterns)

The 2026-05-17 roundtable flagged that Context7's category labels return
CC-formatted skills authored by community members. Skills whose authors
IMPORTED industry/research techniques (TRIZ, FMEA, chaos engineering,
property-based testing, fuzzing) appear in the same registry but under
different query phrasings. Run a small set of technique-vocabulary
queries alongside the category sweep to surface them:

| Query phrasing | What it tends to surface |
|---|---|
| "mutation testing equivalent mutant detection" | shrinking/test-quality skills with named heuristics |
| "chaos engineering principles" | fault-injection skills with failure-mode catalogs |
| "fuzzing harness design" | input-generation skills with corpus-management techniques |
| "STRIDE per interaction" | threat-modeling skills with element-type matrices |
| "property-based test shrinking" | hypothesis/PBT skills with shrink-strategy patterns |
| "differential testing" | comparator-design skills with oracle-selection rubrics |
| "metamorphic testing" | invariant-based testing skills |
| "fault injection patterns" | resilience-test skills with failure-class taxonomies |
| "deception engineering" | honeypot/canary skills with telemetry patterns |
| "supply chain integrity verification" | SLSA/in-toto skills with attestation flows |
| "formal verification lightweight" | proof-assistant or contract-test skills |

**Boundary with /scout-frontier:** these queries surface techniques that
**happen to already be encoded in Context7 skills**. For paradigm-distinct
approaches NOT yet in Context7 — academic frontier, industrial
state-of-the-art, cross-domain analogies — use `/scout-frontier`. If a
technique-vocabulary query returns 0 useful skills, that's a signal to
hand off to `/scout-frontier`, not to invent the technique from
imagination here.

**Cost-bound:** run 4-6 technique-vocabulary queries per session, not all
11. Pick the ones that target known weak categories or recently-touched
domains. Empty result sets are valid signal (informs the /scout-frontier
handoff) and not a failure.
