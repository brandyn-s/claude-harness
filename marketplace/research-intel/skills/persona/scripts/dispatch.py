"""Persona dispatch harness — supports discovery, rubric, and meta modes.

Reads:
  - inventory file (markdown, canonical format)
  - problem statement (string or file)
  - optional fixture.yaml (rubric mode only) for ground truth + scoring
    rubric

Writes per-run dir:
  - problem.md (the problem actually used)
  - results-by-persona/persona_NN_ID.json (one per dispatched persona)
  - STARTED.lock (marks the run as started; prevents pre-reg edits)
  - analysis.md (synthesis or per-cell metrics depending on mode)

Usage examples:

    # Discovery mode (loose problem, manual synthesis)
    python3 dispatch.py discovery "<problem>" --slug 2026-05-01-some-slug

    # Rubric mode (structured problem, pre-reg rubric, dual scoring)
    python3 dispatch.py rubric --slug 2026-05-01-rubric-test \\
        --fixture path/to/fixture.yaml

    # Meta mode (research experiment — manual rubric iteration)
    # Meta is a documentation stub: invoke rubric mode N times with
    # different --slug suffixes, varying --n / --model / --seed, then
    # use scripts/analyze.py per run dir. See run_meta() for guidance.
    python3 dispatch.py meta --slug 2026-05-01-meta-scaling
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from pathlib import Path

import anthropic

# Force UTF-8 stdout for Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent

sys.path.insert(0, str(SCRIPTS_DIR))
from cohort_sample import sample
from model_runtime import (
    DEFAULT_JUDGE_MODEL,
    DEFAULT_PERSONA_MODEL,
    cache_matches_runtime,
    message_request,
    recommended_max_tokens,
    resolve_judge_effort,
    resolve_judge_model,
    resolve_model_id,
    resolve_persona_effort,
    resolve_persona_model,
    runtime_receipt,
)
from parse_inventory import parse_file

# Configurable defaults — env vars override hardcoded paths so the skill
# is portable across machines / marketplace installations.
DEFAULT_RUN_BASE = Path(os.environ.get(
    "PERSONA_DISPATCH_RUNS",
    str(Path.home() / "Documents" / "knowledge-base" / "research" / "dispatch-runs"),
))
DEFAULT_INVENTORY = Path(os.environ.get(
    "PERSONA_INVENTORY",
    str(Path.home() / "Documents" / "knowledge-base" / "research"
        / "2026-04-29-frameworks-master-inventory.md"),
))
DEFAULT_COHORT_YAML = Path(os.environ.get(
    "PERSONA_COHORT_YAML",
    str(Path.home() / "Documents" / "knowledge-base" / "research"
        / "2026-05-01-persona-behavior-cohort-v2.yaml"),
))
# Discovery / rubric prompt template. Updated 2026-05-02 to require the
# [novel]/[default] calibration tag and "Measurable axis" per recommendation.
# Mirror this verbatim in templates/dispatch-prompt.md when changes ship.
DISPATCH_PROMPT_TEMPLATE = """You are a problem-solving persona embodying this framework:

# {framework_name}

{framework_body}

---

## Your task

Read the problem statement below and apply your framework's lens to
diagnose root causes and propose specific fixes.

The problem:

{problem}

## Output requirements

Produce a numbered list of 3-5 recommendations. For EACH recommendation:
- One sentence stating what to do
- One sentence explaining why your framework's lens cares about this
- **Measurable axis**: name the categorical property you would `GROUP BY`
  to validate this recommendation's effect. Examples: "edges grouped by
  caller_kind", "requests grouped by payload_size_bucket", "users grouped
  by tenure_quartile". If you cannot name a measurable axis, prefix the
  recommendation with `[SPECULATIVE]`.
- **Calibration tag**: prefix the recommendation with either `[novel]`
  (the recommendation requires your framework's specific lens — would
  NOT arise from default first-instinct engineering) or `[default]` (the
  recommendation would surface naturally without your framework's lens —
  e.g., "tighten the threshold," "add a retry," "increase the timeout").

Output FORMAT (verbatim, do not deviate):

1. [novel|default] [Recommendation]: [brief description]
   Rationale: [framework-specific reasoning]
   Measurable axis: [GROUP BY property] OR [SPECULATIVE — no axis]

2. ...

Forbidden:
- Generic recommendations ("improve quality")
- Recommendations not derivable from your framework's lens
- Mode-collapse onto the framework's headline pattern without
  naming where it specifically applies to this problem
- Omitting the calibration tag or measurable axis
"""


# Inversion mode: complete standalone template. Replaces the dual-spec
# str.replace() bug — personas now receive a single coherent output spec
# rather than the regular Output requirements section appended after.
INVERSION_PROMPT_TEMPLATE = """You are a problem-solving persona embodying this framework:

# {framework_name}

{framework_body}

---

## Your task

Read the problem below. The team's existing metrics have plateaued.
From your framework's lens, what would you MEASURE about this system
that the current standard metrics don't capture?

The problem:

{problem}

## Output requirements

Surface 3-5 candidate dimensions. For each:

1. Name the dimension (one phrase)
2. Why your framework cares about this dimension (1-2 sentences)
3. A SPECIFIC metric definition (numerator / denominator, threshold,
   or aggregation rule)
4. Tractability tier (EASY post-hoc / CHEAP <1hr / INSTRUMENTED
   schema-change / RESEARCH user-studies)
5. Counterfactual: "If the system scored badly on this metric, what
   user-visible problem would surface?"

Output FORMAT (verbatim, do not deviate):

1. **Dimension**: [one phrase]
   Why: [1-2 sentences]
   Metric: [definition]
   Tractability: [EASY | CHEAP | INSTRUMENTED | RESEARCH]
   Counterfactual: [user-visible problem if scored badly]

2. ...

Forbidden:
- Generic dimensions ("improve quality")
- Dimensions not derivable from your framework's lens
- Restating existing metrics under a new name
"""


def build_persona_prompt(framework: dict, problem: str,
                          inversion: bool = False) -> str:
    body = framework["body"][:1500]
    template = INVERSION_PROMPT_TEMPLATE if inversion else DISPATCH_PROMPT_TEMPLATE
    return template.format(
        framework_name=framework["name"],
        framework_body=body,
        problem=problem,
    )


def dispatch_one(client: anthropic.Anthropic, framework: dict,
                  problem: str, model: str, inversion: bool = False,
                  effort: str | None = None) -> dict:
    prompt = build_persona_prompt(framework, problem, inversion=inversion)
    t0 = time.time()
    try:
        request = message_request(
            model=model,
            max_tokens=recommended_max_tokens(
                workload="persona",
                model=model,
                effort=effort,
            ),
            messages=[{"role": "user", "content": prompt}],
            effort=effort,
        )
        resp = client.messages.create(**request)
        text = "".join(
            getattr(block, "text", "")
            for block in resp.content
            if getattr(block, "type", "text") == "text"
        )
        effective_model = getattr(resp, "model", None)
        stop_reason = getattr(resp, "stop_reason", None)
        receipt = runtime_receipt(
            requested_model=model,
            requested_effort=effort,
            effective_model=effective_model,
            stop_reason=stop_reason,
        )
        common = {
            "framework_id": framework["id"],
            "framework_name": framework["name"],
            "framework_group": framework["group"],
            "elapsed_s": round(time.time() - t0, 2),
            "model": effective_model or "<unavailable>",
            "requested_model": model,
            "effort": effort or "<unavailable>",
            "stop_reason": stop_reason or "<unavailable>",
            "runtime_receipt": receipt,
        }
        if effective_model is None:
            return {
                **common,
                "ok": False,
                "error_type": "model_unobserved",
                "error": (
                    "Anthropic response omitted model metadata; the result "
                    "cannot qualify the requested model lane"
                ),
            }
        if effective_model is not None and effective_model != model:
            return {
                **common,
                "ok": False,
                "error_type": "model_mismatch",
                "error": (
                    f"Requested {model}, but Anthropic returned {effective_model}; "
                    "result is not qualification evidence for the requested model"
                ),
            }
        if stop_reason == "refusal":
            return {
                **common,
                "ok": False,
                "error_type": "refusal",
                "error": "Anthropic model refused the persona dispatch",
            }
        if stop_reason in {"max_tokens", "model_context_window_exceeded"} or not text:
            reason = stop_reason if stop_reason != "end_turn" else "no_text_content"
            return {
                **common,
                "ok": False,
                "error_type": "incomplete_response",
                "error": f"Anthropic persona dispatch was incomplete: {reason}",
            }
        return {
            **common,
            "ok": True,
            "text": text,
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "framework_id": framework["id"],
            "framework_name": framework["name"],
            "framework_group": framework["group"],
            "ok": False,
            "error_type": "transport_or_api",
            "error": str(e)[:300],
            "elapsed_s": round(time.time() - t0, 2),
            "model": "<unavailable>",
            "requested_model": model,
            "effort": effort or "<unavailable>",
            "runtime_receipt": runtime_receipt(
                requested_model=model,
                requested_effort=effort,
            ),
        }


def deterministic_seed(slug: str) -> int:
    h = hashlib.md5(slug.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % (2 ** 31 - 1)


def _warn_curator_bias(inventory_path: Path) -> None:
    """Surface curator-bias warning at dispatch start.

    Looks for an `inventories/<slug>.meta.yaml` next to the skill that flags
    the inventory as curator-biased, and prints a stderr warning. This makes
    bias visible to non-author users running the skill from the marketplace.
    """
    meta_dir = SKILL_DIR / "inventories"
    if not meta_dir.exists():
        return
    inv_stem = inventory_path.stem.lower()
    for meta_file in meta_dir.glob("*.meta.yaml"):
        try:
            text = meta_file.read_text(encoding="utf-8").lower()
        except Exception:  # noqa: BLE001
            continue
        if inv_stem in text and ("curator-biased" in text or "curator_biased" in text):
            print(f"⚠ Inventory {inventory_path.name} is flagged curator-biased "
                  f"(see {meta_file.name}). Cross-check against an independent "
                  f"inventory before treating convergence as cross-frame robustness.",
                  file=sys.stderr)
            return


def check_pre_registration(run_dir: Path) -> dict:
    """For rubric mode: check pre-registration commit timestamp.

    Returns a dict with one of six `status` values:
      - 'missing'        — no pre-registration.md in the run dir
      - 'no_lock'        — pre-registration.md present, STARTED.lock absent
      - 'pre_registered' — pre-registration committed BEFORE first dispatch
      - 'post_hoc_edit'  — pre-registration committed AFTER first dispatch
                            (this run is post-hoc, not pre-registered)
      - 'git_error'      — git log invocation failed (e.g., cwd not a repo)
      - 'unknown'        — fallthrough; status could not be determined

    Uses git log to check the pre-registration.md commit time vs STARTED.lock
    creation time. All callers MUST handle every status — see run_rubric()
    for the canonical handler.
    """
    pre_reg_path = run_dir / "pre-registration.md"
    started_lock = run_dir / "STARTED.lock"
    if not pre_reg_path.exists():
        return {"status": "missing", "message": "No pre-registration.md"}
    if not started_lock.exists():
        return {"status": "no_lock", "message": "Pre-registration not yet locked"}
    # Both exist; check which came first
    import subprocess
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", str(pre_reg_path)],
            capture_output=True, text=True, cwd=str(run_dir.parent),
        )
        if result.returncode == 0 and result.stdout.strip():
            commit_time = int(result.stdout.strip())
            lock_time = int(started_lock.stat().st_mtime)
            if commit_time < lock_time:
                return {"status": "pre_registered",
                         "commit_time": commit_time, "lock_time": lock_time}
            return {"status": "post_hoc_edit",
                     "commit_time": commit_time, "lock_time": lock_time,
                     "message": "Pre-registration was modified AFTER first dispatch — "
                                "this run's results are post-hoc."}
    except Exception as e:  # noqa: BLE001
        return {"status": "git_error", "message": str(e)[:200]}
    return {"status": "unknown"}


def run_discovery(args: argparse.Namespace) -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set")
    inventory_path = Path(args.inventory) if args.inventory else DEFAULT_INVENTORY
    frameworks = parse_file(inventory_path)
    print(f"Inventory: {inventory_path.name} ({len(frameworks)} frameworks)")
    _warn_curator_bias(inventory_path)

    seed = args.seed if args.seed is not None else deterministic_seed(args.slug)
    rng = random.Random(seed)

    # Behavior-driven sampling: load cohort.yaml and pass behaviors through.
    # Falls through to bucket/random/curated if --behaviors is not set.
    cohort_data = None
    behaviors_list: list[str] = []
    if args.sampling == "behavior":
        if not args.behaviors:
            sys.exit("--sampling behavior requires --behaviors b1,b2,...")
        cohort_yaml = Path(args.cohort_yaml) if args.cohort_yaml else DEFAULT_COHORT_YAML
        if not cohort_yaml.exists():
            sys.exit(f"cohort.yaml not found: {cohort_yaml}")
        cohort_data = load_cohort_yaml(cohort_yaml)
        behaviors_list = [b.strip() for b in args.behaviors.split(",") if b.strip()]
        unknown = [b for b in behaviors_list if b not in cohort_data]
        if unknown:
            sys.exit(f"Unknown behaviors {unknown}. Available: {sorted(cohort_data.keys())}")

    cohort = sample(
        frameworks, args.n, rng,
        rule=args.sampling,
        cohort_data=cohort_data,
        behaviors=behaviors_list or None,
        min_confidence=args.min_confidence,
    )
    print(f"Cohort (N={len(cohort)}, sampling={args.sampling}, seed={seed}"
          + (f", behaviors={behaviors_list}" if behaviors_list else "") + "):")
    for f in cohort:
        tags = ""
        if f.get("_matched_behaviors"):
            tags = f"  [{', '.join(f['_matched_behaviors'])}]"
        print(f"  - {f['name'][:60]}{tags}")

    run_dir = DEFAULT_RUN_BASE / args.slug
    run_dir.mkdir(parents=True, exist_ok=True)
    started = run_dir / "STARTED.lock"
    if not started.exists():
        started.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
    (run_dir / "problem.md").write_text(args.problem, encoding="utf-8")
    persona_dir = run_dir / "results-by-persona"
    persona_dir.mkdir(exist_ok=True)

    client = anthropic.Anthropic()
    dispatches: list[dict] = []
    for i, f in enumerate(cohort, 1):
        out_path = persona_dir / f"persona_{i:02d}_{f['id']}.json"
        if out_path.exists():
            try:
                cached = json.loads(out_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                print(f"error: malformed cached persona JSON in {out_path}: {e}",
                      file=sys.stderr)
                print("  hint: delete the corrupt file and re-run to re-dispatch "
                      "this persona.", file=sys.stderr)
                sys.exit(2)
            if cache_matches_runtime(
                cached,
                requested_model=args.model,
                requested_effort=args.effort,
            ):
                print(f"  [{i:>2}/{len(cohort)}] cached: {f['name'][:50]}")
                dispatches.append(cached)
                continue
            print(f"  [{i:>2}/{len(cohort)}] stale runtime cache: "
                  f"{f['name'][:50]} — re-dispatching")
        print(f"  [{i:>2}/{len(cohort)}] dispatching: {f['name'][:50]}", flush=True)
        d = dispatch_one(
            client,
            f,
            args.problem,
            args.model,
            inversion=args.inversion,
            effort=args.effort,
        )
        out_path.write_text(json.dumps(d, indent=2), encoding="utf-8")
        dispatches.append(d)

    # Synthesis (non-interactive) — clustering placeholder; real impl would
    # use embedding similarity. For now we emit raw output for manual review.
    write_discovery_analysis(run_dir, dispatches, args)
    failures = [d for d in dispatches if not d.get("ok")]
    if failures:
        failure_types = sorted({d.get("error_type", "unknown") for d in failures})
        print(
            f"Persona discovery failed closed: {len(failures)}/{len(dispatches)} "
            f"dispatches failed ({', '.join(failure_types)}). Partial diagnostics: "
            f"{run_dir / 'analysis.md'}",
            file=sys.stderr,
        )
        return 1
    update_index(run_dir, args, dispatches, mode="discovery")
    print(f"\nRun complete: {run_dir}")
    print("Read analysis.md for synthesis. Discovery mode requires manual review.")
    return 0


def write_discovery_analysis(run_dir: Path, dispatches: list[dict],
                               args: argparse.Namespace) -> None:
    successful = [d for d in dispatches if d["ok"]]
    bucket_count: dict[str, int] = {}
    for d in successful:
        bucket_count[d["framework_group"]] = bucket_count.get(d["framework_group"], 0) + 1

    out = []
    out.append(f"# Discovery dispatch — {args.slug}")
    out.append("")
    out.append("**Mode**: discovery (loose problem, manual synthesis)")
    out.append(f"**N**: {len(successful)} successful / {len(dispatches)} dispatched")
    out.append(f"**Sampling**: {args.sampling}")
    out.append(f"**Inventory**: {args.inventory or DEFAULT_INVENTORY.name}")
    out.append(f"**Requested model**: {args.model}")
    out.append(f"**Requested effort**: {args.effort or '<unavailable>'}")
    out.append("**Runtime evidence**: see each persona JSON's `runtime_receipt`")
    out.append(f"**Inversion mode**: {'yes' if args.inversion else 'no'}")
    out.append("")
    out.append("## Bucket coverage")
    out.append("")
    for g, n in sorted(bucket_count.items(), key=lambda x: -x[1]):
        out.append(f"- {n} from {g[:60]}")
    out.append("")
    out.append("## Per-persona recommendations")
    out.append("")
    out.append("Read each output and classify recommendations as:")
    out.append("- ACTIONABLE (specific enough for a ticket)")
    out.append("- DILIGENCE (good practice but not insight)")
    out.append("- INSIGHT (novel framing the team hadn't considered)")
    out.append("- OFF-TARGET (not engaged with the problem)")
    out.append("")
    out.append("Per F6 finding: discovery mode does NOT use automated scoring.")
    out.append("Casual scoring would over-rate plausibility; manual review is required.")
    out.append("")
    for i, d in enumerate(dispatches, 1):
        if not d["ok"]:
            out.append(f"### Persona {i:02d}: {d['framework_name']} — DISPATCH FAILED")
            out.append(f"Error: {d.get('error', 'unknown')}")
            out.append("")
            continue
        out.append(f"### Persona {i:02d}: {d['framework_name']}")
        out.append(f"**Bucket**: {d['framework_group']}")
        out.append("")
        out.append(d["text"])
        out.append("")
    (run_dir / "analysis.md").write_text("\n".join(out), encoding="utf-8")


_UPDATE_INDEX_LOCK = threading.Lock()


def update_index(run_dir: Path, args: argparse.Namespace,
                  dispatches: list[dict], mode: str) -> None:
    """Append a row to INDEX.md.

    Two-layer serialization for cross-platform reliability:

    1. **Thread lock** — an in-process `threading.Lock` ensures threads
       inside one Python interpreter never race past the file-lock
       acquisition step. The Windows CI runner can be slow enough that
       O_CREAT|O_EXCL retries don't always converge within the
       30s/jittered-backoff budget when 5 threads contend tightly. The
       in-process lock makes the test fully deterministic without
       changing the file-lock semantics that cross-process callers
       depend on.

    2. **File lock** — sidecar `INDEX.md.lock` via O_CREAT|O_EXCL.
       Atomic on POSIX and Windows. This is the cross-process
       serialization mechanism; the test's threading scenario is a
       proxy for the real cross-process invocation pattern (each
       `dispatch.py` CLI invocation is its own process).

    The PR #974 / PR #976-revert / Track C history shows that file
    locking alone is fragile under contention on slow runners. The
    two-layer approach is robust everywhere.
    """
    # Layer 1: in-process thread lock. Eliminates the file-lock retry
    # storm when multiple threads in the same interpreter contend (the
    # `test_update_index_serializes_concurrent_writes` scenario).
    # Without this, on slow runners (Windows CI especially) the
    # O_CREAT|O_EXCL retries don't always converge within the
    # 30s/jittered-backoff budget when 5 threads contend tightly.
    with _UPDATE_INDEX_LOCK:
        index_path = DEFAULT_RUN_BASE / "INDEX.md"
        lock_path = index_path.with_suffix(".md.lock")
        if not index_path.exists():
            index_path.write_text(
                "# Persona dispatch — run index\n\n"
                "| Date | Slug | Mode | Problem | N | Model | Link |\n"
                "|---|---|---|---|---|---|---|\n",
                encoding="utf-8",
            )
        successful = sum(1 for d in dispatches if d["ok"])
        problem_short = args.problem[:60].replace("|", "\\|").replace("\n", " ") if hasattr(args, "problem") and args.problem else "(rubric mode — see fixture.yaml)"
        date = time.strftime("%Y-%m-%d")
        rel = run_dir.relative_to(DEFAULT_RUN_BASE)
        line = (f"| {date} | {args.slug} | {mode} | {problem_short} | "
                f"{successful}/{args.n} | {args.model} | "
                f"`dispatch-runs/{rel}/analysis.md` |\n")

        # Layer 2: cross-process file lock via O_CREAT|O_EXCL. Atomic on
        # POSIX and Windows. The PR #974 30s deadline + 20ms+jittered
        # backoff stays in place to handle the cross-process case (each
        # `dispatch.py` CLI invocation is its own Python process; the
        # threading lock only covers in-process callers). The audit-
        # skill campaign close (PR #976) accidentally reverted PR #974;
        # this commit restores it.
        deadline = time.time() + 30.0
        fd = None
        while time.time() < deadline:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                time.sleep(0.02 + random.uniform(0, 0.01))
        if fd is None:
            # Lock acquisition timed out — peer holds the lock.
            print(f"WARN: update_index timed out waiting for {lock_path}; "
                  f"skipping index append for this run", file=sys.stderr)
            return
        try:
            with index_path.open("a", encoding="utf-8") as f:
                f.write(line)
        finally:
            os.close(fd)
        # Only unlink the lock we successfully acquired (fd is not None
        # at this point; the early-return above handles the timeout case).
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def load_fixture(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        sys.exit(f"Fixture file not found: {path}")
    except OSError as e:
        sys.exit(f"Could not read fixture {path}: {e}")
    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML required for rubric mode. pip install pyyaml")
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        sys.exit(
            f"Fixture {path} is not valid YAML: {e}\n"
            f"  See templates/rubric.yaml for the expected schema."
        )


def load_cohort_yaml(path: Path) -> dict[str, list[dict]]:
    """Load the persona behavior-coverage cohort YAML produced by
    score_persona_behaviors.py. Falls back to a hand-parser if PyYAML is
    unavailable, since the cohort format is small and uses a single,
    consistent flow-style line per entry."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml
        data = yaml.safe_load(text) or {}
        return {k: v or [] for k, v in data.items() if not k.startswith("_")}
    except ImportError:
        # Hand-parse the cohort.yaml format we generate:
        #   behavior_name:
        #     - {id: ..., name: "...", confidence: HIGH, frequency: 6}
        result: dict[str, list[dict]] = {}
        current: str | None = None
        flow_pat = re.compile(r"^\s*-\s*\{(.*)\}\s*$")
        for line in text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            if not line.startswith(" ") and line.rstrip().endswith(":"):
                current = line.split(":", 1)[0].strip()
                result[current] = []
                continue
            m = flow_pat.match(line)
            if m and current:
                # Parse a flow-style entry: id: x, name: "y", confidence: HIGH, frequency: 6
                entry: dict = {}
                buf = m.group(1)
                # Split on commas not inside quotes
                parts = re.findall(r'(\w+)\s*:\s*("(?:[^"\\]|\\.)*"|[^,]+)', buf)
                for k, v in parts:
                    v = v.strip()
                    if v.startswith('"') and v.endswith('"'):
                        v = v[1:-1].replace('\\"', '"')
                    elif v.isdigit():
                        v = int(v)  # type: ignore[assignment]
                    entry[k] = v
                result[current].append(entry)
        return result


def run_rubric(args: argparse.Namespace) -> int:
    """Rubric mode — pre-registered fixture, structured problem, dual scoring.

    Pipeline:
      1. Load fixture.yaml (problem + RC/FL ground truth + cohort config)
      2. Save fixture + problem into run dir
      3. Pre-registration check (warn-loudly on post-hoc edit)
      4. Sample cohort per fixture's cohort.sampling
      5. Dispatch each persona with the structured problem
      6. Score every output via keyword stance check
      7. Score every output via LLM-judge (default Opus 5 at high effort)
      8. Aggregate per-RC endorsement + Cohen's kappa via analyze.py
      9. Append run to INDEX.md
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set")
    if not args.fixture:
        # Rubric mode requires an explicit fixture. Silently rebinding a
        # rubric run to whatever fixture.yaml is newest under the runs base
        # defeats pre-registration discipline (the run would measure against
        # an unstated, drifting ground truth). Require --fixture by name.
        sys.exit(
            "--fixture is required in rubric mode. Pass "
            "--fixture path/to/fixture.yaml explicitly so the run is "
            "pinned to a named, pre-registered fixture."
        )
    fixture_path = Path(args.fixture)
    if not fixture_path.exists():
        sys.exit(f"Fixture not found: {fixture_path}")
    fixture = load_fixture(fixture_path)

    problem = fixture.get("problem", "").strip()
    if not problem:
        sys.exit("Fixture missing 'problem' field")

    cohort_cfg = fixture.get("cohort", {}) or {}
    models_cfg = fixture.get("models", {}) or {}

    # === Fixture-wins-over-CLI (rubric pre-registration discipline) ===
    # If fixture sets a value AND user passed a contradicting CLI flag,
    # fail loud + log to run dir. Pre-registration that CLI silently
    # breaks isn't pre-registration. --override-fixture is the explicit opt-out.
    fixture_n = cohort_cfg.get("n")
    fixture_sampling = cohort_cfg.get("sampling")
    fixture_persona_model = models_cfg.get("persona")
    fixture_persona_effort = models_cfg.get("persona_effort")
    fixture_judge_model = models_cfg.get("judge")
    fixture_judge_effort = models_cfg.get("judge_effort")

    overrides: dict[str, dict] = {}
    if (args.n is not None and fixture_n is not None and args.n != fixture_n):
        overrides["n"] = {"cli": args.n, "fixture": fixture_n}
    if (args.sampling is not None and fixture_sampling is not None
            and args.sampling != fixture_sampling):
        overrides["sampling"] = {"cli": args.sampling, "fixture": fixture_sampling}
    # Model values are compared as resolved ids: `--model haiku` against a fixture
    # that pins the Haiku snapshot is the same lane, not a conflict. An
    # unresolvable id raises here, before the run directory exists.
    if (args.model is not None and fixture_persona_model is not None
            and resolve_model_id(args.model) != resolve_model_id(fixture_persona_model)):
        overrides["model"] = {"cli": args.model, "fixture": fixture_persona_model}
    if (args.effort is not None and fixture_persona_effort is not None
            and args.effort != fixture_persona_effort):
        overrides["effort"] = {
            "cli": args.effort,
            "fixture": fixture_persona_effort,
        }
    if (args.judge_model is not None and fixture_judge_model is not None
            and resolve_model_id(args.judge_model) != resolve_model_id(fixture_judge_model)):
        overrides["judge_model"] = {"cli": args.judge_model,
                                      "fixture": fixture_judge_model}
    if (args.judge_effort is not None and fixture_judge_effort is not None
            and args.judge_effort != fixture_judge_effort):
        overrides["judge_effort"] = {
            "cli": args.judge_effort,
            "fixture": fixture_judge_effort,
        }

    run_dir = DEFAULT_RUN_BASE / args.slug
    run_dir.mkdir(parents=True, exist_ok=True)

    if overrides:
        log_path = run_dir / "cli_override_attempt.json"
        log_payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "slug": args.slug,
            "fixture": str(fixture_path),
            "attempted_overrides": overrides,
            "resolved": "cli" if args.override_fixture else "fixture",
        }
        log_path.write_text(json.dumps(log_payload, indent=2), encoding="utf-8")
        print()
        print("✗ CLI flags conflict with pre-registered fixture values:")
        for k, v in overrides.items():
            print(f"    {k}: fixture={v['fixture']!r}  <-  CLI tried {v['cli']!r}")
        print(f"  Logged to {log_path.relative_to(run_dir.parent.parent)}")
        if not args.override_fixture:
            print()
            print("  Pre-registration discipline: fixture wins. Either:")
            print("    (a) re-run without the conflicting CLI flag")
            print("    (b) edit the fixture and git-commit BEFORE re-running")
            print("        (the run will then be flagged post-hoc)")
            print("    (c) pass --override-fixture to opt out explicitly")
            print("        (the override is logged and the run is post-hoc)")
            sys.exit(1)
        print()
        print("⚠ --override-fixture flag set; CLI values used. Run is post-hoc.")
        print()

    # Resolve final values: fixture wins where set, else CLI override (if
    # --override-fixture was used), else CLI fill-in, else default.
    if args.override_fixture:
        n = args.n if args.n is not None else (fixture_n if fixture_n is not None else 15)
        sampling = args.sampling or fixture_sampling or "bucket"
        persona_model = resolve_persona_model(args.model or fixture_persona_model)
        persona_effort = resolve_persona_effort(args.effort or fixture_persona_effort)
        judge_model = resolve_judge_model(args.judge_model or fixture_judge_model)
        judge_effort = resolve_judge_effort(args.judge_effort or fixture_judge_effort)
    else:
        n = fixture_n if fixture_n is not None else (args.n if args.n is not None else 15)
        sampling = fixture_sampling or args.sampling or "bucket"
        persona_model = resolve_persona_model(fixture_persona_model or args.model)
        persona_effort = resolve_persona_effort(fixture_persona_effort or args.effort)
        judge_model = resolve_judge_model(fixture_judge_model or args.judge_model)
        judge_effort = resolve_judge_effort(fixture_judge_effort or args.judge_effort)

    # Write resolved values back to args so downstream consumers
    # (update_index, _print_summary, etc.) see the effective config
    # rather than the pre-resolution None. Without this, INDEX.md rows
    # showed `"15/None | None |"` whenever the fixture supplied the value
    # instead of the CLI.
    args.n = n
    args.model = persona_model
    args.effort = persona_effort
    args.judge_model = judge_model
    args.judge_effort = judge_effort

    curated_ids: list[str] = []
    if sampling == "curated":
        if args.frameworks:
            curated_ids = [s.strip() for s in args.frameworks.split(",") if s.strip()]
        else:
            curated_ids = list(cohort_cfg.get("curated_framework_ids", []) or [])
        if not curated_ids:
            sys.exit("curated sampling requires --frameworks or "
                      "cohort.curated_framework_ids in fixture")

    # === Provenance check (Fix J — fixture authorship transparency) ===
    prov = fixture.get("provenance", {}) or {}
    if not prov.get("fixture_author"):
        print()
        print("✗ Fixture missing required `provenance.fixture_author`.")
        print("  See templates/rubric.yaml for the provenance schema.")
        print("  Add fixture_author + inventory_authored_by + independent flag,")
        print("  re-commit fixture, then re-run.")
        sys.exit(1)
    if prov.get("independent") is False:
        print()
        print("ℹ NOTE: fixture and inventory share authorship "
              f"(fixture_author={prov.get('fixture_author')!r}, "
              f"inventory_authored_by={prov.get('inventory_authored_by')!r}).")
        print("  This run validates reproducibility within ONE frame.")
        print("  It does NOT validate methodology generality across frames.")
        print("  See references/methodology-evolution.md (J finding).")
        print()

    inventory_path = Path(args.inventory) if args.inventory else DEFAULT_INVENTORY
    frameworks = parse_file(inventory_path)
    print(f"Inventory: {inventory_path.name} ({len(frameworks)} frameworks)")
    _warn_curator_bias(inventory_path)

    seed = args.seed if args.seed is not None else deterministic_seed(args.slug)
    rng = random.Random(seed)
    cohort = sample(frameworks, n, rng, rule=sampling, curated_ids=curated_ids)
    print(f"Cohort (N={len(cohort)}, sampling={sampling}, seed={seed}, "
          f"persona_model={persona_model}, persona_effort={persona_effort or '<unset>'}, "
          f"judge_model={judge_model}, judge_effort={judge_effort}):")
    for f in cohort:
        print(f"  - {f['name'][:60]}")

    (run_dir / "fixture.yaml").write_text(
        fixture_path.read_text(encoding="utf-8"), encoding="utf-8")
    (run_dir / "problem.md").write_text(problem, encoding="utf-8")

    pre_reg = check_pre_registration(run_dir)
    if pre_reg["status"] == "post_hoc_edit":
        print()
        print("⚠️  WARNING: pre-registration edited AFTER first dispatch.")
        print(f"    {pre_reg.get('message', '')}")
        print("    Continuing — but flag this run as post-hoc, not pre-registered.")
        print()
    elif pre_reg["status"] == "no_lock":
        print("Pre-registration: not yet locked (first dispatch).")
    elif pre_reg["status"] == "pre_registered":
        print(f"Pre-registration: locked at commit_time={pre_reg.get('commit_time')}")
    elif pre_reg["status"] == "missing":
        # SKILL.md Step 3 / Success Criteria: pre-registration must be
        # git-committed BEFORE first dispatch in rubric mode. If the file
        # doesn't exist, the run violates the documented invariant —
        # warn loudly so the user can either (a) write+commit pre-registration.md
        # first, or (b) accept that this run is post-hoc.
        print()
        print("⚠️  WARNING: no pre-registration.md found in the run dir.")
        print("    Rubric mode's invariant is that pre-registration is git-committed")
        print("    BEFORE first dispatch (SKILL.md Success Criteria). This run will")
        print("    be flagged post-hoc unless you write+commit pre-registration.md")
        print(f"    at {run_dir / 'pre-registration.md'} before re-running with the")
        print("    same slug.")
        print()
    elif pre_reg["status"] == "git_error":
        # Git invocation failed — surface the underlying error so the
        # operator can fix it (likely: cwd not inside a git repo, or git
        # binary missing). Don't silently dispatch when we can't verify
        # pre-registration timestamps.
        print()
        print("⚠️  WARNING: pre-registration check could not query git.")
        print(f"    {pre_reg.get('message', '')}")
        print("    Continuing — but this run's pre-registration status is unverified.")
        print()
    elif pre_reg["status"] == "unknown":
        # check_pre_registration returned an empty/unhandled status; treat
        # as unverified (same as git_error path) rather than silently
        # dispatching.
        print()
        print("⚠️  WARNING: pre-registration status could not be determined.")
        print("    Continuing — but this run's pre-registration status is unverified.")
        print()

    started = run_dir / "STARTED.lock"
    if not started.exists():
        started.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
    persona_dir = run_dir / "results-by-persona"
    persona_dir.mkdir(exist_ok=True)

    # === Phase 1: dispatch personas ===
    client = anthropic.Anthropic()
    dispatches: list[dict] = []
    for i, f in enumerate(cohort, 1):
        out_path = persona_dir / f"persona_{i:02d}_{f['id']}.json"
        if out_path.exists():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                print(f"error: malformed cached persona JSON in {out_path}: {e}",
                      file=sys.stderr)
                print("  hint: delete the corrupt file and re-run to re-dispatch "
                      "this persona.", file=sys.stderr)
                sys.exit(2)
            d = existing.get("dispatch") or existing
            if cache_matches_runtime(
                d,
                requested_model=persona_model,
                requested_effort=persona_effort,
            ):
                print(f"  [{i:>2}/{len(cohort)}] cached: {f['name'][:50]}")
                dispatches.append(existing)
                continue
            print(f"  [{i:>2}/{len(cohort)}] stale runtime cache: "
                  f"{f['name'][:50]} — re-dispatching")
        print(f"  [{i:>2}/{len(cohort)}] dispatching: {f['name'][:50]}", flush=True)
        d = dispatch_one(
            client,
            f,
            problem,
            persona_model,
            effort=persona_effort,
        )
        rec = {"dispatch": d}
        out_path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        dispatches.append(rec)

    failed_dispatches = [
        rec.get("dispatch") or rec
        for rec in dispatches
        if not (rec.get("dispatch") or rec).get("ok")
    ]
    if failed_dispatches:
        failure_types = sorted(
            {d.get("error_type", "unknown") for d in failed_dispatches}
        )
        print(
            f"Persona rubric run failed closed: {len(failed_dispatches)}/"
            f"{len(dispatches)} persona dispatches failed "
            f"({', '.join(failure_types)}). Partial results: {persona_dir}",
            file=sys.stderr,
        )
        return 1

    # === Phase 2: keyword scoring ===
    print("\nKeyword scoring (programmatic stance check)...")
    from score_keyword import score as keyword_score
    n_kw = 0
    for p in sorted(persona_dir.glob("persona_*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"error: malformed persona JSON in {p}: {e}", file=sys.stderr)
            print("  hint: delete the corrupt file and re-run to re-dispatch "
                  "this persona.", file=sys.stderr)
            sys.exit(2)
        d = rec.get("dispatch") or rec
        if not d.get("ok"):
            continue
        rec.setdefault("scoring", {})
        rec["scoring"]["keyword"] = keyword_score(d.get("text", ""), fixture)
        p.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        n_kw += 1
    print(f"  scored {n_kw} outputs")

    # === Phase 3: LLM-judge scoring ===
    print(f"\nLLM-judge scoring ({judge_model}, effort={judge_effort})...")
    from score_llm_judge import judge as judge_one
    n_jd = 0
    judge_failures: list[tuple[str, str]] = []
    for p in sorted(persona_dir.glob("persona_*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"error: malformed persona JSON in {p}: {e}", file=sys.stderr)
            print("  hint: delete the corrupt file and re-run to re-dispatch "
                  "this persona.", file=sys.stderr)
            sys.exit(2)
        d = rec.get("dispatch") or rec
        if not d.get("ok"):
            continue
        # Skip ONLY if the cached result has both ok==True AND a parsed
        # judgment (i.e., not a stuck _parse_error). Without this guard,
        # JSON-decode failures persist as sticky state because the API
        # call succeeded — so re-runs never retry the bad parse.
        prior = rec.get("scoring", {}).get("llm_judge", {})
        prior_judgment = prior.get("judgment", {}) if isinstance(prior, dict) else {}
        if (prior.get("ok")
                and isinstance(prior_judgment, dict)
                and "_parse_error" not in prior_judgment
                and any(k.startswith("rc") for k in prior_judgment)
                and cache_matches_runtime(
                    prior,
                    requested_model=judge_model,
                    requested_effort=judge_effort,
                )):
            continue  # already judged AND parsed cleanly (resumable)
        print(f"  judging: {p.name}", flush=True)
        rec.setdefault("scoring", {})
        judge_result = judge_one(
            client,
            fixture,
            d.get("text", ""),
            judge_model,
            effort=judge_effort,
        )
        rec["scoring"]["llm_judge"] = judge_result
        p.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        n_jd += 1
        if not judge_result.get("ok"):
            judge_failures.append(
                (p.name, judge_result.get("error_type", "unknown"))
            )
    print(f"  attempted {n_jd} new outputs")

    if judge_failures:
        failure_types = sorted({error_type for _, error_type in judge_failures})
        print(
            f"Persona rubric run failed closed: {len(judge_failures)}/"
            f"{len(dispatches)} LLM judgments failed "
            f"({', '.join(failure_types)}). Partial results: {persona_dir}",
            file=sys.stderr,
        )
        return 1

    # === Phase 4: aggregate analysis ===
    print("\nAggregating analysis (kappa per RC)...")
    import subprocess
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "analyze.py"), str(run_dir)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  analyze.py exit {result.returncode}: {result.stderr.strip()[:300]}")
    else:
        print(f"  {result.stdout.strip()}")

    # === Phase 5: index ===
    update_index(run_dir, args, [r.get("dispatch") or r for r in dispatches],
                  mode="rubric")
    print(f"\nRun complete: {run_dir}")
    print(f"Read {run_dir / 'analysis.md'} for kappa per RC + endorsement rates.")
    return 0


def run_meta(_args: argparse.Namespace) -> int:
    """Meta mode — multi-cell experiment matrix.

    Same as rubric mode but with --n, --models, --seeds parsed as
    comma-separated lists, producing a cell per combination. Each
    cell's outputs get separate scoring + analysis.

    Stub for now; meta-mode runs are infrequent (research experiments
    only) and the orchestration is the same as rubric, just looped.
    """
    print("Meta mode runs the rubric workflow across a variable matrix.")
    print("Implementation pattern: outer loop over cells, inner = rubric.")
    print()
    print("For now, run rubric mode N times with different --slug suffixes:")
    print("  python3 dispatch.py rubric --slug runA-haiku-N11 --model haiku --n 11 ...")
    print("  python3 dispatch.py rubric --slug runA-haiku-N25 --model haiku --n 25 ...")
    print("  ...")
    print("Then pass the run dirs to scripts/analyze.py with --aggregate.")
    return 0


ARTICLE_VI_CRITERIA = [
    "Aggregate metric plateau >=2 sessions of standard engineering work",
    "Per-subset variance >=2x the aggregate",
    "Both precision AND recall stuck simultaneously",
    "Engineer cannot articulate 'what to measure next'",
    ">30 minutes of conventional investigation already done with diminishing results",
]


def _check_article_vi(args: argparse.Namespace) -> tuple[bool, str]:
    """Enforce the Article VI triage gate documented in SKILL.md Step 0.

    Returns (ok, message). When ok is False, the caller should print message
    to stderr and return exit code 2. The skill refuses to dispatch unless
    >=2 of the 5 triggering criteria hold — this prevents cargo-cult
    dispatches on fresh / bug-shaped problems.

    Two acceptance paths:
      - Headless: --criteria-met=N (int 0-5); pre-computed by the operator.
      - Interactive: prompt the dispatcher for Y/N on each of the 5 criteria.

    --skip-article-vi opts out entirely (operator has already done the
    triage and accepts responsibility); the bypass is logged to stderr.
    """
    if getattr(args, "skip_article_vi", False):
        print("Article VI gate: SKIPPED via --skip-article-vi "
              "(operator asserts triage already done).", file=sys.stderr)
        return True, ""

    criteria_met = getattr(args, "criteria_met", None)

    if criteria_met is None:
        # Interactive triage. stdin must be a TTY; otherwise headless callers
        # must pass --criteria-met=N. (A non-interactive run with no value
        # is treated as "0 met" — the gate refuses by default rather than
        # silently dispatching.)
        if not sys.stdin.isatty():
            return False, (
                "Article VI gate: no --criteria-met=N supplied and stdin is "
                "not a TTY. Headless callers must pass --criteria-met=N "
                "(0-5). For pre-triaged dispatches, pass --skip-article-vi."
            )
        print("Article VI triage gate — answer Y/N for each criterion:",
              file=sys.stderr)
        count = 0
        for i, c in enumerate(ARTICLE_VI_CRITERIA, 1):
            while True:
                ans = input(f"  [{i}/5] {c}? (Y/N): ").strip().lower()
                if ans in ("y", "yes"):
                    count += 1
                    break
                if ans in ("n", "no"):
                    break
                print("    Please answer Y or N.", file=sys.stderr)
        criteria_met = count

    if not isinstance(criteria_met, int) or criteria_met < 0 or criteria_met > 5:
        return False, (
            f"Article VI gate: --criteria-met must be an integer 0-5, "
            f"got {criteria_met!r}."
        )

    if criteria_met < 2:
        return False, (
            f"Article VI gate REFUSED: {criteria_met}/5 criteria met "
            f"(need >=2). The skill refuses to dispatch on cargo-cult "
            f"problems. Try /code-explore for fresh problems, "
            f"/scout-frontier for paradigm reframing, /fp-check for FP "
            f"suspicion. To bypass when you've already triaged, pass "
            f"--skip-article-vi."
        )

    print(f"Article VI gate: PASSED ({criteria_met}/5 criteria met).",
          file=sys.stderr)
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["discovery", "rubric", "meta"])
    ap.add_argument("problem", nargs="?", default="",
                     help="Problem statement (or path to .md file)")
    ap.add_argument("--slug", required=True,
                     help="Run slug (becomes the run dir name)")
    def _parse_n(v: str) -> int:
        """Accept either a bare int or a comma-list (meta mode legacy form).
        For non-meta modes only the first value is used; meta mode is a
        manual stub so the comma-list is accepted for forward-compat with
        the docstring example."""
        if "," in v:
            parts = [p.strip() for p in v.split(",") if p.strip()]
            if not parts:
                raise argparse.ArgumentTypeError(f"empty --n list: {v!r}")
            try:
                return int(parts[0])
            except ValueError as e:
                raise argparse.ArgumentTypeError(
                    f"--n list contains non-int value: {parts[0]!r}") from e
        try:
            return int(v)
        except ValueError as e:
            raise argparse.ArgumentTypeError(f"--n must be int or comma-list of ints, got {v!r}") from e

    ap.add_argument("--n", type=_parse_n, default=None,
                     help="Cohort size (default 15, min 11). In rubric mode, "
                          "fixture's cohort.n wins over this flag. Meta mode "
                          "accepts a comma-list (the first value is used; "
                          "meta is a manual stub — iterate rubric runs with "
                          "different --slug suffixes for a real matrix sweep).")
    ap.add_argument("--sampling", default=None,
                     choices=["bucket", "random", "curated", "behavior"],
                     help="Cohort sampling rule (default bucket). In rubric "
                          "mode, fixture's cohort.sampling wins over this flag.")
    ap.add_argument("--frameworks", default="",
                     help="Comma-separated framework IDs (curated sampling only)")
    ap.add_argument("--behaviors", default="",
                     help="Comma-separated agent-behavior columns (behavior sampling only). "
                          "E.g., 'edge_case_hunter,metric_inventor,trickster' selects personas "
                          "scoring strong on any of those in the cohort YAML. See "
                          "research/2026-04-30-persona-behavior-gaps.md for the full list.")
    ap.add_argument("--cohort-yaml", default=None,
                     help=f"Path to cohort YAML (default: {DEFAULT_COHORT_YAML.name}). "
                          "Required when --sampling behavior.")
    ap.add_argument("--min-confidence", default="MED",
                     choices=["HIGH", "MED", "LOW"],
                     help="Minimum confidence for behavior sampling (default MED). "
                          "Drops cohort entries below this rank.")
    ap.add_argument("--seed", type=int, default=None,
                     help="RNG seed (default: deterministic from slug)")
    ap.add_argument("--inventory", default=None,
                     help="Inventory file path (default: canonical-2026-04-29)")
    ap.add_argument("--model", default=None,
                     help=f"Persona model (default: {DEFAULT_PERSONA_MODEL}). "
                          "In rubric mode, fixture's models.persona wins.")
    ap.add_argument("--effort", default=None,
                     choices=["low", "medium", "high", "xhigh", "max"],
                     help="Persona effort (default: unset for Haiku 4.5). "
                          "In rubric mode, fixture's models.persona_effort wins.")
    ap.add_argument("--judge-model", default=None,
                     help=f"LLM-judge model (default: {DEFAULT_JUDGE_MODEL}). "
                          "In rubric mode, fixture's models.judge wins.")
    ap.add_argument("--judge-effort", default=None,
                     choices=["low", "medium", "high", "xhigh", "max"],
                     help="LLM-judge effort (default: high). In rubric mode, "
                          "fixture's models.judge_effort wins.")
    ap.add_argument("--inversion", action="store_true",
                     help="Discovery mode: ask 'what to measure' instead of 'what to fix'")
    ap.add_argument("--fixture", default=None,
                     help="Path to fixture.yaml (rubric/meta mode)")
    ap.add_argument("--override-fixture", action="store_true",
                     help="Rubric mode only: explicitly opt out of pre-registered "
                          "fixture values, using CLI flags instead. The override is "
                          "logged in the run dir and the run is flagged post-hoc.")
    ap.add_argument("--criteria-met", type=int, default=None,
                     help="Article VI gate: number of triage criteria (0-5) that "
                          "hold for this problem. Headless callers must pass this "
                          "(or --skip-article-vi). Interactive runs are prompted.")
    ap.add_argument("--skip-article-vi", action="store_true",
                     help="Bypass the Article VI triage gate (operator asserts "
                          "they've already done the triage). Logged to stderr.")
    args = ap.parse_args()

    # === Article VI gate (Step 0 from SKILL.md) ===
    # The dispatch flow refuses cargo-cult invocations: <2 of 5 triage
    # criteria → exit 2 with a denial message. This must run BEFORE any
    # mode-specific setup so cohort sampling / API key checks / run-dir
    # creation don't fire for refused dispatches.
    ok, msg = _check_article_vi(args)
    if not ok:
        print(msg, file=sys.stderr)
        return 2

    # Discovery mode fills defaults inline; rubric mode resolves them from
    # fixture-vs-CLI in run_rubric. Apply discovery defaults here.
    if args.mode == "discovery":
        if args.n is None:
            args.n = 15
        if args.sampling is None:
            args.sampling = "bucket"
        try:
            args.model = resolve_persona_model(args.model)
            args.effort = resolve_persona_effort(args.effort)
            args.judge_model = resolve_judge_model(args.judge_model)
            args.judge_effort = resolve_judge_effort(args.judge_effort)
        except ValueError as exc:
            print(f"Persona runtime configuration error: {exc}", file=sys.stderr)
            return 2
        if args.n < 11:
            print(f"Warning: N={args.n} is below the recommended floor (11 = "
                  f"one per bucket). Continuing anyway, but bucket coverage "
                  f"will be incomplete.")

    # Resolve problem from file if given a path
    if args.problem and Path(args.problem).is_file():
        args.problem = Path(args.problem).read_text(encoding="utf-8")

    if args.mode == "discovery":
        if not args.problem:
            sys.exit("Discovery mode requires a problem statement")
        return run_discovery(args)
    elif args.mode == "rubric":
        try:
            return run_rubric(args)
        except ValueError as exc:
            print(f"Persona runtime configuration error: {exc}", file=sys.stderr)
            return 2
    elif args.mode == "meta":
        return run_meta(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
