# Provider Monitor Contracts

This is a non-invocable shared contract for provider-monitor skills and their cross-provider router. Provider-specific source, identity, API, and mutation contracts always remain in the provider skill.

## Query descriptor

Normalize every request before source selection:

| Field | Contract |
|---|---|
| `provider` | `claude`, `openai`, or an explicit set; never inferred from a generic word when the choice changes sources |
| `surface` | named product/runtime surface such as Claude Chat, Claude Code, ChatGPT, OpenAI API, or Codex |
| `source_id` | one or more exact provider source identities, resolved by the provider skill |
| `intent` | content/activity, audit, usage, cost, inventory, security finding, health, quality, delivery, or mutation |
| `grain` | event, message, session/conversation, actor/day, project/day, finding, run, report, inventory snapshot, or another declared unit |
| `window_start`, `window_end` | inclusive start and exclusive end in UTC unless the provider contract explicitly says otherwise |
| `time_basis` | `operational_window`, `data_window`, or `producer_run_window`; report both operational and later data-day processing when “health for a day” could mean either |
| `actor_scope` | native actor/team/project identifiers plus any governed mapping generation |
| `freshness_need` | live, latest settled, exact historical generation, or bounded forensic |
| `changes_state` | false for reads; true for any provider, AWS, storage, delivery, or administrative mutation |

Extensibility comes from mapping `intent × grain × source capability`, not from one regex or bespoke script per question.

## Evidence precedence

For each source, prefer:

1. an existing complete artifact at the question's grain;
2. verified normalized semantic facts bound to an exact source generation;
3. manifest-ready settled facts/Gold when the manifest and coverage are current;
4. bounded raw evidence when higher-level artifacts lack required fields or content.

Do not silently substitute a different surface or source. A summary report can answer summary questions; it cannot prove raw content, source exhaustion, detector denominator, or delivery by itself.

## Provider result envelope

Every provider result carries:

- `provider`, `surface`, `source_id`;
- `window_start`, `window_end`, `as_of`, and `freshness_at`;
- `time_basis`, `health_state`, and the producer/run window when it differs from the data window;
- `intent`, `grain`, and direct answer;
- `coverage_state`, source denominator, terminal/manifest state, and data-through time;
- identity namespace, mapping generation, ambiguity/unresolved counts, and actor scope;
- cost basis and unit when money or usage is reported;
- facts, estimates, and inference as distinct fields;
- `evidence_refs` such as query IDs, object VersionIds/hashes, request IDs, run/task revisions, finding IDs, manifests, and delivery receipts;
- unavailable sources, known seams, and any mutation receipt.

For cross-provider work, return `provider_results` as an ordered list. Each provider result remains valid independently even when another is `partial`, `unavailable`, or `unknown`.

## Coverage states

Use source-native states and map them conservatively:

| Shared state | Meaning |
|---|---|
| `complete` | required source denominator is terminal and the requested grain is supported |
| `observed_empty` | a bounded source completed and proved a terminal empty interval |
| `empty_without_watermark` | the source returned empty but did not prove a safe terminal bound |
| `partial` | some required pages, targets, families, surfaces, or downstream receipts are incomplete |
| `stale` | last qualifying evidence predates the required freshness window |
| `failed` | the source or producer has a terminal failure receipt |
| `unavailable` | the source/capability is known not to be reachable or activated in the current context |
| `unknown` | evidence needed to distinguish states was not read or does not exist |

A negative result requires every required source to be `complete` or `observed_empty` for the exact window and grain. Missing evidence never becomes zero.

## Identity and cost composition

- Preserve native identity namespaces. Email, provider user ID, API key, workspace/project, principal, device, and workload identities are not interchangeable.
- Join identities only through an explicit mapping generation that reports resolved, ambiguous, unresolved, and not-applicable outcomes.
- A device or workload submitter proves provenance of submission, not necessarily a human actor or semantic truth.
- Preserve provider-reported/billed, effective/allocated, and client-estimated cost bases separately. Do not add unlike currencies, time bases, discounts, or estimate classes.
- Usage units are comparable only when their semantic definition, window, and denominator match; “tokens” from unlike product planes can remain parallel facts rather than one total.

## Liveness, health, coverage, quality, and delivery

Report these as separate propositions:

- **liveness:** a producer or consumer ran;
- **health:** the latest/status evidence for that component was healthy;
- **coverage:** required sources and denominators were captured for the window;
- **quality:** outcome-backed precision/recall or another explicitly measured metric;
- **delivery:** an analyst surface received the exact finding/report generation.

Use `health_state=healthy`, `degraded`, `failed`, `stale`, `unavailable`, or
`unknown` for the qualified component/window. Keep it separate from
`coverage_state`: a later healthy processing run may settle a data day without
making the earlier operational wall-clock window healthy, and a healthy
component can still have partial source coverage.

An exit code, current alarm state, object write, detector verdict, or Slack post proves only its own proposition. For windowed health, bind the active configuration timestamp and inspect alarm history plus metric/log extrema.

## Findings and analyst surfaces

Keep candidate, judge decision, promoted finding, analyst delivery, and human outcome as distinct grains. Deterministic, regex, anomaly, injection, taint, and credential rules can generate candidates or corroboration; contextual judging can classify semantic content; human outcomes supply truth labels.

Slack is an analyst decision surface. Bind every visible item to authority, evidence generation, impact, freshness, and next action; use the durable source/report and delivery ledger for proof.

## Mutation receipt

Before a provider mutation, bind authorization to provider/account/organization, exact target IDs or inclusive dates, expected effects, bounded resources/cost, verification artifact, and rollback or irreversibility. After execution, record requested, accepted, terminal, and observed states separately. Acceptance is not completion.

## Adding query types or providers

For a new query type:

1. add the intent/grain route to the owning provider skill;
2. name required sources, identity rules, denominator, and terminal evidence;
3. add deterministic positive, negative, partial, and ambiguous routing cases;
4. reuse this envelope rather than creating a new output shape.

For a new provider, create a provider skill when acquisition, identity, completeness, or mutation contracts differ. Add it to the cross-provider router only after its own provider tests pass. Do not move provider mechanics into this shared file.
