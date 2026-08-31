# Readiness Method — full procedure + the worked Proteus Polar example

## Critical Gotchas (read first)

- **Static review lies — boot it and drive it.** The two findings that motivated this skill (a focus-trap that shipped axe-clean but caught 0/12 Tabs; a junk upload that returned HTTP 200 on a code-read) were BOTH invisible to source-reading and obvious on the first live drive. Never certify "verified-live" from the code.
- **Read the SOURCE for reason-to-exist, not the README.** Narratives over-claim (Proteus Polar's README claimed "async job processing" that wasn't implemented, and "ZIP export" with no zip path). Doc-drift is itself a finding.
- **The capability oracle must be code-disjoint.** Internal consistency is necessary but not sufficient; a wrong formula passes its own unit tests. The independent library / golden-records / second-implementation is what catches the wrong-formula case.
- **A fix needs a no-false-reject control.** A guard that rejects junk must be tested to still ACCEPT valid input (PP's junk-upload guard had to reject prose while still passing the real ShipMo3D file).

## Step 1 — Reason-to-exist → harden vs rebuild

Read the domain source. Answer "where does this tool's value live in the code?"
- Thin wrapper over a commodity library → rebuild is on the table → **early-exit to /superplan** (this skill hardens; it does not rebuild).
- A niche no off-the-shelf package fills → **harden**.

PP: `seakeeping.py` + `operability.py` showed it runs zero hydrodynamics — it
post-processes vendor-solver output, and `_resolve_column` folds ShipMo3D /
two vendor design tools into one evaluator. No vendor tool reads its competitors'
formats → a real niche → HARDEN.

## Step 2 — Capability oracle (the independent-check menu)

Identify the core correctness claim, validate ≥2 code-disjoint ways:

| Output type | Independent oracles |
|---|---|
| Closed-form math | hand-computed known-value vectors; an independent library re-deriving the formula; real domain data end-to-end |
| Classification / score | hand-labeled gold set; a second implementation; boundary cases at every threshold |
| Transform / report | round-trip property; spec/standard test vectors; a real production input |
| CRUD / workflow (no math) | golden-record state-transition fixtures; API-contract spec-conformance; a real end-to-end task |

PP: 12/12 hand-computed Rayleigh/operability vectors + `scipy.stats.rayleigh`
matched to 1e-12 + the real 338-row MRV0 file evaluated end-to-end (37.5%
operable). The vendor-differential (re-run ShipMo3D, diff operability%) was
**live-blocked — no license** → documented as an open gap, graded AMBIGUOUS on
that sub-axis, NOT faked.

## Step 3-4 — Boot, drive, adversarial-hammer

Specialists own the shape sweep (`/lab-review` frontend, `/service-review`
backend). This skill adds the capability live-drive: the real end-to-end SME
workflow against the running tool with real data. PP: login → upload real MRV0
→ operability evaluate → export PNG/SVG/CSV → health = 11/11 live steps.

Live-blocked escape hatch (per `engineering-assessment-plan-falsifier-discipline`):
if the environment can't support a live drive (GCC-High SSO, classified feed,
HIL, absent vendor license), document the blocker + the strongest available
substitute and grade the axis AMBIGUOUS. Name which readiness you certified:
methodology-ready vs verified-live.

## Step 5 — Grade + verdict

Use the pre-registered bar in `readiness-rubric.md` — axis table first, then the
go/no-go collapse. State honest scope limits.

## The full PP worked example (one-paragraph trace)

`/readiness-review proteus-polar`: Step 1 read `seakeeping.py` → post-processor +
multi-format unifier → HARDEN. Step 2 shape = backend service → dispatched
`/service-review`. Step 3 capability oracle = 12/12 hand-values + scipy 1e-12 +
real MRV0 → Capability A. Step 4 live drive 11/11; vendor-differential
live-blocked (documented). `/service-review` adversarial pass: 13 inputs, 0
crashes, authz holds, but junk.txt → HTTP 200 (fail-open) caught downstream →
bounded to High. Step 5 axis table → Capability A / Reliability A / Usability
B+ / Security A / Operability A, one High → **GO for supervised pilot; fix the
junk-upload guard before unsupervised handoff.** (That fix shipped same session
with a no-false-reject regression test — proving the guard rejects prose while
still accepting the real ShipMo3D file.)
