# Evaluation Criteria for `/gather-repos` Runs

## Eval 1: Regular discovery run
**Prompt**: `/gather-repos`
**Grade on**:
1. Were 3+ discovery strategies run in parallel? (yes/no)
2. Were ALL discovered repos batch-screened (not hand-picked)? (yes/no)
3. Were score 4+ repos sent directly to inventory (skipping Phase 2 triage)? (yes/no)
4. Were minimum 5 repos inventoried (or all qualified)? (count)
5. Was the ledger updated with all inventories, assessment queue, and run log? (yes/no)

## Eval 2: Ad-hoc repo inventory
**Prompt**: `/gather-repos https://github.com/someone/interesting-config`
**Grade on**:
1. Was discovery skipped? (yes/no)
2. Were all 6 buckets inventoried? (count)
3. Was the repo type classifier applied? (yes/no)

---

# Ledger Maintenance

Gather-repos maintains a single ledger (`~/.claude/assessed-repos.md`) that tracks:
- **Assessed** repos with verdicts (inventoried, queued, auto-skip, dup, low-signal, qualified)
- **Assessment Queue** for score 4+ repos deferred to future runs
- **Run Log** documenting each run's queries, screening results, and hit rates
- **Handoff to /evaluate-repos** section with inventory summary for downstream evaluation

See SKILL.md Step 5 for ledger update procedure.
