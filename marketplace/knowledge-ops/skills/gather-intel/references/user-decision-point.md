# Step 12: User Decision Point

Present all four sections. Ask the user to approve actions across each section:

**Section 1 (Existing Intel Health):**
- Trim STALE/redundant recommendations from community report
- Create test plans for UNVALIDATED items
- Accept or reject RELAX recommendations for self-imposed constraints
- Resolve RECONCILE contradictions
- Note research-validated and research-contradicted items

**Section 2 (New Findings):**
For each finding, options:
1. **Add to community report** - Append to the community report (see Output File Management section for file location)
2. **Create action item** - Note the specific change to implement (file + what to change)
3. **Queue experiment** - Design and add to experiment backlog
4. **Monitor** - Add to Community Radar for future check-ins
5. **Skip** - Finding noted but no action needed

**Section 3 (Community Threads):**
- Confirm thread assessments
- Approve monitoring or adoption recommendations

**Section 4 (Popularity vs Effectiveness):**
- Confirm or override verdicts
- Approve test plans for UNVALIDATED items
- Approve investigation of HIDDEN GEMs

Ask: "Which findings should I act on? You can approve all, select specific numbers, or skip."

**NEVER auto-write.** Wait for explicit user approval before modifying any files.

After user approval:
- For community report additions: append findings to the appropriate section with source attribution
- For removals: delete stale entries with a note about why
- For action items: present a summary list of changes to implement
- **Skill-modification gate**: If an action item modifies a skill file (`skills/*/SKILL.md`), check the proposed change against skill-standards.md quality criteria before applying: CSO compliance (description = when-to-use only), 250-char trigger phrase window, no stale-prone version-specific content in skill body. Research findings are inputs to skill design, not direct edits. (but don't implement yet - that's a separate task)
- Update the Sources section of the community report with any new URLs
