# Completion Checklist

(Extracted from SKILL.md 2026-07-24 to meet the 5000-word Q1 budget; content unchanged.)

Each item is tagged with the condition under which it applies. Items whose
condition does not hold are N/A and **not** required. The minimum bar is the
core items (no tag); everything else is conditional.

## Core (always required)

- [ ] Phase -1 substrate detection ran and the substrate line was emitted
- [ ] Domain detection completed and documented (or explicitly noted "no domain match")
- [ ] Execution path selected and justified (inline / subagent / team / script / lite)
- [ ] Execution budget uses the one-repair/one-full-suite/one-live-probe defaults, or names the concrete reason for a higher bound
- [ ] Every step has a concrete action (no "implement X" without HOW)
- [ ] No placeholder content (TBD, "similar to task N", vague descriptions)
- [ ] Tool inventory verified (every MCP tool referenced in the plan actually exists)
- [ ] **Load-bearing-mechanism verification**: every phase step that trusts an existing function/tool/flag/field to behave a certain way was read at file:line before presenting (contract == reality), OR explicitly noted as N/A (no phase depends on an existing mechanism's contract). Fires Phase-4-wide, independent of any lift claim.
- [ ] Risk/failure modes identified for non-trivial steps
- [ ] Verification signal stated (how the user will know the task is done)
- [ ] **Number provenance**: every quantity in the plan traces to a saved measurement, verified mechanically — `python3 bin/number-provenance-check.py <plan> --evidence <run artifacts> --strict` exits 0. A value INTERPOLATED between two rows of your own probe is the failure mode: re-run at the value you actually chose. Any hedged figure (`~N`, "about N") is a tell, not a rounding convention.
- [ ] **Self-composition review**: the FINISHED plan was re-read against its own evidence, not just its inputs. Every input fact can be individually verified and the composition still be false. Three checks, each a measured 2026-08-02 defect: (a) does any recommendation contradict the plan's own data? (b) does any arithmetic ignore a semantic the plan itself states — e.g. summing values under a resolution order that SHADOWS? (c) does any setting in one section defeat a choice in another — e.g. a health-check target defeating a declared fail-open posture?
- [ ] **Adversarial pre-hand-over review** `[production]` — for a plan that touches production, an independent reader (ideally a different-provider flagship, per `eval-shipping-discipline.md`) reviewed the plan BEFORE hand-over, and its findings were verified rather than accepted. Stopping bar is invariant coverage, NOT "a review round found nothing" — a sufficiently adversarial review always finds something (KB `engineering-assessment-adversarial-review`, 2026-07-05).

## `[named-entity]` — when the request names a function / file / skill / hook / rule / MCP tool / API endpoint

- [ ] Phase 0 preflight ran for every named entity in the request
- [ ] **Phase 0 mechanical verification**: every cited entity was actually grep'd / ls'd / read. Zero entities cited from session-memory without verification.

## `[substrate]` — when Phase -1 detected the corresponding substrate as Y

- [ ] All relevant topic files loaded for detected domains (substrate `topics:Y`)
- [ ] Knowledge base and agent memory searched for prior decisions (substrate `kb:Y` + `memory-search:Y`)

## `[size-of-effect]` — when the plan claims to lift / improve / fix a measurable property

- [ ] **Self-contained session check**: zero calendar gates and zero external-approval gates between plan steps. Generate / Test / Glean used instead. External reviews are terminal artifacts, never in-plan gates.
- [ ] **Target-state baseline check**: every size-of-effect prediction cites a "currently M" baseline measured in Phase 3.5 on the same target
- [ ] **Demo specificity check**: every Demo line for a size-of-effect phase references a specific target-system entity (file:line, edge target, metric name). Synthetic fixture passes appear only as supplementary regression evidence.
- [ ] **Phase 3.6 6-field gate** per implementation phase: substrate count + layer/prerequisite check + max recoverable lift + local→terminal metric ladder + prior-plan-attribution + n-power budget — all populated or explicitly N/A with justification
- [ ] **Phase 3.5 mechanism-correctness verification**: synthetic-input contract test written + asserted, OR explicitly noted as N/A

## `[observable-system]` — when plan touches extractors / parsers / resolvers / indexers / rankers

- [ ] **Phase ordering check**: instrument → investigate → implement → verify, unless the system already emits the needed signal
- [ ] **Cross-component coordination check** (when adding a new signal — log prefix, metric, env-var, response field): downstream consumer grep'd and either accepts the new shape OR is patched in the same edit batch

## `[deploy-seam]` — when a BUILD phase's artifact is a DEPLOYED component (Lambda module, ECS service, hook, scheduled job)

- [ ] **Deploy-seam check**: the Demo line + `### Metric Commands` assert the artifact reaches its real sink (in the deploy boundary / wired into the running entrypoint / one real invocation crosses every seam) — NOT just `[ -f <file> ]` or `grep -q symbol`. New module placed at its deploy boundary (where the image COPYs from), not by conceptual grouping.
- [ ] **Live-execution rung (the rung ABOVE deploy-asserting)**: the verification runs the real code path against the REAL sink with REAL data — a real Athena query against real rows (not a stubbed client), a real Lambda invoke, the deployed artifact's actual bytes (pull the deployed zip / `ResolvedImageUri`, don't trust the workflow's green check), the resource's own state (`LastModified` advanced past the apply). A unit test that STUBS the sink does NOT cross the seam that breaks: 3 bugs THIS session (#528 query-vs-real-schema, #690 date_diff-vs-real-varchar, #693 producer-vs-consumer-render) all passed stubbed unit tests and failed on first real execution. If the phase's test stubs a sink (Athena/Bedrock/Slack/DynamoDB), it MUST additionally assert the real SHAPE the stub can't catch (the SQL access shape, the payload contract) OR carry a documented live-probe result.
- [ ] **Cross-repo consumer check**: if the artifact is a PRODUCER whose output is read by a consumer in ANOTHER repo (mcp-servers `build_brief_data` → mcp-infra `brief_poster`; any producer/consumer split across repos), the phase verifies the CONSUMER renders/accepts the new output — not just that the producer emits it. The cross-repo seam is invisible to either repo's own test suite (the #693 Phase-5 render gap: producer-tested, consumer-untested, findings reached the data object and died there). Grep the consumer for the new field; assert it reads it, in the SAME phase.

## `[falsifier]` — for M/L/XL plans

- [ ] **Falsifiers section present**: every phase has at least one stated observation that would invalidate the diagnosis, with the corresponding re-diagnosis action. Each falsifier carries a `Derived from: measured | extrapolated | estimated` label.

## `[refresh-then-decide]` — when phase depends on >4h-old measurement

- [ ] **Refresh-then-decide framing**: phase's first step is "refresh the measurement", subsequent steps explicitly conditional on the refresh result. No phase begins with "apply/ship/fix" based on a prior measurement.

## `[prior-arc]` — when Phase 2d fired

- [ ] **Prior-arc ledger built**: every prior plan against the same metric is tabulated with proposed mechanism + predicted lift + measured outcome. Current plan's mechanism is positioned against the ledger.

## `[long-running]` — when any phase is expected to take >24h

- [ ] **Per-phase freshness re-check awareness** (Phase 4b): plan acknowledges that Phase 4b's per-phase baseline-freshness re-check fires at each phase start. Phase 3.5 Baselines section includes the re-check measurement command per metric.

## `[persist]` — when Step 5a fires (`--persist=auto` + substrate + non-lite, OR `--persist=always`)

- [ ] **Terminal-doc-on-undershoot contract acknowledged** (Step 5c): if the plan author predicts a falsifier may trigger, Step 5c's four-section terminal-doc requirement is referenced in the plan's risk/failure section.
- [ ] Plan written to `~/Documents/knowledge-base/plans/YYYY-MM-DD-<slug>.md` and verified non-empty
- [ ] Phase 3.5 baseline written to `~/Documents/knowledge-base/plans/YYYY-MM-DD-<slug>-baseline.md` (sibling), if Phase 3.5 fired
