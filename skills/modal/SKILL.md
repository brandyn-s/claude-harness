---
name: modal
description: "Offload compute-heavy, egress-safe work to Modal serverless GPUs/containers from Claude Code: parallel batch fan-out, Sandboxes for untrusted/LLM-generated code, GPU model hosting, and durable long-running jobs."
when_to_use: "Use when a workload is (a) embarrassingly parallel over many inputs (per-query eval scoring, batch judging orchestration), (b) needs a GPU you don't have locally (open-model inference, embeddings, rerankers), (c) must run untrusted or LLM-generated code in isolation (vuln-discovery harness, PoC execution), or (d) is a long/expensive run that must survive your laptop closing (detach + durable Volume). ALL inputs must be egress-safe (public, synthetic, or OSS data). Trigger phrases: 'run on Modal', 'offload to Modal', 'fan this out', 'parallelize this batch', 'sandbox this code', 'need a GPU'. Do NOT use for: sensitive Example data of any kind (credentials, session transcripts, detection data, production security infra), production detection jobs (those stay in AWS GovCloud), or trivial local jobs that finish in seconds."
disable-model-invocation: false
argument-hint: "[what to offload, e.g. 'fan out this eval over 500 queries', 'sandbox this generated exploit', 'serve bge-reranker on a GPU']"
effort: medium
compatibility:
  requires:
    - cli: modal
  optional: []
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: AskUserQuestion Bash Read Write
---

## modal

# Modal — Offload Compute to Serverless GPUs/Containers

Run parallel batch jobs, GPU inference, untrusted-code sandboxes, and durable
long-running jobs on Modal's serverless cloud, driven from Claude Code via the
`modal` CLI. You write plain Python; Modal containerizes it and scales from zero
to hundreds of containers, then back to zero when idle (per-second billing).

## Perimeter gate — read first (non-negotiable)

Modal is **external commercial compute** (Modal's own cloud), NOT the Example AWS
perimeter. Before offloading anything:

- **NEVER send sensitive Example data to Modal** — credentials, session
  transcripts, OTel/detection data, customer data, production security infra, or
  anything with real secrets. That data stays in AWS (GovCloud / in-perimeter
  Bedrock).
- **Egress-safe inputs ONLY**: public data, synthetic fixtures, open-source code,
  published benchmarks, your own non-sensitive experiments.
- **Production detection stays in AWS** (Lambda/ECS). Modal is for
  ad-hoc / experimental / eval compute, not the security pipeline.
- If a workload *needs* sensitive data to be useful, it is **not** a Modal
  candidate — keep it in-perimeter.

If you cannot confirm the inputs are egress-safe, **ask the user before
proceeding** (AskUserQuestion).

## When to reach for Modal

| Workload shape | Modal primitive | Example |
|---|---|---|
| Embarrassingly parallel over many inputs | `Function.map()` fan-out | per-query eval scoring, batch orchestration |
| Needs a GPU you don't have locally | `@app.function(gpu=...)` | open-model inference, embeddings, rerankers |
| Untrusted / LLM-generated code | `Sandbox` | vuln-harness PoC execution, running an untrusted repo's tests |
| Long/expensive run that must survive your laptop | `modal run --detach` + `Volume` | multi-hour eval / measurement runs |

If none of these fit (trivial local job, sensitive data, production pipeline),
don't use Modal.

## Prerequisites

1. **CLI installed** — isolated venv on Python 3.13, symlinked to
   `/opt/homebrew/bin/modal`. Verify: `modal --version` prints `modal client
   version: 1.5.x`.
2. **Authenticated** — run `modal setup` (opens a browser; one-time). If
   `~/.modal.toml` is absent, you are not authenticated. Verify with
   `modal profile current`.
3. **New account** — sign up at modal.com, then `modal setup`. New accounts
   include roughly 30 dollars of free compute.

## Core primitives (accurate as of client 1.5.1)

```python
import modal

app = modal.App("my-job")                                   # namespace + deploy unit

# Dependencies install into the REMOTE container image, not on your laptop:
image = modal.Image.debian_slim().pip_install("numpy", "torch")

vol = modal.Volume.from_name("my-out", create_if_missing=True)   # durable storage

@app.function(image=image, gpu="L4", volumes={"/out": vol}, timeout=3600)
def work(x):
    ...

@app.local_entrypoint()
def main(n: int = 100):
    # .map fans out across containers; results come back ordered like the inputs.
    for r in work.map(range(n), return_exceptions=True):
        ...
```

Run it:
- `modal run my_job.py` — ephemeral (stops when your terminal exits)
- `modal run --detach my_job.py` — **survives your laptop closing** (long jobs)
- `modal deploy my_job.py` — persistent app (for scheduled / `modal.Cron` jobs)
- `modal app list` / `modal app logs <name>` — monitor
- `modal volume get my-out results.json ./results.json` — pull durable output

Secrets (for egress-safe API keys the remote function needs):
`@app.function(secrets=[modal.Secret.from_name("my-secret")])`, created via
`modal secret create my-secret KEY=value`. **Do not put Example production
secrets in Modal Secrets** (perimeter gate).

## Templates (ready to run)

- `templates/batch_map.py` — parallel fan-out with `return_exceptions` + durable
  Volume output. The pattern for eval-harness / batch-orchestration work
  (per-query scoring across hundreds of containers).
  Run: `modal run skills/modal/templates/batch_map.py --n 100`
- `templates/sandbox_runner.py` — run untrusted / LLM-generated code in an
  isolated Sandbox, capturing stdout + exit code. The pattern for vuln-harness
  PoC execution.
  Run: `modal run skills/modal/templates/sandbox_runner.py`

Copy a template into a worktree/scratch dir, adapt `work()` / the sandbox
command, and run. (Don't edit under `~/.claude` — copy out first.)

## Gotchas

- **Python 3.14 is unsupported by the modal client** — that's why the CLI lives
  in a dedicated 3.13 venv (`~/.modal-cli`). A standalone Sandbox script run as
  `python foo.py` needs that interpreter (`~/.modal-cli/bin/python foo.py`);
  `modal run foo.py` sidesteps this (it uses the client's own interpreter).
- `.map()` caps at **1000 concurrent** inputs per call; **2000 pending / 25000
  total** input limit per function (use `.spawn()` for up to 1M async inputs).
- **`return_exceptions=True`** on `.map()` returns failures inline as `Exception`
  objects instead of killing the batch — always use it for long fan-outs.
- **Volume writes need `.commit()`** (or rely on automatic background commits +
  the on-shutdown commit); a reader in another container needs `.reload()` to
  see them. Last-write-wins on the same file — don't write one file from many
  containers at once.
- **Sandboxes default to a 5-minute timeout** (max 24h via `timeout=`); call
  `.terminate()` + `.detach()` when done.
- Files written outside the mounted Volume path (e.g. container `/tmp`) are lost
  when the container exits — write results under the Volume mount.

## Examples

**1. Fan out an eval over 500 egress-safe queries**
> User: "score these 500 public benchmark queries in parallel"

Confirm the queries are egress-safe (perimeter gate), adapt `batch_map.py`'s
`score_one()` to your scorer, then `modal run --detach batch_map.py --n 500`.
Pull results with `modal volume get`.

**2. Run a model-generated exploit safely**
> User: "run this generated PoC without it touching my machine"

Confirm the PoC targets a public/synthetic target (perimeter gate), drop the code
into `sandbox_runner.py`, `modal run sandbox_runner.py`, read the exit code +
stdout.

## Success criteria

- Perimeter gate applied: inputs confirmed egress-safe before any offload (asked
  the user if uncertain).
- `modal --version` works and `modal setup` has been run (auth confirmed).
- The job ran end-to-end: a real `modal run` completed and (for batch) durable
  output landed in the Volume.
- For long jobs, `--detach` was used so the run survives the laptop closing.
