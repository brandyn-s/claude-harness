export const meta = {
  name: 'corpus-cluster',
  description: 'Phase B4: cluster per-session prose lessons into cross-session recurring patterns',
  phases: [
    { title: 'Cluster', detail: 'one synthesis agent groups all lessons by underlying pattern -> cross-session clusters ranked by breadth' },
  ],
}

// Phase B4 — the LLM clustering pass. ONE synthesis agent reads the collated lessons (cluster_input.json,
// built deterministically by transcript_cluster_input.py) and groups them by UNDERLYING PATTERN (not
// surface text), emitting clusters that each carry their member lesson keys. The cluster gate (B5,
// transcript_semantic_gate.py --mode cluster) then verifies coverage + no-fabrication + recomputes
// breadth deterministically (the LLM's breadth claim is NOT trusted — FLAW-4 count-lying).
//
// Self-contained (flaw #7): a bootstrap agent reads cluster_input.json and returns the lessons; no args.

const INPUT = '/tmp/claude/corpus-sem/cluster_input.json'
const OUT = '/tmp/claude/corpus-sem/clusters.json'

const CLUSTER_SCHEMA = {
  type: 'object',
  required: ['clusters'],
  properties: {
    clusters: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name', 'pattern', 'root_cause', 'proposed_fix', 'tier_hint', 'members'],
        properties: {
          name: { type: 'string' },
          pattern: { type: 'string' },         // the cross-session pattern in one sentence
          root_cause: { type: 'string' },
          proposed_fix: { type: 'string' },
          tier_hint: { type: 'string' },
          members: { type: 'array', items: { type: 'string' } },  // lesson keys "sid::i"
        },
      },
    },
  },
}

phase('Cluster')
log('Phase B4 clustering: one synthesis agent over the collated lessons')

const result = await agent(
  `You are the cross-session lesson-clustering synthesis pass for /mega-distill corpus mode.

STEP 1 — Read ${INPUT} FULLY with the Read tool. It is {n_sessions, n_lessons, lessons:[{key, session,
summary, kind, root_cause, proposed_fix, tier_hint, evidence}, ...]}. Each lesson is one session's
prose meta-lesson. "key" is "sid::index" — your cluster members reference these keys.

STEP 2 — Cluster the lessons by UNDERLYING PATTERN, not surface wording. Two lessons belong together
if they describe the SAME recurring failure/habit even if worded differently — e.g. "trusted a stale
local memory note" + "graded against a 3-day-old baseline" + "acted on a stale cached value" all
cluster as "acted on stale local state without re-verifying". The GOAL is cross-session recurrence:
a cluster spanning many distinct sessions is the high-value systemic signal.

STEP 3 — For each cluster emit: name (short slug), pattern (one sentence — the recurring thing),
root_cause, proposed_fix (a DURABLE fix: a rule, a guard, a habit change), tier_hint
(T1-rule|T2-fact|T4-topic|SKILL:<name>|T0-hook), and members (the list of lesson keys "sid::i" in it).

CRITICAL anti-census rule: the deliverable is a SMALL set of cross-session clusters (expect roughly
8-25 for ~100-300 lessons), NOT one cluster per lesson. A lesson that is genuinely unique to one
session can be its own singleton cluster, but if your cluster count approaches the lesson count you
have NOT clustered — you have re-listed. Merge aggressively by pattern.

COVERAGE rule: EVERY lesson key must appear in EXACTLY ONE cluster's members (the gate fails the run
if any key is unassigned or double-assigned). Do not invent keys that aren't in the input.

STEP 4 — WRITE your result to ${OUT} (python3, encoding='utf-8') as {"clusters":[...]}, then return
the SAME object. The orchestrator runs a deterministic gate that recomputes each cluster's breadth
(distinct sessions among its members) — so members must be accurate; your job is the grouping.`,
  { label: 'cluster:synthesis', phase: 'Cluster', schema: CLUSTER_SCHEMA }
)

const clusters = (result && result.clusters) || []
const totalMembers = clusters.reduce((a, c) => a + (c.members ? c.members.length : 0), 0)
log(`Clustering complete: ${clusters.length} clusters covering ${totalMembers} lesson assignments`)

return {
  n_clusters: clusters.length,
  total_member_assignments: totalMembers,
  clusters: clusters.map((c) => ({ name: c.name, pattern: c.pattern, n_members: (c.members || []).length })),
}