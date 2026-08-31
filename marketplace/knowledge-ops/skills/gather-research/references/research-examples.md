# gather-research Examples

**Example 1: Monthly full-scope research refresh**
User says: `/gather-research`
Actions:
1. Phase A: Load baseline, audit 15 existing research-derived recommendations for currency and practice status. Memory search surfaces 3 relevant agent learnings.
2. Phase A finds: 1 SUPERSEDED (newer ReAct variant), 2 EVOLVED, 1 MISAPPLIED (simplified version loses key benefit), 2 UNTESTED
3. Step 3b: Decompose into 7 research questions covering all 8 architecture components
4. Phase B Wave 1: 10 parallel basic searches dynamically generated from research questions
5. Phase B Wave 2: 2 tavily_research(pro) syntheses (with verification) + targeted follow-ups + known sources check
6. Step 6b: 5 adversarial queries for preliminary HIGH/MEDIUM findings. 1 finding downgraded due to failed replication.
7. Phase B identifies 3 research threads: "structured reflection improves agent recovery" (4 papers), "context-aware tool selection" (3 papers), "memory consolidation patterns" (3 papers)
8. Convergence reached in 2 waves (new-rate dropped to 22%)
9. Phase C: Combined report with baseline health table + 8 ranked findings + 3 threads + transfer analysis. ~35 Tavily credits consumed.
Result: User approves updating 1 SUPERSEDED recommendation, correcting 1 MISAPPLIED implementation, adding 4 HIGH findings with transfer paths, and queuing 2 experiments.

**Example 2: Targeted focus area research**
User says: `/gather-research agent memory`
Actions:
1. Phase A: Audit memory-related recommendations in baseline. Memory search finds 5 relevant entries.
2. Step 3b: Decompose "agent memory" into 6 research questions (episodic memory, consolidation, retrieval, decay, scaling, cross-session persistence)
3. Phase B: All queries target agent memory specifically. 3 waves needed (niche topic, Wave 2 new-rate was 45%)
4. Step 6b: 4 adversarial queries. 1 finding revealed as framework-specific (LangChain memory, doesn't transfer cleanly)
5. Phase C: Focused report mapping memory research against the current file-based MEMORY.md approach
Result: User approves 2 pattern adoptions and 1 experiment comparing current approach against research-backed consolidation strategy.
