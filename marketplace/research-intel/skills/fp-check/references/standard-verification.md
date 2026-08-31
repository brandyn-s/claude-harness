# Standard Verification

Linear single-pass checklist for straightforward bugs. No task creation — work through each step sequentially and document findings inline.

## Terminology and Stop-Hook Contract

Standard verification uses **Step 1..6** headings (this file). Deep verification uses **Phase 1..5** headings (with numbered sub-phases like 1.1, 2.4, 4.4) and lives in [deep-verification.md](deep-verification.md). The Stop hook understands both vocabularies and applies the matching rubric — the Step (standard) labels here map one-for-one to the Phase (deep) labels there for the data-flow, exploitability, impact, PoC, devil's advocate, and gate-review concepts.

A **negative PoC** (a counter-example showing the exploit preconditions that must hold) is **not required** for standard verification — Step 4 below asks for a pseudocode PoC only. Negative PoC is a Phase 4.4 deep-verification artifact. The Stop hook explicitly exempts standard runs from negative-PoC presence; do not invent one to satisfy a literal grep.

## Phase Mapping (Standard Step ↔ Deep Phase)

When the Stop hook (or a downstream reader) speaks in Phase numbers, translate to Standard Steps using this table:

### Phase 1 ↔ Step 1: Data Flow Analysis
- Step 1 here covers Phase 1.1 (trust boundaries), Phase 1.2 (API contracts), Phase 1.3 (environment protections), and Phase 1.4 (cross-references) in a single linear pass.

### Phase 2 ↔ Step 2: Exploitability Verification
- Step 2 here covers Phase 2.1 (attacker control), Phase 2.2 (mathematical bounds), Phase 2.3 (race conditions), and Phase 2.4 (adversarial analysis).

### Phase 3 ↔ Step 3: Impact Assessment
- Step 3 here covers Phase 3.1 (real security impact) and Phase 3.2 (primary control vs defense-in-depth).

### Phase 4 ↔ Step 4: PoC Sketch
- Step 4 here covers Phase 4.1 (pseudocode PoC with data flow diagram), and treats Phase 4.2 (executable PoC), Phase 4.3 (unit test PoC), Phase 4.4 (negative PoC), and Phase 4.5 (PoC verification) as optional with explicit skip.

### Phase 5 ↔ Step 5 + Step 6: Devil's Advocate and Gate Review
- Step 5 here is the 7-question subset of Phase 5's 13-question devil's-advocate review.
- Step 6 here is the same 6-gate review used at the end of the deep path.

## Escalation Checkpoints

Two points in this checklist may trigger escalation to [deep-verification.md](deep-verification.md):

1. **After Step 1 (Data Flow)**: Escalate if 3+ trust boundaries, callbacks/async control flow, or ambiguous validation chain
2. **After Step 5 (Devil's Advocate)**: Escalate if any question produces genuine uncertainty you cannot resolve

When escalating, hand off all evidence gathered so far — deep verification will continue from where you left off.

## Checklist

### Step 1: Data Flow

Trace data from source to the alleged vulnerability sink.

- Map trust boundaries crossed (internal/trusted vs external/untrusted)
- Identify all validation and sanitization between source and sink
- Check API contracts — many APIs have built-in bounds protection that prevents the alleged issue
- Check for environmental protections (compiler, runtime, OS, framework) that prevent exploitation entirely (not just raise the bar)
- Apply class-specific checks from [bug-class-verification.md](bug-class-verification.md)

**Key pitfall**: Analyzing the vulnerable code in isolation. Conditional logic upstream may make the vulnerability mathematically unreachable. Trace the full validation chain.

**Escalation check**: If you found 3+ trust boundaries, callbacks or async control flow in the path, or an ambiguous validation chain — escalate to deep verification.

### Step 2: Exploitability

Prove the attacker can trigger the vulnerability.

- **Attacker control**: Prove the attacker controls data reaching the vulnerable operation. Internal storage set by trusted components is not attacker-controlled.
- **Bounds proof**: For integer/bounds issues, create an explicit algebraic proof using the template in [evidence-templates.md](evidence-templates.md). Verify: IF validation_check_passes THEN bounds_guarantee_holds.
- **Race feasibility**: For race conditions, prove concurrent access is actually possible. Single-threaded initialization and synchronized contexts cannot have races.

### Step 3: Impact

Determine whether exploitation has real security consequences.

- Distinguish real security impact (RCE, privesc, info disclosure) from operational robustness issues (crash recovery, cleanup failure)
- Distinguish primary security controls from defense-in-depth. Failure of a defense-in-depth measure is not a vulnerability if primary protections remain intact.

### Step 4: PoC Sketch

Create a pseudocode PoC showing the attack path. Executable and unit test PoCs are optional for standard verification — but if you omit them, write an explicit one-line skip statement (e.g., "Executable PoC: skipped — pseudocode is sufficient for this class") so the Stop hook can confirm the decision was made rather than the section was forgotten.

```
Data Flow: [Source] → [Validation?] → [Transform?] → [Vulnerable Op] → [Impact]
Attacker controls: [what input, how]
Trigger: [pseudocode showing the exploit path]
```

See [evidence-templates.md](evidence-templates.md) for the full PoC template.

### Step 5: Devil's Advocate Spot-Check

Answer these 7 questions. If any produces genuine uncertainty, escalate to deep verification.

**Against the vulnerability:**

1. Am I seeing a vulnerability because the pattern "looks dangerous" rather than because it actually is? (pattern-matching bias)
2. Am I incorrectly assuming attacker control over trusted data? (trust boundary confusion)
3. Have I rigorously proven the mathematical condition for vulnerability can occur? (proof rigor)
4. Am I confusing defense-in-depth failure with a primary security vulnerability? (defense-in-depth confusion)
5. Am I hallucinating this vulnerability? LLMs are biased toward seeing bugs everywhere — is this actually real or am I pattern-matching on scary-looking code? (LLM self-check)

**For the vulnerability (always ask — false-negative protection):**

6. Am I dismissing a real vulnerability because the exploit seems complex or unlikely?
7. Am I inventing mitigations or validation logic that I haven't verified in the actual source code? Re-read the code after reaching a conclusion.

**Escalation check**: If any question above produces genuine uncertainty you cannot resolve with the evidence at hand — escalate to deep verification.

### Step 6: Gate Review

Apply all six gates from [gate-reviews.md](gate-reviews.md) and all 13 items from [false-positive-patterns.md](false-positive-patterns.md) to reach a verdict.
