"""Modal batch fan-out template — parallelize per-item work across many containers.

Run:          modal run batch_map.py --n 100
Detached:     modal run --detach batch_map.py --n 100   (survives your laptop closing)
Pull output:  modal volume get batch-fanout-out results.json ./results.json

PERIMETER: inputs must be egress-safe (public / synthetic / OSS). Never feed
sensitive Example data (credentials, session transcripts, detection data) to Modal.
"""
import json

import modal

app = modal.App("batch-fanout")

# Dependencies install into the REMOTE container image, not on your laptop.
image = modal.Image.debian_slim().pip_install("numpy")

# Durable distributed storage: survives container exit AND your laptop closing.
vol = modal.Volume.from_name("batch-fanout-out", create_if_missing=True)


@app.function(image=image, timeout=60 * 60)
def score_one(item: dict) -> dict:
    """Per-item work. Replace with your real metric / transform / inference."""
    x = item["value"]
    return {"id": item["id"], "score": x * x}


@app.function(volumes={"/out": vol})
def write_results(results: list) -> str:
    with open("/out/results.json", "w", encoding="utf-8") as f:
        json.dump(results, f)
    vol.commit()  # persist before the container exits
    return f"/out/results.json ({len(results)} rows)"


@app.local_entrypoint()
def main(n: int = 100):
    items = [{"id": i, "value": i} for i in range(n)]
    results = []
    # .map fans out across containers (max 1000 concurrent). return_exceptions
    # keeps a single failure from killing the whole batch.
    for r in score_one.map(items, return_exceptions=True):
        results.append({"error": str(r)} if isinstance(r, Exception) else r)
    ok = sum(1 for r in results if "error" not in r)
    print(f"done: {ok}/{len(results)} succeeded")
    print("wrote", write_results.remote(results))
