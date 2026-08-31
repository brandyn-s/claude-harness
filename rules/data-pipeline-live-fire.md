---
# PATH-SCOPED at creation (2026-08-27): a data-pipeline redesign is always
# expressed through IaC, SQL, or ETL source, so delivery-on-matching-edit fits
# the trigger. The decision this rule gates (enable the full schedule) is an
# arc-level process decision spanning many edits, not a single tool call, so
# the unmeasured paths: injection TIMING (see rule-authoring.md's honest-gap
# note) is acceptable here. mcp-infra additionally carries this contract
# ambiently in its own AGENTS.md/CLAUDE.md.
paths:
  - "**/*.tf"
  - "**/*.sql"
  - "**/etl/**"
  - "**/glue/**"
  - "**/*pipeline*"
  - "**/*materializ*"
---

@rule data_pipeline_live_fire
@version 2026-08-27
@scope every data-pipeline redesign — a new materializer, table layout, ingestion path, storage format, or changed provenance/certification model — in any repository, before its schedule covers the full population

# Data-Pipeline Live-Fire — Decision Contract

Operator directive (2026-08-27, verbatim intent): "a data-pipeline redesign gets a
single-partition live-fire before schedule-wide rollout."

INVARIANT one_real_partition_end_to_end_before_the_schedule_widens
INVARIANT green_plan_apply_and_unit_suite_do_not_substitute_for_first_contact
INVARIANT killable_runs_emit_a_start_heartbeat_and_cap_polls_at_remaining_runtime

# Required sequence
STEP_1 deploy the redesigned path DISABLED or scoped to manual invocation.
STEP_2 run it end-to-end against ONE real partition/day.
STEP_3 verify three things against independent oracles before widening:
       - the certification artifact (manifest/receipt) exists and validates;
       - row counts match an INDEPENDENTLY known count for that partition
         (an INSERT can "succeed" writing 0 rows — a count oracle is the only
         thing that catches it);
       - terminal metrics emitted (started AND terminal; a platform kill emits
         neither receipt nor metric unless the run heartbeats first).
STEP_4 only then enable the full schedule, and soak the first scheduled cycle.

# Why CI is blind by construction (measured, 2026-08-26/27 session-Gold arc)
Nine stacked defects shipped through green plan + green apply + a green unit
suite, each masking the next: catalog-accepts/engine-rejects validation splits
(Glue vs Hive), partition projection/format mismatches that read as EMPTY
tables, memory sizing (silent OOM kills), data-plane IAM (the query engine
reads storage as the CALLER role — enumerate the engine's reads, not just the
SDK calls), and real-data damage no fixture predicted. A single-partition
live-fire front-loads exactly these classes. Full stack:
mcp-infra LESSONS-LEARNED.md "A data-pipeline redesign gets a
single-partition live-fire before schedule-wide rollout".

GUARD pattern="the plan is green and the unit suite passes, just enable the schedule":
  REFUSE. Plan/apply/unit-green are blind to first-contact classes by
  construction. Run STEP_2 on one real partition first. NO EXCEPTIONS.
GUARD pattern="we're behind schedule / it's a small change to the pipeline":
  REFUSE urgency and size framing. The live-fire costs one invoke and one
  soak; the 2026-08 skip cost ~36 hours of production iteration. NO EXCEPTIONS.
GUARD pattern="the fixture suite covers real data shapes":
  REFUSE. Real data contained sidecar-less orphan sessions no fixture
  predicted; fixtures model the contract, not the corpus. NO EXCEPTIONS.

# Exclusions
Additive changes inside an already-live-fired pipeline (a new column, a
threshold change) need normal verify-effectiveness discipline, not a fresh
live-fire — unless they change the provenance/certification model or the
read path's engine/format assumptions.
