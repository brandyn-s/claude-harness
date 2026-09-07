# Lesson routing — public core or private overlay?

`/distill` and `/capture` write lessons down. Since this repository is the public
core of a private configuration (`docs/consuming-from-a-private-overlay.md`),
every lesson has two possible homes, and the choice is not "where is it handy" but
"who may read it". Decide before writing, per lesson, with this table. When in
doubt, the overlay: a lesson can be promoted later; a leak cannot be recalled.

| The lesson is about… | Home | Crosses into the core only as… |
|---|---|---|
| a hook, rule or skill in this repository misbehaving, or a gap in one (a leak shape it missed, a fire rate, two rules fighting) | **core** (`rules/incidents/`, a hook's manifest `incidents:`, `hooks/staged/*.spec.md`) | itself, de-identified — see the strip list |
| how Claude Code / Codex / a model behaves (a platform contract, a compaction effect, a model-specific habit) | **core** (`docs/PLATFORM_NOTES.md`, `hooks/session_start_modules/model_notes.py`, `rules/`) | itself; platform facts carry no organisation |
| an engineering practice with no organisation in it (a testing pattern, a review habit, a scope discipline) | **core** (`rules/`, `docs/rule-reference/`, a skill's `references/`) | itself |
| a specific system, tenant, repository, vendor account, ticket, incident timeline, or person | **overlay** (agent memory topics, audit trackers, the overlay's own `rules/incidents/`) | never as the instance; the *shape* may travel as a core lesson with a synthetic fixture |
| an MCP server's quirks (its write-indicators, auth flow, rate limits) | **overlay**, unless the server is a public product — then the core's environment catalog *example* may gain a placeholder row | a catalog schema change (new section, documented in `hooks/README.md`), never the server's identifiers |
| a workflow that only exists at one organisation (their provisioning, their compliance run) | **overlay** skill | not at all; the core lists such skills in README §What this is a subset of only as removed |

## The strip list (what must not cross)

Before a lesson crosses from the overlay into the core — as a PR, a manifest
incident line, a spec, a rule — remove or replace:

- hostnames, tenant ids, org ids, object ids, connector UUIDs, app-id prefixes
  → `example.internal`, `<tenant-id>`, a `00000000-…` placeholder UUID
- repository and programme names that are not public → `ExampleTarget`,
  `example-repo` (the placeholders the README documents)
- people → a role (`the reviewer`, `contributor-a`), never a first name
- ticket keys and incident numbers → the date and the shape (`the 2026-08-12
  script-file leak`), not the tracker reference
- vendor **account** details (tenant subdomains, client ids) — the vendor's
  public product name is fine (`Jamf`, `Entra`); the instance is not
- the literal secret, always, even redacted to a prefix

The residue gate (`scripts/deidentification_residue.py`) holds the identifiers that
have leaked before and runs on every tracked file, every staged file and every
commit message. It is the floor, not the test: it knows only what has already
leaked once.

## Where each skill applies this

- `/distill` Step 3 (routing to persistence tiers): a T1/T3 target inside the
  harness clone is a **core** write and goes through the strip list; a T2/T4
  target (project memory, topic files) is **overlay**.
- `/capture`: the knowledge-base staging dir is the **overlay** by construction.
  A captured lesson that belongs in the core (first two rows) is *also* filed as
  a core PR, de-identified — not copied from the topic page verbatim.
- `/retro`, `/mega-distill`, `/mega-capture` inherit the same rule through the
  skills they chain.
